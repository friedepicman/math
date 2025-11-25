#!/usr/bin/env python3
"""
HMMT (Harvard-MIT Mathematics Tournament) PDF Scraper

Downloads all problems and solutions PDFs from HMMT's S3 archive.

Tournaments:
- November: General, Theme, Team, Guts
- February: Algebra/NT, Geometry, Combinatorics, Team, Guts

Usage:
    pip install requests
    python hmmt_scraper.py
"""

import os
import csv
import requests
from pathlib import Path
import time
import random
from dataclasses import dataclass
from typing import Optional, List

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL_NEW = "https://hmmt-archive.s3.amazonaws.com/tournaments"
OUTPUT_DIR = Path("hmmt_pdfs")
MANIFEST_FILE = OUTPUT_DIR / "manifest.csv"

# Request settings
TIMEOUT = 30
MIN_DELAY = 0.5
MAX_DELAY = 1.5
RETRY_ATTEMPTS = 2
RETRY_DELAY = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# ============================================================================
# CONTEST DEFINITIONS
# ============================================================================

# Years available (newer format: 2012+)
NOVEMBER_YEARS = list(range(2025, 2007, -1))  # 2025 down to 2008
FEBRUARY_YEARS = list(range(2025, 2007, -1))  # 2025 down to 2008

# Round codes for each tournament
NOVEMBER_ROUNDS = [
    (["gen"], "General"),
    (["thm"], "Theme"),
    (["team"], "Team"),
    (["guts"], "Guts"),
]

FEBRUARY_ROUNDS = [
    (["algnt", "alg"], "Algebra"),      # "algnt" is new, "alg" is old
    (["geo"], "Geometry"),
    (["comb"], "Combinatorics"),
    (["team"], "Team"),
    (["guts"], "Guts"),
]

DOC_TYPES = ["problems", "solutions"]

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class PDFEntry:
    competition: str      # "HMMT November" or "HMMT February"
    year: int
    round_name: str       # e.g., "Geometry", "General"
    doc_type: str         # "problems" or "solutions"
    url: str
    filename: str
    display_name: str     # e.g., "HMMT February 2024 Geometry"
    alt_urls: List[str] = None  # Alternative URLs to try if primary fails
    
    def __post_init__(self):
        if self.alt_urls is None:
            self.alt_urls = []
    
    def to_row(self) -> dict:
        return {
            "competition": self.competition,
            "year": self.year,
            "round": self.round_name,
            "type": self.doc_type,
            "display_name": self.display_name,
            "filename": self.filename,
            "url": self.url,
        }

# ============================================================================
# URL GENERATION
# ============================================================================

def generate_november_entries() -> List[PDFEntry]:
    """Generate all HMMT November PDF entries."""
    entries = []
    for year in NOVEMBER_YEARS:
        for round_codes, round_name in NOVEMBER_ROUNDS:
            for doc_type in DOC_TYPES:
                primary_code = round_codes[0]
                url = f"{BASE_URL_NEW}/{year}/nov/{primary_code}/{doc_type}.pdf"
                display_name = f"HMMT November {year} {round_name}"
                
                alt_urls = [f"{BASE_URL_NEW}/{year}/nov/{code}/{doc_type}.pdf" 
                           for code in round_codes[1:]]
                
                entries.append(PDFEntry(
                    competition="HMMT November",
                    year=year,
                    round_name=round_name,
                    doc_type=doc_type,
                    url=url,
                    filename=f"HMMT_November_{year}_{round_name}_{doc_type.capitalize()}.pdf",
                    display_name=display_name,
                    alt_urls=alt_urls,
                ))
    return entries


def generate_february_entries() -> List[PDFEntry]:
    """Generate all HMMT February PDF entries."""
    entries = []
    for year in FEBRUARY_YEARS:
        for round_codes, round_name in FEBRUARY_ROUNDS:
            for doc_type in DOC_TYPES:
                # Use first code for primary URL, store alternates
                primary_code = round_codes[0]
                url = f"{BASE_URL_NEW}/{year}/feb/{primary_code}/{doc_type}.pdf"
                display_name = f"HMMT February {year} {round_name}"
                
                # Build list of alternate URLs to try
                alt_urls = [f"{BASE_URL_NEW}/{year}/feb/{code}/{doc_type}.pdf" 
                           for code in round_codes[1:]]
                
                entries.append(PDFEntry(
                    competition="HMMT February",
                    year=year,
                    round_name=round_name,
                    doc_type=doc_type,
                    url=url,
                    filename=f"HMMT_February_{year}_{round_name}_{doc_type.capitalize()}.pdf",
                    display_name=display_name,
                    alt_urls=alt_urls,
                ))
    return entries


def generate_all_entries() -> List[PDFEntry]:
    """Generate all PDF entries."""
    return generate_november_entries() + generate_february_entries()

# ============================================================================
# DOWNLOAD FUNCTIONS
# ============================================================================

def download_pdf(entry: PDFEntry, output_dir: Path):
    """
    Download a PDF. Returns (success, error_message).
    Tries alternate URLs if primary fails with 404/403.
    """
    filepath = output_dir / entry.filename
    
    # Skip if already exists
    if filepath.exists():
        return True, "already exists"
    
    # Build list of URLs to try
    urls_to_try = [entry.url] + entry.alt_urls
    
    for url in urls_to_try:
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'pdf' in content_type or response.content[:4] == b'%PDF':
                    filepath.write_bytes(response.content)
                    return True, None
                else:
                    continue  # Try next URL
            elif response.status_code == 404 or response.status_code == 403:
                continue  # Try next URL
            else:
                return False, f"HTTP {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "timeout"
        except requests.exceptions.RequestException as e:
            return False, str(e)
    
    # All URLs failed
    return False, "404 not found"


def download_all(entries: List[PDFEntry], output_dir: Path) -> List[PDFEntry]:
    """
    Download all PDFs with retry logic.
    Returns list of successfully downloaded entries.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    successful = []
    failed = []
    skipped = []
    
    total = len(entries)
    
    for i, entry in enumerate(entries, 1):
        # Try to download with retries
        success = False
        last_error = None
        
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            result, message = download_pdf(entry, output_dir)
            
            if result:
                success = True
                last_error = message
                break
            
            last_error = message
            
            # Don't retry 404s
            if "404" in str(message) or "403" in str(message):
                break
                
            if attempt < RETRY_ATTEMPTS:
                print(f"    Retry {attempt}/{RETRY_ATTEMPTS} in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
        
        # Log result
        status = "✓" if success else "✗"
        detail = f" ({last_error})" if last_error else ""
        print(f"[{i}/{total}] {status} {entry.display_name} {entry.doc_type}{detail}")
        
        if success:
            if last_error == "already exists":
                skipped.append(entry)
            successful.append(entry)
        else:
            failed.append((entry, last_error))
        
        # Rate limiting (only for new downloads)
        if success and last_error != "already exists":
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Downloaded: {len(successful) - len(skipped)}")
    print(f"Skipped (already exist): {len(skipped)}")
    print(f"Failed/Missing: {len(failed)}")
    
    if failed:
        # Separate 404s from real failures
        not_found = [(e, m) for e, m in failed if "404" in str(m) or "403" in str(m)]
        real_failures = [(e, m) for e, m in failed if "404" not in str(m) and "403" not in str(m)]
        
        if real_failures:
            print(f"\nFailed downloads ({len(real_failures)}):")
            for entry, error in real_failures[:10]:
                print(f"  - {entry.display_name} {entry.doc_type}: {error}")
            if len(real_failures) > 10:
                print(f"  ... and {len(real_failures) - 10} more")
        
        print(f"\nNot found (404/403): {len(not_found)} files")
    
    return successful

# ============================================================================
# MANIFEST GENERATION
# ============================================================================

def write_manifest(entries: List[PDFEntry], manifest_path: Path):
    """Write a CSV manifest of all downloaded PDFs."""
    fieldnames = ["competition", "year", "round", "type", "display_name", "filename", "url"]
    
    with open(manifest_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in sorted(entries, key=lambda e: (e.competition, -e.year, e.round_name, e.doc_type)):
            writer.writerow(entry.to_row())
    
    print(f"\nManifest written to: {manifest_path}")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("HMMT (Harvard-MIT Mathematics Tournament) PDF Scraper")
    print("="*60)
    print(f"Output directory: {OUTPUT_DIR.absolute()}")
    print(f"Tournaments: November (2008-2025), February (2008-2025)")
    print(f"Tip: Existing files are skipped, so you can stop and resume anytime.")
    print()
    
    # Generate all entries
    entries = generate_all_entries()
    print(f"Found {len(entries)} potential PDFs to download")
    print()
    
    try:
        # Download
        successful = download_all(entries, OUTPUT_DIR)
        
        # Write manifest
        if successful:
            write_manifest(successful, MANIFEST_FILE)
        
        print(f"\nDone! PDFs saved to: {OUTPUT_DIR.absolute()}")
        
    except KeyboardInterrupt:
        print(f"\n\nInterrupted! Run again to resume - existing files will be skipped.")


if __name__ == "__main__":
    main()