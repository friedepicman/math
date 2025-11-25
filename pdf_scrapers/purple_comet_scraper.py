#!/usr/bin/env python3
"""
Purple Comet Math Meet Scraper v2

Downloads:
1. Problem PDFs (e.g., 2025HS_English.pdf)
2. Solution PDFs (e.g., 2024HSSolutions.pdf) - only recent years have these
3. Answer tables scraped from HTML pages → saved to CSV
"""

import os
import csv
import requests
from pathlib import Path
import time
import random
import re
from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://purplecomet.org"
PDF_PROBLEMS_BASE = f"{BASE_URL}/files"
PDF_SOLUTIONS_BASE = f"{BASE_URL}/views/data"
OUTPUT_DIR = Path("purplecomet_pdfs")
ANSWERS_DIR = OUTPUT_DIR / "answers"
MANIFEST_FILE = OUTPUT_DIR / "manifest.csv"

TIMEOUT = 30
MIN_DELAY = 4.0
MAX_DELAY = 6.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://purplecomet.org/",
    "Accept": "application/pdf,*/*",
}

# All years (2015 missing from site)
ALL_YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 
             2014, 2013, 2012, 2011, 2010, 2009, 2008, 2007, 2006, 2005]

DIVISIONS = [
    ("HS", "High School"),
    ("MS", "Middle School"),
]

# ============================================================================
# PDF DOWNLOAD
# ============================================================================

def get_pdf_url_from_page(year, div_code, doc_type):
    """Parse the HTML page to find the actual PDF URL from the iframe."""
    if doc_type == "Problems":
        page_url = f"{BASE_URL}/problems/{year}{div_code.lower()}"
    else:
        # Solutions pages might have different URL pattern
        page_url = f"{BASE_URL}/solutions/{year}{div_code.lower()}"
    
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        
        soup = BeautifulSoup(r.text, 'html.parser')
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            src = iframe['src']
            # Make sure it's a full URL
            if src.startswith('/'):
                return BASE_URL + src
            elif src.startswith('http'):
                return src
            else:
                return BASE_URL + '/' + src
        return None
    except:
        return None


def generate_pdf_entries():
    """Generate PDF entries to try downloading."""
    entries = []
    
    for year in ALL_YEARS:
        for div_code, div_name in DIVISIONS:
            # Problems PDF only: /files/{year}{div}_English.pdf
            entries.append({
                "year": year,
                "division": div_code,
                "division_name": div_name,
                "type": "Problems",
                "urls": [
                    f"{PDF_PROBLEMS_BASE}/{year}{div_code}_English.pdf",
                    f"{PDF_PROBLEMS_BASE}/{year}{div_code}.pdf",  # fallback
                ],
                "filename": f"PurpleComet_{year}_{div_code}_Problems.pdf",
                "display_name": f"Purple Comet {year} {div_name} Problems",
            })
    
    return entries


def download_pdf(entry, output_dir, max_retries=2):
    """Try downloading PDF from multiple possible URLs. Returns (success, message, url_used)."""
    filepath = output_dir / entry["filename"]
    
    if filepath.exists():
        return True, "exists", None
    
    # Set Referer to the page that would normally embed this PDF
    if entry["type"] == "Problems":
        referer = f"{BASE_URL}/problems/{entry['year']}{entry['division'].lower()}"
    else:
        referer = f"{BASE_URL}/answers/{entry['year']}{entry['division'].lower()}"
    
    headers = HEADERS.copy()
    headers["Referer"] = referer
    
    # First, try the static URL guesses
    for url in entry["urls"]:
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT)
            
            if r.status_code == 200 and r.content[:4] == b'%PDF':
                filepath.write_bytes(r.content)
                return True, f"{len(r.content)//1024}KB", url
                    
        except requests.exceptions.RequestException:
            continue
    
    # If static URLs failed, try parsing the HTML page for the real URL
    dynamic_url = get_pdf_url_from_page(entry["year"], entry["division"], entry["type"])
    if dynamic_url:
        try:
            time.sleep(1)  # Small delay
            r = requests.get(dynamic_url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200 and r.content[:4] == b'%PDF':
                filepath.write_bytes(r.content)
                return True, f"{len(r.content)//1024}KB (dynamic)", dynamic_url
        except:
            pass
    
    return False, "not-found", None


# ============================================================================
# ANSWER TABLE SCRAPING
# ============================================================================

def get_answer_page_url(year, div_code):
    """Get the URL for the answers page."""
    # URL pattern: /answers/2024hs or /answers/2024ms
    return f"{BASE_URL}/answers/{year}{div_code.lower()}"


def scrape_answers(year, div_code, div_name):
    """Scrape answer table from HTML page. Returns list of (problem_num, answer) tuples."""
    url = get_answer_page_url(year, div_code)
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None, f"http-{r.status_code}"
        
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Find the table with answers
        table = soup.find('table')
        if not table:
            return None, "no-table"
        
        answers = []
        rows = table.find_all('tr')
        
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 2:
                prob_text = cells[0].get_text(strip=True)
                ans_text = cells[1].get_text(strip=True)
                
                # Skip header row
                if prob_text.lower() in ['problem #', 'problem', '#']:
                    continue
                
                # Try to parse problem number
                try:
                    prob_num = int(prob_text)
                    answers.append((prob_num, ans_text))
                except ValueError:
                    continue
        
        if answers:
            return answers, "ok"
        return None, "no-answers"
        
    except requests.exceptions.RequestException as e:
        return None, f"error"


def save_answers_csv(answers, year, div_code, output_dir):
    """Save answers to a CSV file."""
    filename = f"PurpleComet_{year}_{div_code}_Answers.csv"
    filepath = output_dir / filename
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["problem", "answer"])
        for prob_num, answer in sorted(answers):
            writer.writerow([prob_num, answer])
    
    return filename


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Purple Comet Math Meet Scraper v2")
    print("=" * 50)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    
    # -------------------------
    # Part 1: Download PDFs
    # -------------------------
    print("\n[1/2] Downloading PDFs...")
    print("-" * 40)
    
    entries = generate_pdf_entries()
    successful_pdfs = []
    
    for i, entry in enumerate(entries):
        success, msg, url_used = download_pdf(entry, OUTPUT_DIR)
        
        if success:
            sym = "✓" if msg != "exists" else "·"
            print(f"[{i+1}/{len(entries)}] {sym} {entry['display_name']} ({msg})")
            successful_pdfs.append(entry)
        else:
            print(f"[{i+1}/{len(entries)}] - {entry['display_name']} ({msg})")
        
        # Delay after every request (not just successful ones) to avoid rate limiting
        if msg != "exists":
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    
    # -------------------------
    # Part 2: Scrape Answers
    # -------------------------
    print("\n[2/2] Scraping answer tables...")
    print("-" * 40)
    
    answer_entries = []
    total_answers = len(ALL_YEARS) * len(DIVISIONS)
    count = 0
    
    for year in ALL_YEARS:
        for div_code, div_name in DIVISIONS:
            count += 1
            display = f"Purple Comet {year} {div_name} Answers"
            
            answers, status = scrape_answers(year, div_code, div_name)
            
            if answers:
                filename = save_answers_csv(answers, year, div_code, ANSWERS_DIR)
                print(f"[{count}/{total_answers}] ✓ {display} ({len(answers)} problems)")
                answer_entries.append({
                    "year": year,
                    "division": div_code,
                    "division_name": div_name,
                    "type": "Answers",
                    "filename": f"answers/{filename}",
                    "num_problems": len(answers),
                })
                time.sleep(random.uniform(0.5, 1.0))
            else:
                print(f"[{count}/{total_answers}] - {display} ({status})")
    
    # -------------------------
    # Write manifest
    # -------------------------
    with open(MANIFEST_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, ["year", "division", "division_name", "type", "filename"])
        writer.writeheader()
        
        # PDFs
        for e in sorted(successful_pdfs, key=lambda x: (-x["year"], x["division"], x["type"])):
            writer.writerow({k: e[k] for k in ["year", "division", "division_name", "type", "filename"]})
        
        # Answers
        for e in sorted(answer_entries, key=lambda x: (-x["year"], x["division"])):
            writer.writerow({k: e[k] for k in ["year", "division", "division_name", "type", "filename"]})
    
    # Summary
    print(f"\n{'='*50}")
    print(f"PDFs downloaded: {len([e for e in successful_pdfs])}")
    print(f"Answer tables scraped: {len(answer_entries)}")
    print(f"Manifest: {MANIFEST_FILE}")
    print(f"Files saved to: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    main()