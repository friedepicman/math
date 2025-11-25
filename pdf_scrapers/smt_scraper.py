#!/usr/bin/env python3
"""
SMT PDF Scraper - Downloads all PDFs from Stanford Math Tournament (2011-2024)
Run: python smt_scraper.py
Output: smt_pdfs/ folder with PDFs and manifest.csv
"""

import requests
import os
import time
import random
import csv

OUTPUT_DIR = "smt_pdfs"
BASE_URL = "https://www.stanfordmathtournament.org/pdfs"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Years available based on the website navigation
YEARS = [2024, 2023, 2022, 2021, 2020, 2019, 2018, 2014, 2013, 2012, 2011]

# Test types - Individual
INDIVIDUAL_TESTS = [
    "algebra",
    "geometry", 
    "calculus",
    "discrete",          # Also called "advanced-topics" in some years
    "advanced-topics",
    "general",
]

# Test types - Team
TEAM_TESTS = [
    "team",
    "power",
]

# Tiebreakers (individual subjects)
TIEBREAKER_SUBJECTS = [
    "algebra",
    "geometry",
    "calculus", 
    "discrete",
    "general",
]

# Document types
DOC_TYPES = ["problems", "solutions"]

def build_pdf_links():
    """Build list of all potential PDF URLs to try"""
    links = []
    
    for year in YEARS:
        year_prefix = f"smt{year}"
        
        # Individual tests
        for test in INDIVIDUAL_TESTS:
            for doc_type in DOC_TYPES:
                links.append({
                    'year': year,
                    'round': test.replace('-', '').title(),
                    'category': 'Individual',
                    'type': doc_type.title(),
                    'url': f"{BASE_URL}/{year_prefix}/{test}-{doc_type}.pdf",
                    'filename': f"SMT_{year}_{test.replace('-', '').title()}_{doc_type.title()}.pdf"
                })
        
        # Team tests
        for test in TEAM_TESTS:
            for doc_type in DOC_TYPES:
                links.append({
                    'year': year,
                    'round': test.title(),
                    'category': 'Team',
                    'type': doc_type.title(),
                    'url': f"{BASE_URL}/{year_prefix}/{test}-{doc_type}.pdf",
                    'filename': f"SMT_{year}_{test.title()}_{doc_type.title()}.pdf"
                })
        
        # Tiebreakers
        for subject in TIEBREAKER_SUBJECTS:
            for doc_type in DOC_TYPES:
                links.append({
                    'year': year,
                    'round': f"{subject.title()}Tiebreaker",
                    'category': 'Tiebreaker',
                    'type': doc_type.title(),
                    'url': f"{BASE_URL}/{year_prefix}/{subject}-tiebreaker-{doc_type}.pdf",
                    'filename': f"SMT_{year}_{subject.title()}Tiebreaker_{doc_type.title()}.pdf"
                })
        
        # Results PDFs
        links.append({
            'year': year,
            'round': 'Results',
            'category': 'Results',
            'type': 'Results',
            'url': f"{BASE_URL}/{year_prefix}/results.pdf",
            'filename': f"SMT_{year}_Results.pdf"
        })
        
        # Online results (for years that had online versions)
        if year >= 2020:
            links.append({
                'year': year,
                'round': 'ResultsOnline',
                'category': 'Results',
                'type': 'Results',
                'url': f"{BASE_URL}/{year_prefix}/results-online.pdf",
                'filename': f"SMT_{year}_ResultsOnline.pdf"
            })
    
    return links

def download_pdf(url, filepath):
    """Download PDF from URL, return True if successful"""
    if os.path.exists(filepath):
        print(f"  Skip: {os.path.basename(filepath)}")
        return True
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code == 200:
            content = response.content
            # Verify it's a PDF
            if content[:4] == b'%PDF':
                with open(filepath, 'wb') as f:
                    f.write(content)
                print(f"  OK: {os.path.basename(filepath)} ({len(content):,} bytes)")
                return True
            else:
                print(f"  FAIL (not PDF): {os.path.basename(filepath)}")
        elif response.status_code == 404:
            print(f"  404: {os.path.basename(filepath)}")
        else:
            print(f"  FAIL ({response.status_code}): {os.path.basename(filepath)}")
            
    except Exception as e:
        print(f"  ERR: {e}")
    
    return False

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Build all potential links
    all_links = build_pdf_links()
    
    # Sort by year (descending), then round
    all_links.sort(key=lambda x: (-x['year'], x['round'], x['type']))
    
    print(f"SMT Scraper: Trying {len(all_links)} potential PDFs")
    print(f"Years: {min(YEARS)}-{max(YEARS)}")
    print("=" * 50)
    
    ok = fail = skip_404 = 0
    successful_entries = []
    
    for i, entry in enumerate(all_links, 1):
        print(f"[{i}/{len(all_links)}] {entry['year']} {entry['round']} {entry['type']}")
        filepath = os.path.join(OUTPUT_DIR, entry['filename'])
        
        # Try to download
        try:
            response = requests.head(entry['url'], headers=HEADERS, timeout=10)
            if response.status_code == 404:
                print(f"  404: {os.path.basename(filepath)}")
                skip_404 += 1
                continue
        except:
            pass  # If HEAD fails, try GET anyway
        
        if download_pdf(entry['url'], filepath):
            ok += 1
            successful_entries.append(entry)
        else:
            fail += 1
        
        time.sleep(random.uniform(0.3, 0.8))
    
    # Write manifest (only successful downloads)
    manifest_path = os.path.join(OUTPUT_DIR, "manifest.csv")
    with open(manifest_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['competition', 'year', 'round', 'category', 'type', 'filename', 'url'])
        for entry in successful_entries:
            writer.writerow([
                'SMT',
                entry['year'],
                entry['round'],
                entry['category'],
                entry['type'],
                entry['filename'],
                entry['url']
            ])
    
    print("=" * 50)
    print(f"Done! OK:{ok} FAIL:{fail} 404:{skip_404}")
    print(f"Output: {OUTPUT_DIR}/")
    print(f"Manifest: {manifest_path} ({len(successful_entries)} entries)")

if __name__ == "__main__":
    main()