#!/usr/bin/env python3
"""
MAA Competition Scraper + Processor

Scrapes AIME/AMC problems from AoPS wiki, then:
1. Computes difficulty based on problem number + year
2. Uses Claude Batch API to classify type and rephrase
3. Outputs CSV ready for Supabase import

Usage:
    python maa_scraper_full.py scrape          # Scrape all problems to JSON
    python maa_scraper_full.py submit          # Submit batch for classification + rephrase
    python maa_scraper_full.py poll            # Poll batch status
    python maa_scraper_full.py download        # Download results and create CSV
    python maa_scraper_full.py run             # Do everything
"""

import requests
from bs4 import BeautifulSoup
import csv
import json
import time
import re
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_URL = "https://artofproblemsolving.com/wiki/index.php"
CURRENT_YEAR = 2025

client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# ============ DIFFICULTY FUNCTIONS ============

def get_difficulty_amc8(num):
    if num <= 10: return 1
    if num <= 17: return 1.5
    if num <= 23: return 2
    return 2.5

def get_difficulty_amc10(num):
    if num <= 5: return 1
    if num <= 9: return 1.5
    if num <= 14: return 2
    if num <= 17: return 2.5
    if num <= 20: return 3
    if num <= 22: return 3.5
    if num <= 24: return 4
    return 4.5

def get_difficulty_amc12(num):
    if num <= 5: return 1.5
    if num <= 10: return 2
    if num <= 14: return 2.5
    if num <= 17: return 3
    if num <= 20: return 3.5
    if num == 21: return 4
    if num == 22: return 4.5
    if num == 23: return 5
    if num == 24: return 5.5
    return 6

def get_difficulty_aime(num):
    if num <= 3: return 3
    if num <= 5: return 3.5
    if num <= 8: return 4
    if num <= 10: return 4.5
    if num == 11: return 5
    if num == 12: return 5.5
    if num == 13: return 6
    if num == 14: return 6.5
    return 7

def adjust_difficulty_for_year(base, year):
    """Older problems are slightly easier due to evolution of competition math."""
    age = CURRENT_YEAR - year
    if age <= 8:
        return base
    elif age <= 16:
        return max(1, base - 0.5)
    else:
        return max(1, base - 1)

def compute_difficulty(contest, problem_num, year):
    """Compute difficulty for a problem."""
    if contest == "AIME":
        base = get_difficulty_aime(problem_num)
    elif contest == "AMC_8":
        base = get_difficulty_amc8(problem_num)
    elif contest == "AMC_10":
        base = get_difficulty_amc10(problem_num)
    elif contest == "AMC_12":
        base = get_difficulty_amc12(problem_num)
    else:
        return None
    
    return adjust_difficulty_for_year(base, year)


# ============ URL BUILDERS ============

def build_problem_page(contest, year, variant, problem_num):
    if contest == "AIME":
        if variant is None or year < 2000:
            return f"{year}_AIME_Problems/Problem_{problem_num}"
        return f"{year}_AIME_{variant}_Problems/Problem_{problem_num}"
    elif contest == "AMC_8":
        return f"{year}_AMC_8_Problems/Problem_{problem_num}"
    elif contest in ["AMC_10", "AMC_12"]:
        if variant is None:
            return f"{year}_{contest}_Problems/Problem_{problem_num}"
        return f"{year}_{contest}{variant}_Problems/Problem_{problem_num}"
    return None


def build_answer_key_page(contest, year, variant):
    if contest == "AIME":
        if variant is None or year < 2000:
            return f"{year}_AIME_Answer_Key"
        return f"{year}_AIME_{variant}_Answer_Key"
    elif contest == "AMC_8":
        return f"{year}_AMC_8_Answer_Key"
    elif contest in ["AMC_10", "AMC_12"]:
        if variant is None:
            return f"{year}_{contest}_Answer_Key"
        return f"{year}_{contest}{variant}_Answer_Key"
    return None


def build_problem_link(contest, year, variant, problem_num):
    page = build_problem_page(contest, year, variant, problem_num)
    return f"{BASE_URL}?title={page}" if page else ""


def build_source(contest, year, variant, problem_num):
    if contest == "AIME":
        if variant is None or year < 2000:
            return f"{year} AIME #{problem_num}"
        return f"{year} AIME {variant} #{problem_num}"
    elif contest == "AMC_8":
        return f"{year} AMC 8 #{problem_num}"
    elif contest == "AMC_10":
        if variant is None:
            return f"{year} AMC 10 #{problem_num}"
        return f"{year} AMC 10{variant} #{problem_num}"
    elif contest == "AMC_12":
        if variant is None:
            return f"{year} AMC 12 #{problem_num}"
        return f"{year} AMC 12{variant} #{problem_num}"
    return ""


# ============ SCRAPERS ============

def get_raw_latex(page, section=None, max_retries=5, followed_redirect=None):
    """
    Get raw LaTeX from wiki page using MediaWiki API.
    Returns tuple: (content, redirect_target) where redirect_target is the page we redirected to (or None)
    """
    api_url = "https://artofproblemsolving.com/wiki/api.php"
    params = {
        "action": "query",
        "titles": page.replace("_", " "),  # API uses spaces
        "prop": "revisions",
        "rvprop": "content",
        "format": "json",
        "redirects": "1"  # Automatically follow redirects
    }
    
    for attempt in range(max_retries):
        try:
            res = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
            
            if res.status_code == 429:
                wait_time = 3 ** (attempt + 1)
                print(f"  ⚠️ Rate limited on {page}, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            if res.status_code != 200:
                print(f"  ⚠️ HTTP {res.status_code} on {page}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return None, None
            
            data = res.json()
            
            # Check for redirects
            redirect_target = None
            if "redirects" in data.get("query", {}):
                redirects = data["query"]["redirects"]
                if redirects:
                    redirect_target = redirects[-1]["to"]  # Final redirect target
            
            # Get the page content
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    # Page doesn't exist
                    return None, None
                
                revisions = page_data.get("revisions", [])
                if revisions:
                    content = revisions[0].get("*", "")
                    if content:
                        # If section is specified, extract just that section
                        if section == 1:
                            # Extract Problem section (handles "Problem" or "Problem 23" etc)
                            match = re.search(r'==\s*Problem(?:\s+\d+)?\s*==\s*(.*?)(?=\n==|$)', content, re.DOTALL | re.IGNORECASE)
                            if match:
                                return match.group(1).strip(), redirect_target
                            
                            # Some pages have no "Problem" header - content is before first ==
                            # Skip any {{template}} at the start, then grab until first ==
                            match = re.search(r'^(?:\{\{[^}]+\}\}\s*)*(.*?)(?=\n==)', content, re.DOTALL)
                            if match and match.group(1).strip():
                                return match.group(1).strip(), redirect_target
                                
                        elif section == 2:
                            # Extract Solution section
                            match = re.search(r'==\s*Solutions?(?:\s+\d+)?\s*==\s*(.*?)(?=\n==|$)', content, re.DOTALL | re.IGNORECASE)
                            if match:
                                return match.group(1).strip(), redirect_target
                            # Try alternate solution headers like "Simple Solution"
                            match = re.search(r'==\s*(?:Simple\s+)?Solutions?\s*(?:\d+)?\s*==\s*(.*?)(?=\n==|$)', content, re.DOTALL | re.IGNORECASE)
                            if match:
                                return match.group(1).strip(), redirect_target
                        else:
                            return content, redirect_target
            
            return None, None
            
        except requests.exceptions.Timeout:
            wait_time = 3 ** (attempt + 1)
            print(f"  ⚠️ Timeout on {page}, waiting {wait_time}s...")
            time.sleep(wait_time)
            continue
        except Exception as e:
            print(f"  ⚠️ Exception on {page}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None, None
    
    return None, None


def scrape_problem(contest, year, variant, problem_num):
    """Returns tuple: (problem_text, redirect_target)"""
    page = build_problem_page(contest, year, variant, problem_num)
    raw, redirect_target = get_raw_latex(page, section=1)
    
    if raw:
        # Clean up the problem text (handles "Problem" or "Problem 23" etc)
        raw = re.sub(r"^==\s*Problem(?:\s+\d+)?\s*==\s*", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
    return raw, redirect_target


def scrape_solution(contest, year, variant, problem_num):
    page = build_problem_page(contest, year, variant, problem_num)
    raw, _ = get_raw_latex(page, section=2)
    
    if raw:
        raw = re.sub(r"^==+\s*Solutions?.*?==+\s*", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
        if len(raw) < 20:
            return None
    return raw


def scrape_answer_key(contest, year, variant):
    page = build_answer_key_page(contest, year, variant)
    raw, _ = get_raw_latex(page, section=None)  # Get full page for answer key
    
    if not raw:
        return {}
    
    answers = {}
    
    # Method 1: numbered list format
    matches = re.findall(r'#\s*\(?([A-Ea-e]|\d{1,3})\)?', raw)
    if matches:
        for i, ans in enumerate(matches, 1):
            if ans.isalpha():
                answers[i] = ans.upper()
            else:
                answers[i] = ans.zfill(3) if contest == "AIME" else ans
        return answers
    
    # Method 2: "Problem X: A" format
    matches = re.findall(r'Problem\s*(\d+).*?:\s*\*?\*?\s*\(?([A-Ea-e]|\d{1,3})\)?', raw, re.IGNORECASE)
    for num, ans in matches:
        if ans.isalpha():
            answers[int(num)] = ans.upper()
        else:
            answers[int(num)] = ans.zfill(3) if contest == "AIME" else ans
    
    # Method 3: table format
    if not answers:
        matches = re.findall(r'\|\s*(\d+)\s*\|\s*\*?\*?\s*\(?([A-Ea-e]|\d{1,3})\)?', raw)
        for num, ans in matches:
            if ans.isalpha():
                answers[int(num)] = ans.upper()
            else:
                answers[int(num)] = ans.zfill(3) if contest == "AIME" else ans
    
    return answers


def parse_redirect_source(redirect_target):
    """Parse redirect target like '2013_AMC_12B_Problems/Problem_2' into source string."""
    if not redirect_target:
        return None
    
    # Match pattern: YEAR_AMC_10A_Problems/Problem_N or YEAR_AMC_12B_Problems/Problem_N
    match = re.match(r'(\d{4})_AMC_(10|12)([AB]?)_Problems/Problem_(\d+)', redirect_target)
    if match:
        year, contest_num, variant, prob_num = match.groups()
        variant_str = variant if variant else ""
        return f"{contest_num}{variant_str} #{prob_num}"
    return None


def scrape_single_problem(args):
    """Scrape a single problem - used by thread pool."""
    contest, year, variant, prob_num, answer = args
    
    # Small delay to be nice to the server
    time.sleep(0.05)
    
    problem_text, redirect_target = scrape_problem(contest, year, variant, prob_num)
    
    if not problem_text:
        # Log failure details
        page = build_problem_page(contest, year, variant, prob_num)
        print(f"  ✗ Failed: {page}")
        return None
    
    solution_text = scrape_solution(contest, year, variant, prob_num)
    
    # For AIME, compute numeric aime_answer
    if contest == "AIME" and answer:
        aime_answer = str(int(answer))
    else:
        aime_answer = ""
    
    difficulty = compute_difficulty(contest, prob_num, year)
    
    # Build source string
    base_source = build_source(contest, year, variant, prob_num)
    
    # If redirected, add the redirect target to source
    if redirect_target:
        redirect_source = parse_redirect_source(redirect_target)
        if redirect_source:
            # e.g., "2013 AMC 10B #3" + "12B #2" -> "2013 AMC 10B #3 / 12B #2"
            source = f"{base_source} / {redirect_source}"
        else:
            source = base_source
    else:
        source = base_source
    
    return {
        "contest": contest,
        "year": year,
        "variant": variant,
        "problem_num": prob_num,
        "text": problem_text,
        "solution": solution_text or "",
        "answer": answer,
        "aime_answer": aime_answer,
        "difficulty": difficulty,
        "source": source,
        "link": build_problem_link(contest, year, variant, prob_num),
    }


def scrape_contest(contest, start_year, end_year, variants, num_problems, max_workers=10):
    """Scrape all problems for a contest in parallel."""
    
    # First, gather all answer keys (sequential, these are fast)
    print(f"  Fetching answer keys...")
    answer_keys = {}
    for year in range(start_year, end_year + 1):
        for variant in variants:
            key = (year, variant)
            answer_keys[key] = scrape_answer_key(contest, year, variant)
            time.sleep(0.05)
    
    # Build list of all problems to scrape
    tasks = []
    for year in range(start_year, end_year + 1):
        for variant in variants:
            answers = answer_keys.get((year, variant), {})
            for prob_num in range(1, num_problems + 1):
                answer = answers.get(prob_num, "")
                tasks.append((contest, year, variant, prob_num, answer))
    
    print(f"  Scraping {len(tasks)} problems with {max_workers} workers...")
    
    all_problems = []
    completed = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(scrape_single_problem, task): task for task in tasks}
        
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                if result:
                    all_problems.append(result)
                    completed += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"  Error on {task[0]} {task[1]} {task[2]} #{task[3]}: {e}")
                failed += 1
            
            # Progress update every 100
            total_done = completed + failed
            if total_done % 100 == 0:
                print(f"    Progress: {total_done}/{len(tasks)} ({completed} ok, {failed} failed)")
    
    print(f"  Done: {completed} problems scraped, {failed} failed")
    
    # Sort by year, variant, problem_num for consistent ordering
    all_problems.sort(key=lambda p: (p['year'], p['variant'] or '', p['problem_num']))
    
    return all_problems


# ============ BATCH API FOR CLASSIFICATION + REPHRASING ============

CATEGORIES = ["algebra", "counting", "geometry", "number_theory"]

CLASSIFY_PROMPT = """Classify this math competition problem into exactly ONE category, then rephrase it.

Categories:
- algebra: equations, polynomials, functions, inequalities, sequences, series, logarithms, exponents, complex numbers
- counting: combinatorics, probability, permutations, combinations, expected value, counting arrangements
- geometry: triangles, circles, polygons, 3D shapes, coordinate geometry, trigonometry, areas, volumes
- number_theory: divisibility, primes, GCD/LCM, modular arithmetic, digits, bases, Diophantine equations

Problem:
{problem_text}

Solution:
{solution}

Output JSON only:
{{"type": "<category>", "rephrased": "<problem rephrased clearly, keeping mathematical content identical>"}}"""


def create_batch_request(problem, custom_id):
    prompt = CLASSIFY_PROMPT.format(
        problem_text=problem['text'],
        solution=problem.get('solution', 'N/A')[:2000]
    )
    
    return {
        "custom_id": custom_id,
        "params": {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 2048,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]
        }
    }


def submit_batch(problems):
    """Submit batch for classification + rephrasing."""
    requests_list = []
    
    for i, p in enumerate(problems):
        custom_id = f"prob_{i}"
        requests_list.append(create_batch_request(p, custom_id))
    
    print(f"Submitting batch of {len(requests_list)} problems...")
    
    batch = client.messages.batches.create(requests=requests_list)
    
    print(f"✅ Batch ID: {batch.id}")
    print(f"   Status: {batch.processing_status}")
    
    # Save batch info
    with open("maa_batch_info.json", "w") as f:
        json.dump({"batch_id": batch.id}, f)
    
    return batch.id


def poll_batch(batch_id):
    """Poll until batch is complete."""
    print(f"Polling batch {batch_id}...")
    
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        counts = batch.request_counts
        
        total = counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
        print(f"⏳ {status} | {counts.succeeded}/{total} succeeded, {counts.errored} errors")
        
        if status == "ended":
            print("✅ Batch complete!")
            return
        
        time.sleep(30)


def download_and_create_csv(batch_id, problems, output_file="maa_problems.csv"):
    """Download batch results and create final CSV."""
    print(f"Downloading results...")
    
    results = {}
    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        idx = int(custom_id.replace("prob_", ""))
        
        if result.result.type == "succeeded":
            try:
                text = result.result.message.content[0].text.strip()
                # Parse JSON from response
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                
                data = json.loads(text)
                results[idx] = data
            except Exception as e:
                print(f"  ⚠️ {custom_id}: parse error - {e}")
                results[idx] = {"type": "algebra", "rephrased": problems[idx]['text']}
        else:
            print(f"  ❌ {custom_id}: {result.result.type}")
            results[idx] = {"type": "algebra", "rephrased": problems[idx]['text']}
    
    # Build final CSV
    fieldnames = [
        "id", "text", "difficulty", "source", "link", "answer", "aime_answer",
        "year", "title", "answer_type", "solution", "manually_reviewed",
        "bad_problem", "quality", "rewritten_problem", "finalized", "type"
    ]
    
    rows = []
    for i, p in enumerate(problems):
        result = results.get(i, {"type": "algebra", "rephrased": p['text']})
        
        prob_type = result.get('type', 'algebra').lower().replace(" ", "_")
        if prob_type not in CATEGORIES:
            prob_type = "algebra"
        
        rephrased = result.get('rephrased', p['text'])
        
        # Determine answer_type
        if p['contest'] == "AIME":
            answer_type = "positive integer <= 1000"
        else:
            answer_type = "multiple choice"
        
        rows.append({
            "id": "",  # Supabase auto-generates
            "text": p['text'],
            "difficulty": p['difficulty'],
            "source": p['source'],
            "link": p['link'],
            "answer": p['answer'],
            "aime_answer": p['aime_answer'],
            "year": p['year'],
            "title": p['source'],
            "answer_type": answer_type,
            "solution": p['solution'],
            "manually_reviewed": "true",
            "bad_problem": "false",
            "quality": 5,  # MAA problems get quality 5
            "rewritten_problem": rephrased,
            "finalized": "true",
            "type": prob_type
        })
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\n✅ Saved {len(rows)} problems to {output_file}")
    
    # Print type distribution
    type_counts = {}
    for r in rows:
        t = r['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    
    print("\n📊 Type distribution:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"   {t}: {count}")


# ============ MAIN ============

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['scrape', 'submit', 'poll', 'download', 'run'])
    parser.add_argument('--batch-id', type=str)
    parser.add_argument('--aime-only', action='store_true', help='Only scrape AIME')
    parser.add_argument('--contest', type=str, choices=['aime', 'amc8', 'amc10', 'amc12'], 
                        help='Only scrape specific contest')
    
    args = parser.parse_args()
    
    if args.command == 'scrape' or args.command == 'run':
        print("=" * 60)
        print("SCRAPING MAA PROBLEMS")
        print("=" * 60)
        
        all_problems = []
        
        # Determine which contests to scrape
        scrape_aime = args.contest in [None, 'aime'] and not args.contest
        scrape_amc10 = args.contest in [None, 'amc10']
        scrape_amc12 = args.contest in [None, 'amc12']
        scrape_amc8 = args.contest in [None, 'amc8']
        
        if args.aime_only:
            scrape_aime = True
            scrape_amc10 = scrape_amc12 = scrape_amc8 = False
        
        if args.contest:
            scrape_aime = args.contest == 'aime'
            scrape_amc10 = args.contest == 'amc10'
            scrape_amc12 = args.contest == 'amc12'
            scrape_amc8 = args.contest == 'amc8'
        
        if scrape_aime:
            print("\n--- AIME ---")
            all_problems.extend(scrape_contest("AIME", 1983, 1999, [None], 15))
            all_problems.extend(scrape_contest("AIME", 2000, 2024, ["I", "II"], 15))
        
        if scrape_amc10:
            print("\n--- AMC 10 ---")
            all_problems.extend(scrape_contest("AMC_10", 2000, 2001, [None], 25))
            all_problems.extend(scrape_contest("AMC_10", 2002, 2024, ["A", "B"], 25))
        
        if scrape_amc12:
            print("\n--- AMC 12 ---")
            all_problems.extend(scrape_contest("AMC_12", 2000, 2001, [None], 25))
            all_problems.extend(scrape_contest("AMC_12", 2002, 2024, ["A", "B"], 25))
        
        if scrape_amc8:
            print("\n--- AMC 8 ---")
            all_problems.extend(scrape_contest("AMC_8", 1999, 2024, [None], 25))
        
        print(f"\n✅ Scraped {len(all_problems)} total problems")
        
        # Save to CSV
        fieldnames = [
            "contest", "year", "variant", "problem_num", "text", "solution",
            "answer", "aime_answer", "difficulty", "source", "link"
        ]
        with open("maa_problems_scraped.csv", "w", newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_problems)
        print("   Saved to maa_problems_scraped.csv")
        
        if args.command == 'run':
            # Continue to submit
            batch_id = submit_batch(all_problems)
            poll_batch(batch_id)
            download_and_create_csv(batch_id, all_problems)
    
    elif args.command == 'submit':
        with open("maa_problems_scraped.csv", newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            problems = list(reader)
        # Convert types back from strings
        for p in problems:
            p['year'] = int(p['year'])
            p['problem_num'] = int(p['problem_num'])
            p['difficulty'] = float(p['difficulty']) if p['difficulty'] else None
            p['variant'] = p['variant'] if p['variant'] else None
        submit_batch(problems)
    
    elif args.command == 'poll':
        batch_id = args.batch_id
        if not batch_id:
            with open("maa_batch_info.json") as f:
                batch_id = json.load(f)['batch_id']
        poll_batch(batch_id)
    
    elif args.command == 'download':
        batch_id = args.batch_id
        if not batch_id:
            with open("maa_batch_info.json") as f:
                batch_id = json.load(f)['batch_id']
        
        with open("maa_problems_scraped.csv", newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            problems = list(reader)
        # Convert types back from strings
        for p in problems:
            p['year'] = int(p['year'])
            p['problem_num'] = int(p['problem_num'])
            p['difficulty'] = float(p['difficulty']) if p['difficulty'] else None
            p['variant'] = p['variant'] if p['variant'] else None
        
        download_and_create_csv(batch_id, problems)


if __name__ == "__main__":
    main()