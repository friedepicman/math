#!/usr/bin/env python3
"""
Mathpix Batch Converter

Converts all competition math PDFs to LaTeX using the Mathpix API.
Supports HMMT, PUMaC, SMT, and BMT PDF directories.

Usage:
    export MATHPIX_APP_ID='your_app_id'
    export MATHPIX_APP_KEY='your_app_key'
    python mathpix_batch.py

Features:
    - Reads manifest.csv from each scraper to get full metadata
    - Tracks source info: competition, year, round, type (problems/solutions)
    - Resumes from where it left off (skips already converted)
    - Saves both .md (preview) and .tex.zip (full LaTeX)
    - Creates combined manifest with all metadata + output paths
"""

import os
import sys
import time
import json
import csv
import requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import argparse

# ============================================================================
# CONFIGURATION
# ============================================================================

APP_ID = os.environ.get("MATHPIX_APP_ID", "")
APP_KEY = os.environ.get("MATHPIX_APP_KEY", "")

# Directories to scan for PDFs
PDF_DIRS = [
    "hmmt_pdfs",
    "pumac_pdfs", 
    "smt_pdfs",
]

# Output directory for converted files
OUTPUT_DIR = Path("mathpix_output")

# State file to track progress
STATE_FILE = OUTPUT_DIR / "conversion_state.json"

# Output manifest with all metadata
OUTPUT_MANIFEST = OUTPUT_DIR / "converted_manifest.csv"

# Rate limiting
DELAY_BETWEEN_UPLOADS = 2.0      # Seconds between starting new conversions
POLL_INTERVAL = 3.0              # Seconds between status checks
MAX_CONCURRENT = 3               # Max PDFs processing at once (Mathpix limit)
MAX_RETRIES = 3                  # Retries on failure

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class PDFEntry:
    """Represents a PDF with its metadata."""
    pdf_path: str
    competition: str          # HMMT, PUMaC, SMT, BMT
    year: int
    round: str                # Geometry, Algebra, Team, etc.
    doc_type: str             # Problems or Solutions
    division: str = ""        # For PUMaC: A or B
    category: str = ""        # For SMT: Individual, Team, Tiebreaker
    display_name: str = ""
    source_url: str = ""
    
    # Output paths (filled after conversion)
    md_path: str = ""
    tex_path: str = ""
    num_pages: int = 0

@dataclass
class ConversionJob:
    pdf_path: str
    pdf_id: Optional[str] = None
    status: str = "pending"      # pending, uploading, processing, completed, failed
    error: Optional[str] = None
    md_path: Optional[str] = None
    tex_path: Optional[str] = None
    pages: int = 0
    retries: int = 0

# ============================================================================
# MATHPIX API
# ============================================================================

class MathpixClient:
    def __init__(self, app_id: str, app_key: str):
        self.app_id = app_id
        self.app_key = app_key
        self.headers = {
            "app_id": app_id,
            "app_key": app_key,
        }
    
    def upload_pdf(self, pdf_path: str) -> dict:
        """Upload a PDF and start conversion. Returns response with pdf_id."""
        options = {
            "conversion_formats": {
                "tex.zip": True,
                "md": True,
            },
            "math_inline_delimiters": ["$", "$"],
            "math_display_delimiters": ["$$", "$$"],
        }
        
        with open(pdf_path, "rb") as f:
            response = requests.post(
                "https://api.mathpix.com/v3/pdf",
                headers=self.headers,
                files={"file": f},
                data={"options_json": json.dumps(options)},
                timeout=120,
            )
        
        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.status_code} - {response.text}")
        
        return response.json()
    
    def check_status(self, pdf_id: str) -> dict:
        """Check conversion status."""
        response = requests.get(
            f"https://api.mathpix.com/v3/pdf/{pdf_id}",
            headers=self.headers,
            timeout=30,
        )
        return response.json()
    
    def download_md(self, pdf_id: str) -> str:
        """Download markdown result."""
        response = requests.get(
            f"https://api.mathpix.com/v3/pdf/{pdf_id}.md",
            headers=self.headers,
            timeout=60,
        )
        return response.text
    
    def download_tex_zip(self, pdf_id: str) -> bytes:
        """Download LaTeX zip file."""
        response = requests.get(
            f"https://api.mathpix.com/v3/pdf/{pdf_id}.tex.zip",
            headers=self.headers,
            timeout=60,
        )
        return response.content

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def load_state(state_file: Path) -> dict:
    """Load conversion state from file."""
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return {"jobs": {}, "completed": [], "failed": []}

def save_state(state: dict, state_file: Path):
    """Save conversion state to file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

# ============================================================================
# PDF DISCOVERY WITH METADATA
# ============================================================================

def load_manifest(manifest_path: Path) -> Dict[str, dict]:
    """Load manifest.csv and return dict keyed by filename."""
    if not manifest_path.exists():
        return {}
    
    entries = {}
    with open(manifest_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.get('filename', '')
            if filename:
                entries[filename] = row
    return entries

def parse_filename_fallback(filename: str, source_dir: str) -> dict:
    """Parse metadata from filename if no manifest entry exists."""
    # Filename patterns:
    # HMMT: HMMT_February_2024_Geometry_Problems.pdf
    # PUMaC: PUMaC_2024_Algebra_A_Problems.pdf
    # SMT: SMT_2024_Algebra_Problems.pdf
    # BMT: BMT_2024_Algebra_Problems.pdf
    
    name = Path(filename).stem
    parts = name.split('_')
    
    result = {
        'competition': parts[0] if parts else source_dir.upper(),
        'year': 0,
        'round': '',
        'type': '',
        'division': '',
    }
    
    # Try to extract year
    for p in parts:
        if p.isdigit() and len(p) == 4:
            result['year'] = int(p)
            break
    
    # Last part is usually Problems/Solutions
    if parts and parts[-1] in ['Problems', 'Solutions']:
        result['type'] = parts[-1].lower()
    
    return result

def find_all_pdfs_with_metadata(directories: List[str]) -> List[PDFEntry]:
    """Find all PDFs and load their metadata from manifests."""
    entries = []
    
    for dir_name in directories:
        dir_path = Path(dir_name)
        if not dir_path.exists():
            continue
        
        # Load manifest if exists
        manifest_path = dir_path / "manifest.csv"
        manifest = load_manifest(manifest_path)
        
        pdf_count = 0
        for pdf_path in dir_path.glob("*.pdf"):
            pdf_count += 1
            filename = pdf_path.name
            
            # Get metadata from manifest or parse from filename
            if filename in manifest:
                row = manifest[filename]
                entry = PDFEntry(
                    pdf_path=str(pdf_path),
                    competition=row.get('competition', ''),
                    year=int(row.get('year', 0)),
                    round=row.get('round', ''),
                    doc_type=row.get('type', ''),
                    division=row.get('division', ''),
                    category=row.get('category', ''),
                    display_name=row.get('display_name', ''),
                    source_url=row.get('url', ''),
                )
            else:
                # Fallback: parse from filename
                parsed = parse_filename_fallback(filename, dir_name)
                entry = PDFEntry(
                    pdf_path=str(pdf_path),
                    competition=parsed['competition'],
                    year=parsed['year'],
                    round=parsed['round'],
                    doc_type=parsed['type'],
                    division=parsed['division'],
                )
            
            entries.append(entry)
        
        manifest_status = "✓" if manifest else "⚠ no manifest"
        print(f"  {dir_name}: {pdf_count} PDFs ({manifest_status})")
    
    return sorted(entries, key=lambda e: (e.competition, -e.year, e.round, e.doc_type))

def get_output_paths(pdf_path: str, output_dir: Path) -> tuple:
    """Get output paths for a PDF."""
    pdf_name = Path(pdf_path).stem
    # Preserve source directory structure
    source_dir = Path(pdf_path).parent.name
    out_subdir = output_dir / source_dir
    out_subdir.mkdir(parents=True, exist_ok=True)
    
    md_path = out_subdir / f"{pdf_name}.md"
    tex_path = out_subdir / f"{pdf_name}.tex.zip"
    return str(md_path), str(tex_path)

# ============================================================================
# BATCH PROCESSOR
# ============================================================================

class BatchProcessor:
    def __init__(self, client: MathpixClient, output_dir: Path, state_file: Path):
        self.client = client
        self.output_dir = output_dir
        self.state_file = state_file
        self.state = load_state(state_file)
        self.converted_entries: List[PDFEntry] = []
    
    def is_completed(self, pdf_path: str) -> bool:
        """Check if a PDF has already been converted."""
        md_path, tex_path = get_output_paths(pdf_path, self.output_dir)
        return Path(md_path).exists() and Path(tex_path).exists()
    
    def process_all(self, entries: List[PDFEntry], dry_run: bool = False):
        """Process all PDFs."""
        # Filter out already completed
        pending = [e for e in entries if not self.is_completed(e.pdf_path)]
        completed_entries = [e for e in entries if self.is_completed(e.pdf_path)]
        
        print(f"\nTotal PDFs: {len(entries)}")
        print(f"Already converted: {len(completed_entries)}")
        print(f"To convert: {len(pending)}")
        
        if dry_run:
            print("\n[DRY RUN] Would convert:")
            for e in pending[:20]:
                print(f"  {e.competition} {e.year} {e.round} {e.doc_type}")
            if len(pending) > 20:
                print(f"  ... and {len(pending) - 20} more")
            return
        
        if not pending:
            print("\nAll PDFs already converted!")
            # Still write manifest for completed ones
            self.write_output_manifest(completed_entries)
            return
        
        # Estimate cost (Mathpix charges per page, roughly $0.004/page)
        print(f"\n⚠️  Estimated cost: ~${len(pending) * 2 * 0.004:.2f} - ${len(pending) * 5 * 0.004:.2f}")
        print("   (Assuming 2-5 pages per PDF at $0.004/page)")
        
        input("\nPress Enter to start, Ctrl+C to cancel...")
        
        # Track all converted (including previously completed)
        self.converted_entries = completed_entries.copy()
        
        # Process pending
        total = len(pending)
        for i, entry in enumerate(pending):
            print(f"\n[{i+1}/{total}] {entry.competition} {entry.year} {entry.round} {entry.doc_type}")
            print(f"         {Path(entry.pdf_path).name}")
            
            try:
                num_pages = self.convert_single(entry)
                entry.num_pages = num_pages
                md_path, tex_path = get_output_paths(entry.pdf_path, self.output_dir)
                entry.md_path = md_path
                entry.tex_path = tex_path
                self.converted_entries.append(entry)
                self.state["completed"].append(entry.pdf_path)
            except KeyboardInterrupt:
                print("\n\nInterrupted! Progress saved. Run again to resume.")
                save_state(self.state, self.state_file)
                self.write_output_manifest(self.converted_entries)
                sys.exit(0)
            except Exception as e:
                print(f"  ❌ Error: {e}")
                self.state["failed"].append({"path": entry.pdf_path, "error": str(e)})
            
            save_state(self.state, self.state_file)
            
            # Rate limit
            if i < total - 1:
                time.sleep(DELAY_BETWEEN_UPLOADS)
        
        # Write final manifest
        self.write_output_manifest(self.converted_entries)
        
        # Summary
        print("\n" + "=" * 60)
        print(f"Completed: {len(self.converted_entries)}")
        print(f"Failed: {len(self.state['failed'])}")
        if self.state["failed"]:
            print("\nFailed files:")
            for f in self.state["failed"][-10:]:
                print(f"  {f['path']}: {f['error']}")
    
    def convert_single(self, entry: PDFEntry) -> int:
        """Convert a single PDF. Returns number of pages."""
        md_path, tex_path = get_output_paths(entry.pdf_path, self.output_dir)
        
        # Upload
        print(f"  📤 Uploading...")
        result = self.client.upload_pdf(entry.pdf_path)
        pdf_id = result.get("pdf_id")
        if not pdf_id:
            raise Exception(f"No pdf_id in response: {result}")
        
        # Poll for completion
        print(f"  ⏳ Processing (ID: {pdf_id})...")
        num_pages = 0
        while True:
            status = self.client.check_status(pdf_id)
            state = status.get("status")
            percent = status.get("percent_done", 0)
            
            if state == "completed":
                num_pages = status.get("num_pages", 0)
                print(f"  ✓ Completed ({num_pages} pages)")
                break
            elif state == "error":
                raise Exception(f"Conversion error: {status.get('error')}")
            else:
                print(f"  ... {state} ({percent}%)", end="\r")
                time.sleep(POLL_INTERVAL)
        
        # Download results
        print(f"  📥 Downloading...")
        
        md_content = self.client.download_md(pdf_id)
        with open(md_path, "w") as f:
            f.write(md_content)
        
        tex_content = self.client.download_tex_zip(pdf_id)
        with open(tex_path, "wb") as f:
            f.write(tex_content)
        
        print(f"  ✓ Saved: {Path(md_path).name}, {Path(tex_path).name}")
        return num_pages
    
    def write_output_manifest(self, entries: List[PDFEntry]):
        """Write manifest with all metadata and output paths."""
        manifest_path = self.output_dir / "converted_manifest.csv"
        
        fieldnames = [
            'competition', 'year', 'round', 'type', 'division', 'category',
            'display_name', 'source_url', 'pdf_path', 'md_path', 'tex_path', 'num_pages'
        ]
        
        with open(manifest_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for e in sorted(entries, key=lambda x: (x.competition, -x.year, x.round, x.doc_type)):
                # Fill in output paths if not set
                if not e.md_path:
                    e.md_path, e.tex_path = get_output_paths(e.pdf_path, self.output_dir)
                
                writer.writerow({
                    'competition': e.competition,
                    'year': e.year,
                    'round': e.round,
                    'type': e.doc_type,
                    'division': e.division,
                    'category': e.category,
                    'display_name': e.display_name,
                    'source_url': e.source_url,
                    'pdf_path': e.pdf_path,
                    'md_path': e.md_path,
                    'tex_path': e.tex_path,
                    'num_pages': e.num_pages,
                })
        
        print(f"\n📋 Manifest written: {manifest_path} ({len(entries)} entries)")

# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Batch convert math PDFs to LaTeX via Mathpix")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be converted without doing it")
    parser.add_argument("--dir", action="append", help="Additional PDF directory to scan")
    parser.add_argument("--output", default="mathpix_output", help="Output directory")
    parser.add_argument("--single", help="Convert a single PDF file")
    args = parser.parse_args()
    
    # Check credentials
    if not APP_ID or not APP_KEY:
        print("Error: Mathpix credentials not set!")
        print("\nSet environment variables:")
        print("  export MATHPIX_APP_ID='your_app_id'")
        print("  export MATHPIX_APP_KEY='your_app_key'")
        print("\nGet credentials at: https://mathpix.com/ocr")
        sys.exit(1)
    
    print("Mathpix Batch Converter")
    print("=" * 60)
    
    output_dir = Path(args.output)
    state_file = output_dir / "conversion_state.json"
    
    client = MathpixClient(APP_ID, APP_KEY)
    processor = BatchProcessor(client, output_dir, state_file)
    
    # Single file mode
    if args.single:
        if not os.path.exists(args.single):
            print(f"Error: File not found: {args.single}")
            sys.exit(1)
        # Create a minimal entry for single file
        entry = PDFEntry(
            pdf_path=args.single,
            competition="Unknown",
            year=0,
            round="Unknown",
            doc_type="unknown",
        )
        processor.convert_single(entry)
        return
    
    # Batch mode - find all PDFs with metadata
    print("\nScanning directories for PDFs and manifests...")
    dirs = PDF_DIRS + (args.dir or [])
    entries = find_all_pdfs_with_metadata(dirs)
    
    if not entries:
        print("\nNo PDFs found! Make sure you have the PDF directories:")
        for d in dirs:
            print(f"  {d}/")
        sys.exit(1)
    
    # Show breakdown by competition
    print("\nBreakdown by competition:")
    by_comp = {}
    for e in entries:
        by_comp[e.competition] = by_comp.get(e.competition, 0) + 1
    for comp, count in sorted(by_comp.items()):
        print(f"  {comp}: {count}")
    
    # Process
    processor.process_all(entries, dry_run=args.dry_run)
    
    print(f"\nOutput directory: {output_dir.absolute()}")

if __name__ == "__main__":
    main()