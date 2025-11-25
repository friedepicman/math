#!/usr/bin/env python3
"""
BMT PDF Scraper v6

Enhanced rate limiting protection:
1. Longer, more randomized delays (10-20s between PDFs)
2. Batch processing with 5-minute pauses every 20 PDFs
3. Exponential backoff on errors
4. Progress tracking to resume safely
5. Conservative default settings

Run overnight for best results!
"""

import requests
import time
import random
import os
import csv
import json
from pathlib import Path
from urllib.parse import urljoin

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://berkeley.mt"
ARCHIVE_URL = "https://berkeley.mt/archives/"
OUTPUT_DIR = Path("bmt_pdfs")
MANIFEST_FILE = OUTPUT_DIR / "manifest.csv"
STATE_FILE = OUTPUT_DIR / "scraper_state.json"

# Delays (seconds) - VERY CONSERVATIVE to avoid rate limiting
DELAY_BETWEEN_PDFS = (10, 20)       # Random range between PDF downloads
DELAY_BETWEEN_YEARS = (30, 60)      # Random range between years
DELAY_AFTER_ARCHIVE = (5, 10)       # After visiting archive page
DELAY_AFTER_ERROR = 120             # 2 minutes after any error
DELAY_AFTER_BATCH = 300             # 5 minutes after every 20 PDFs
BATCH_SIZE = 20                     # PDFs before taking a long break

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
]

# ============================================================================
# BMT STRUCTURE
# ============================================================================

YEARS = list(range(2011, 2025))  # 2011-2024

CATEGORIES = [
    "Algebra",
    "Analysis", 
    "Calculus",
    "Discrete",
    "Geometry",
    "Guts",
    "Team",
    "General",
    "Power",
    "Tiebreaker",
]

def get_year_archive_url(year: int) -> str:
    """Get the archive page URL for a specific year."""
    return f"{BASE_URL}/archive-{year}/"


# ============================================================================
# SCRAPER
# ============================================================================

class BMTScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'DNT': '1',
        })
        self.last_referer = ARCHIVE_URL
        self.state = self.load_state()
        self.pdfs_since_break = 0
        self.error_count = 0
    
    def load_state(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        return {"downloaded": [], "missing": [], "failed": [], "pdfs_count": 0}
    
    def save_state(self):
        self.state["pdfs_count"] = self.pdfs_since_break
        STATE_FILE.write_text(json.dumps(self.state, indent=2))
    
    def random_delay(self, range_tuple):
        """Sleep for a random time within the range."""
        delay = random.uniform(*range_tuple)
        print(f"  [waiting {delay:.1f}s]", end=" ", flush=True)
        time.sleep(delay)
        print("✓")
    
    def check_batch_pause(self):
        """Take a long break after BATCH_SIZE PDFs."""
        if self.pdfs_since_break >= BATCH_SIZE:
            print(f"\n  ⏸  Batch complete ({BATCH_SIZE} PDFs). Taking {DELAY_AFTER_BATCH}s break...")
            print(f"  Time: {time.strftime('%H:%M:%S')}")
            time.sleep(DELAY_AFTER_BATCH)
            print(f"  Resuming at {time.strftime('%H:%M:%S')}")
            self.pdfs_since_break = 0
            self.save_state()
    
    def exponential_backoff(self):
        """Increase delay after repeated errors."""
        self.error_count += 1
        delay = min(DELAY_AFTER_ERROR * (2 ** (self.error_count - 1)), 600)  # Max 10 min
        print(f"  ⚠  Error #{self.error_count}. Backing off {delay}s...")
        time.sleep(delay)
    
    def visit_page(self, url: str, desc: str = "") -> bool:
        """Visit a page to establish navigation history."""
        try:
            print(f"  [visiting {desc or url}]", end=" ", flush=True)
            resp = self.session.get(url, headers={'Referer': self.last_referer}, timeout=30)
            if resp.status_code == 200:
                self.last_referer = url
                print("✓")
                self.error_count = 0  # Reset error counter on success
                return True
            else:
                print(f"✗ status {resp.status_code}")
                return False
        except Exception as e:
            print(f"✗ error: {e}")
            return False
    
    def download_pdf(self, url: str, save_path: Path, year: int) -> str:
        """Download a PDF with proper headers. Returns status."""
        
        # Set referer to the year's archive page
        year_archive = get_year_archive_url(year)
        
        headers = {
            'Referer': year_archive,
            'Accept': 'application/pdf,*/*',
        }
        
        try:
            resp = self.session.get(url, headers=headers, timeout=60)
            
            if resp.status_code == 200:
                content_type = resp.headers.get('Content-Type', '')
                if 'pdf' in content_type.lower() or resp.content[:4] == b'%PDF':
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    save_path.write_bytes(resp.content)
                    self.error_count = 0  # Reset on success
                    return "ok"
                else:
                    return "not-pdf"
            elif resp.status_code == 404:
                return "not-found"
            elif resp.status_code == 403:
                return "forbidden"
            elif resp.status_code == 429:
                return "rate-limited"
            else:
                return f"http-{resp.status_code}"
                
        except requests.exceptions.ConnectionError:
            return "conn-err"
        except requests.exceptions.Timeout:
            return "timeout"
        except Exception as e:
            return f"error-{type(e).__name__}"
    
    def find_pdf_url(self, year: int, category: str, doc_type: str) -> str:
        """Generate most likely PDF URL."""
        
        cat_lower = category.lower()
        
        # Different URL patterns BMT has used over the years
        if doc_type == "problems":
            return f"{BASE_URL}/wp-content/uploads/{year}/bmt-{year}-{cat_lower}.pdf"
        else:
            return f"{BASE_URL}/wp-content/uploads/{year}/bmt-{year}-{cat_lower}-solutions.pdf"
    
    def scrape_year(self, year: int) -> list:
        """Scrape all PDFs for a given year."""
        results = []
        
        # First, visit the year's archive page
        year_url = get_year_archive_url(year)
        if not self.visit_page(year_url, f"{year} archive"):
            # Try alternate URL
            year_url = f"{BASE_URL}/bmt-{year}/"
            if not self.visit_page(year_url, f"{year} archive (alt)"):
                print(f"  Warning: couldn't load {year} archive page")
        
        self.random_delay(DELAY_AFTER_ARCHIVE)
        
        for category in CATEGORIES:
            for doc_type in ["problems", "solutions"]:
                key = f"BMT {year} {category} {doc_type}"
                
                # Skip if already processed
                if key in self.state["downloaded"] or key in self.state["missing"]:
                    continue
                
                filename = f"BMT_{year}_{category}_{doc_type}.pdf"
                save_path = OUTPUT_DIR / filename
                
                url = self.find_pdf_url(year, category, doc_type)
                
                print(f"  {category} {doc_type}: ", end="", flush=True)
                status = self.download_pdf(url, save_path, year)
                print(status)
                
                if status == "ok":
                    self.state["downloaded"].append(key)
                    self.pdfs_since_break += 1
                    results.append({
                        "competition": "BMT",
                        "year": year,
                        "round": category,
                        "doc_type": doc_type,
                        "filename": filename,
                        "url": url,
                    })
                    
                    # Check if we need a batch pause
                    self.check_batch_pause()
                    
                elif status in ["not-found", "not-pdf"]:
                    self.state["missing"].append(key)
                    
                elif status == "rate-limited":
                    print(f"  ⚠⚠ RATE LIMITED! Pausing 10 minutes...")
                    time.sleep(600)
                    self.state["failed"].append(key)
                    
                elif status in ["conn-err", "forbidden", "timeout"]:
                    self.state["failed"].append(key)
                    self.exponential_backoff()
                
                self.save_state()
                
                # Regular delay between PDFs (unless we just took a batch break)
                if self.pdfs_since_break > 0:
                    self.random_delay(DELAY_BETWEEN_PDFS)
        
        return results
    
    def run(self, test_mode: bool = False):
        """Run the full scraper."""
        OUTPUT_DIR.mkdir(exist_ok=True)
        
        print("BMT Scraper v6 - Conservative Mode")
        print("=" * 60)
        print(f"Delays: {DELAY_BETWEEN_PDFS[0]}-{DELAY_BETWEEN_PDFS[1]}s between PDFs")
        print(f"        {DELAY_AFTER_BATCH}s break every {BATCH_SIZE} PDFs")
        print(f"        {DELAY_BETWEEN_YEARS[0]}-{DELAY_BETWEEN_YEARS[1]}s between years")
        print("=" * 60)
        
        # Step 1: Visit main archive page
        print("\n[1] Visiting main archive page...")
        if not self.visit_page(ARCHIVE_URL, "main archive"):
            print("Failed to load archive page. Site may be blocking.")
            return
        
        self.random_delay(DELAY_AFTER_ARCHIVE)
        
        if test_mode:
            print("\n[TEST MODE] Trying just one PDF...")
            url = f"{BASE_URL}/wp-content/uploads/2023/bmt-2023-algebra.pdf"
            status = self.download_pdf(url, OUTPUT_DIR / "test.pdf", 2023)
            print(f"Test result: {status}")
            if status == "ok":
                (OUTPUT_DIR / "test.pdf").unlink()  # cleanup
            return
        
        # Step 2: Scrape each year
        all_results = []
        start_time = time.time()
        
        for year in YEARS:
            print(f"\n[{year}] (Elapsed: {(time.time() - start_time)/60:.1f} min)")
            results = self.scrape_year(year)
            all_results.extend(results)
            
            # Write manifest after each year (incremental save)
            if all_results:
                with open(MANIFEST_FILE, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=all_results[0].keys())
                    writer.writeheader()
                    writer.writerows(all_results)
            
            # Longer delay between years
            if year != YEARS[-1]:
                print(f"\n  Year {year} complete. Taking break before {year+1}...")
                self.random_delay(DELAY_BETWEEN_YEARS)
        
        # Summary
        elapsed = (time.time() - start_time) / 60
        print("\n" + "=" * 60)
        print(f"COMPLETE - Total time: {elapsed:.1f} minutes")
        print(f"Downloaded: {len(self.state['downloaded'])} PDFs")
        print(f"Missing (404): {len(self.state['missing'])}")
        print(f"Failed (conn): {len(self.state['failed'])}")
        print(f"Average rate: {len(self.state['downloaded'])/elapsed:.1f} PDFs/min")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Test mode - just try one PDF")
    parser.add_argument("--reset", action="store_true", help="Reset state and start fresh")
    parser.add_argument("--fast", action="store_true", help="Use faster delays (more risky)")
    args = parser.parse_args()
    
    if args.fast:
        print("⚠  FAST MODE - Using shorter delays (higher risk of rate limiting)")
        DELAY_BETWEEN_PDFS = (5, 10)
        DELAY_BETWEEN_YEARS = (10, 20)
        DELAY_AFTER_BATCH = 120
        BATCH_SIZE = 30
    
    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("State reset.")
    
    scraper = BMTScraper()
    scraper.run(test_mode=args.test)