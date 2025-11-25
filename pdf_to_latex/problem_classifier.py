#!/usr/bin/env python3
"""
Problem Classifier

Enriches problems_database.csv with:
- problem_type: "proof" or "numerical"
- reasonable_answer: true/false
- aime_suitability: 1-5
- aime_answer: sum of abs values mod 1000 (or null)
- difficulty: 1-10 in increments of 0.5 (baseline + Claude adjustment -1 to +1)

Uses Claude API for classification.

VERSION HISTORY:
v1.6 (2024-11-24): Fixed CSV writing to preserve all input columns (e.g., Supabase id, created_at)
v1.5 (2024-11-24): Fixed --start-from to still load cached results for rows before start index
v1.4 (2024-11-24): Fixed PUMaC case mismatch ('PUMAC' vs 'PUMaC' in difficulty_map)
v1.3 (2024-11-24): Fixed PUMaC Div A/B parsing ('div a'/'div b' vs 'division a'/'division b')
                   Added --start-from argument to resume from specific row
                   Pre-2018 problems get -0.5 difficulty adjustment (min 1.0)
v1.2 (2024-11-24): Changed to adjustment-based difficulty (Claude adjusts baseline by -1 to +1)
                   Added "2-3 line solution" guidance for conservative ratings
v1.1 (2024-11-24): Added comprehensive difficulty_map with all contest baselines
                   Integrated parse_source() for automatic baseline lookup
v1.0 (2024-11-24): Initial version with Claude-based classification
"""

import csv
import json
import time
import re
import os
from pathlib import Path
import anthropic

# ============================================================================
# DIFFICULTY MAPPINGS
# ============================================================================

difficulty_map = {
    'BMT': {
        'Algebra':       [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'Geometry':      [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'NT':            [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'Discrete':      [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'Analysis':      [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'Team':          [1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7],
        'Tiebreaker Algebra': {1:1.5, 2:3, 3:4.5},
        'Tiebreaker Geometry': {1:1.5, 2:3, 3:4.5},
        'Tiebreaker NT': {1:1.5, 2:3, 3:4.5},
        'Tiebreaker Discrete': {1:1.5, 2:3, 3:4.5},
        'Tiebreaker Analysis': {1:1.5, 2:3, 3:4.5},
        'General Tiebreaker': {1:1.5, 2:3, 3:3.5, 4:4, 5:4.5},
        'General': {
            **{i: 1 for i in range(1, 6)},
            **{i: 1.5 for i in range(6, 10)},
            **{i: 2 for i in range(10, 13)},
            **{i: 2.5 for i in range(13, 15)},
            **{i: 3 for i in range(15, 18)},
            **{i: 3.5 for i in range(18, 20)},
            20: 4, 21: 4.5, 22: 5, 23: 5.5, 24: 6, 25: 6.5
        },
        'Guts': {
            1:1.5, 2:2, 3:2.5, 4:2, 5:2.5, 6:3, 7:3, 8:3.5, 9:4, 10:3.5,
            11:4, 12:4.5, 13:4, 14:4.5, 15:5, 16:5, 17:5.5, 18:6, 19:5.5,
            20:6, 21:6.5, 22:6, 23:6.5, 24:7, 25:6.5, 26:7, 27:7.5
        },
    },
    'CMIMC': {
        'Algebra':       [1.5, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6.5, 7],
        'Team_10':       [3, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8],
        'Team_15':       [2, 2, 2.5, 2.5, 3, 3.5, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        'Tiebreakers':   {1:4, 2:4.5, 3:5},
        'Theoretical Computer Science': [2,2.5,3,3.5,4,4.5,5,5.5,6,6.5],
        'Computer Science': [2,2.5,3,3.5,4,4.5,5,5.5,6,6.5],
    },
    'HMMT': {
        'General':       [1,2,3,4,4.5,5,5.5,6,6.5,7],
        'Theme':         [2,3,4,4.5,5,5.5,6,6.5,7,7.5],
        'Guts': {
            1:1.5, 2:2, 3:2.5, 4:2, 5:2.5, 6:3, 7:2.5, 8:3, 9:3.5, 10:3.5,
            11:4, 12:3, 13:3.5, 14:4, 15:3, 16:3.5, 17:4.5, 18:5, 19:5.5,
            20:6, 21:6.5, 22:5.5, 23:6, 24:6.5, 25:6, 26:6.5, 27:7, 28:6.5,
            29:7, 30:7.5, 31:6.5, 32:7, 33:7.5
        },
        'Team':          [2.5, 3, 3.5, 4, 4, 4.5, 5, 5.5, 6, 6.5],
        'General Part 1': [2,3,3.5,4,4,4,4,4.5,4.5,5],
        'General Part 2': [2.5,3,3.5,4,4,4.5,5,5.5,6,6.5],
        'Algebra':       [1,2,3,4,4.5,5,5.5,6,6.5,7],  # Added for Feb/Nov subject rounds
        'Geometry':      [1,2,3,4,4.5,5,5.5,6,6.5,7],
        'Combinatorics': [1,2,3,4,4.5,5,5.5,6,6.5,7],
    },
    'SMT': {
        'Team':          [2,2.5,3,3.5,4,4.5,5,5,5.5,5.5,6,6,6.5,6.5,7],
        'Geometry':      [2.5,3.5,4,4.5,5,5.5,6,6.5,7,7.5],
        'Discrete':      [2.5,3.5,4,4.5,5,5.5,6,6.5,7,7.5],
        'Algebra':       [2.5,3.5,4,4.5,5,5.5,6,6.5,7,7.5],
        'Calculus':      [2.5,3.5,4,4.5,5,5.5,6,6.5,7,7.5],
        'Advanced Topics':[2.5,3.5,4,4.5,5,5.5,6,6.5,7,7.5],
        'Tiebreaker':    {1:2.5, 2:4, 3:5.5},
        'Guts': {
            1:2.5, 2:3, 3:3.5, 4:2.5, 5:3, 6:3.5, 7:2.5, 8:3, 9:3.5, 10:3,
            11:3.5, 12:4, 13:4, 14:4.5, 15:5, 16:4.5, 17:5, 18:5.5, 19:5.5,
            20:6, 21:6.5, 22:6, 23:6.5, 24:7, 25:6.5, 26:7, 27:7.5
        },
        'General': {
            1:1.5, 2:1.5, 3:1.5, 4:1.5, 5:1.5, 6:2, 7:2, 8:2, 9:2, 10:2,
            11:2.5, 12:2.5, 13:2.5, 14:2.5, 15:3, 16:3, 17:3, 18:3,
            19:3.5, 20:3.5, 21:3.5, 22:3.5, 23:4, 24:4, 25:4.5
        },
    },
    'PUMaC': {
        'Division A':    [3,3,3.5,3.5,4,4.5,5,5.5,6,6.5],
        'Division B':    [1,1.5,2,2.5,2.5,3,3.5,3.5,4,4],
        'Team Round':    [3,3.5,4,4,4.5,5,5.5,6,6.5,7]
    }
}

cmimc_team_15_years = set(range(2016, 2024))
pumac_division_a_years = set(range(2017, 2026))

def parse_source(source):
    """Extract contest, subject, problem number, and year from source string."""
    s = source.lower()
    
    # Contest
    contest_match = re.search(r'\b(bmt|cmimc|hmmt|smt|pumac)\b', s)
    if contest_match:
        c = contest_match.group(1).upper()
        # Special case for PUMaC which uses mixed case in difficulty_map
        if c == 'PUMAC':
            contest = 'PUMaC'
        else:
            contest = c
    else:
        contest = None
    
    # Year
    year_match = re.search(r'\b(20\d{2})\b', s)
    year = int(year_match.group(1)) if year_match else None
    
    # Tiebreaker
    is_tiebreaker = bool(re.search(r'\b(tie|tb|tiebreaker)\b', s))
    
    # Subject
    subject = None
    subject_keywords = [
        'algebra', 'geometry', 'nt', 'number theory', 'discrete', 'analysis',
        'combinatorics', 'calculus', 'advanced topics', 'team', 'guts', 'theme',
        'general part 1', 'general part 2', 'general',
        'div a', 'div b', 'division a', 'division b', 'team round', 'theoretical computer science', 'computer science'
    ]
    
    for key in subject_keywords:
        if key in s:
            subject = key.title()
            if key == 'nt' or key == 'number theory':
                subject = 'NT'
            elif key == 'theme':
                subject = 'Theme'
            elif key == 'team round':
                subject = 'Team Round'
            elif key == 'div a' or key == 'division a':
                subject = 'Division A'
            elif key == 'div b' or key == 'division b':
                subject = 'Division B'
            elif key == 'general part 1':
                subject = 'General Part 1'
            elif key == 'general part 2':
                subject = 'General Part 2'
            elif key == 'theoretical computer science':
                subject = 'Theoretical Computer Science'
            elif key == 'computer science':
                subject = 'Computer Science'
            break
    
    # Fallback: letter+number patterns
    if subject is None:
        letter_number_match = re.search(r'\b([A-Z]{1,2})(\d+)\b', source, re.I)
        if letter_number_match:
            letter = letter_number_match.group(1).upper()
            letter_subject_map = {
                'A': 'Algebra', 'B': 'Combinatorics', 'C': 'Geometry',
                'G': 'Geometry', 'N': 'NT', 'D': 'Discrete',
            }
            subject = letter_subject_map.get(letter)
    
    # Problem number
    number = None
    number_match = re.search(r'#([A-Z]?)(\d+)', source, re.I)
    if number_match:
        number = int(number_match.group(2))
    else:
        any_number_match = re.search(r'\b(\d+)\b', source)
        if any_number_match:
            number = int(any_number_match.group(1))
    
    # Normalize subject
    if contest == 'CMIMC':
        if subject in ['Algebra', 'Combinatorics', 'Geometry', 'NT', 'Number Theory']:
            subject = 'Algebra'
        if subject == 'Team Round' or subject == 'Team':
            subject = 'Team_15' if year in cmimc_team_15_years else 'Team_10'
    
    if contest == 'PUMaC':
        # Check for explicit "Div A" or "Div B" in source string
        if 'div a' in s or 'division a' in s:
            subject = 'Division A'
        elif 'div b' in s or 'division b' in s:
            subject = 'Division B'
        # For individual subject rounds without explicit division marker, use year-based logic
        elif subject in ['Algebra', 'Combinatorics', 'Geometry', 'NT', 'Number Theory']:
            subject = 'Division A' if year in pumac_division_a_years else 'Division B'
    
    if contest == 'BMT' and is_tiebreaker:
        tiebreaker_map = {
            'Algebra': 'Tiebreaker Algebra', 'Geometry': 'Tiebreaker Geometry',
            'NT': 'Tiebreaker NT', 'Discrete': 'Tiebreaker Discrete',
            'Analysis': 'Tiebreaker Analysis'
        }
        subject = tiebreaker_map.get(subject, 'General Tiebreaker')
    
    return contest, subject, number, year

def get_baseline_difficulty(source):
    """Get baseline difficulty from source string."""
    contest, subject, number, year = parse_source(source)
    if not all([contest, subject, number]):
        return None
    
    contest_map = difficulty_map.get(contest)
    if not contest_map:
        return None
    
    difficulty_data = contest_map.get(subject)
    if not difficulty_data:
        return None
    
    if isinstance(difficulty_data, dict):
        return difficulty_data.get(number)
    else:  # list
        idx = number - 1
        if 0 <= idx < len(difficulty_data):
            return difficulty_data[idx]
    
    return None

# ============================================================================
# CONFIGURATION
# ============================================================================

INPUT_CSV = Path("problems_database.csv")
OUTPUT_CSV = Path("problems_database_enriched.csv")
STATE_FILE = Path("classifier_state.json")

MODEL = "claude-sonnet-4-20250514"
DELAY_BETWEEN_CALLS = 0.3  # seconds
BATCH_SIZE = 1  # Process one at a time for reliability

# ============================================================================
# PROMPT
# ============================================================================

CLASSIFY_PROMPT = '''Classify this math competition problem.

Problem: {problem}
Answer: {answer}
Source: {source}
Baseline Difficulty: {baseline}

Respond with ONLY a JSON object (no markdown, no explanation):

{{
  "problem_type": "proof" or "numerical",
  "reasonable_answer": true or false,
  "aime_suitability": 1-5,
  "aime_answer": number or null,
  "difficulty_adjustment": -1, -0.5, 0, 0.5, or 1
}}

Classification rules:

**problem_type:**
- "proof" if the problem asks to prove, show, demonstrate, find all, or explain why
- "numerical" if it asks to compute, find, calculate, or determine a specific value

**reasonable_answer:**
- true if answer is a clean integer, simple fraction, or simple expression like "5", "1/2", "2+sqrt(3)"
- false if answer is:
  - A messy decimal like "0.2937156494680644"
  - A complex expression like "2014(1+C(2013,1007))/2^2014"
  - Multiple solutions like "(1,2),(4,2),(5/2,2±3i/2)"
  - Contains variables or is a formula
  - Proof problems (no numerical answer)

**aime_suitability:** (1=worst, 5=best for AIME practice)
- 1: Proof problems, Power Round problems, unsolvable, or answers that aren't a single number
- 2: Non-AIME topics (calculus, analysis, logic, college math, linear algebra)
- 3: Right topics but lower quality, overly computational, or unreasonable answer
- 4: Good AIME candidate - right difficulty and style
- 5: Excellent AIME candidate - perfect difficulty, clean answer, elegant problem

**aime_answer:**
- If reasonable_answer is true: extract ALL integers from the answer (including from fractions and expressions), take absolute values, sum them, then mod 1000
- If reasonable_answer is false: null
- Examples:
  - "120" → 120
  - "1/2" → (1+2) % 1000 = 3
  - "2+sqrt(3)" → (2+3) % 1000 = 5
  - "-15" → 15
  - "3/4 + 5/6" → (3+4+5+6) % 1000 = 18
  - "1001" → 1001 % 1000 = 1

**difficulty_adjustment:** Adjust the baseline difficulty by -1, -0.5, 0, +0.5, or +1
The baseline difficulty is {baseline} (from the competition/round difficulty map).

**Adjustment guidelines:**
- If the solution is 2-3 lines of straightforward algebra/arithmetic → adjust DOWN by -0.5 or -1
- If solution requires only direct formula application → likely 0 or -0.5
- If problem is significantly easier/harder than typical for this round → adjust accordingly
- Default to 0 if unsure
- Be conservative - only adjust ±1 if problem is clearly much easier/harder

Respond with ONLY the JSON object, no other text.'''

# ============================================================================
# CLASSIFIER
# ============================================================================

class ProblemClassifier:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.state = self.load_state()
    
    def load_state(self) -> dict:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
        return {"processed": 0, "results": {}}
    
    def save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))
    
    def classify_problem(self, problem: str, answer: str, source: str) -> dict:
        """Classify a single problem using Claude."""
        # Get baseline difficulty
        baseline_difficulty = get_baseline_difficulty(source)
        baseline_str = f"{baseline_difficulty:.1f}" if baseline_difficulty else "unknown"
        
        prompt = CLASSIFY_PROMPT.format(
            problem=problem[:2000],  # Truncate if too long
            answer=answer[:500],
            source=source,
            baseline=baseline_str
        )
        
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}]
            )
            
            text = response.content[0].text.strip()
            
            # Clean up response - remove markdown code blocks if present
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            text = text.strip()
            
            result = json.loads(text)
            
            # Validate and normalize
            result['problem_type'] = result.get('problem_type', 'numerical')
            result['reasonable_answer'] = bool(result.get('reasonable_answer', False))
            result['aime_suitability'] = max(1, min(5, int(result.get('aime_suitability', 3))))
            result['aime_answer'] = result.get('aime_answer')
            
            # Ensure aime_answer is int or None
            if result['aime_answer'] is not None:
                try:
                    result['aime_answer'] = int(result['aime_answer']) % 1000
                except (ValueError, TypeError):
                    result['aime_answer'] = None
            
            # Get Claude's adjustment
            adjustment = result.get('difficulty_adjustment', 0)
            try:
                adjustment = float(adjustment)
                # Must be in [-1, -0.5, 0, 0.5, 1]
                valid_adjustments = [-1, -0.5, 0, 0.5, 1]
                adjustment = min(valid_adjustments, key=lambda x: abs(x - adjustment))
            except (ValueError, TypeError):
                adjustment = 0
            
            # Calculate final difficulty
            if baseline_difficulty is not None:
                final_difficulty = baseline_difficulty + adjustment
                
                # Year-based adjustment: pre-2018 problems were easier
                # But don't reduce below 1.0
                _, _, _, year = parse_source(source)
                if year and year <= 2017 and final_difficulty > 1.0:
                    final_difficulty -= 0.5
                
                # Clamp to [1, 10]
                final_difficulty = max(1.0, min(10.0, final_difficulty))
            else:
                # No baseline, can't compute difficulty
                final_difficulty = None
            
            result['difficulty'] = final_difficulty
            result['baseline_difficulty'] = baseline_difficulty
            result['difficulty_adjustment'] = adjustment
            
            return result
            
        except json.JSONDecodeError as e:
            print(f" [JSON error: {e}]", end="")
            baseline = get_baseline_difficulty(source)
            return {
                'problem_type': 'numerical',
                'reasonable_answer': False,
                'aime_suitability': 3,
                'aime_answer': None,
                'difficulty': baseline,
                'baseline_difficulty': baseline,
                'difficulty_adjustment': 0
            }
        except Exception as e:
            print(f" [API error: {e}]", end="")
            baseline = get_baseline_difficulty(source)
            return {
                'problem_type': 'numerical',
                'reasonable_answer': False,
                'aime_suitability': 3,
                'aime_answer': None,
                'difficulty': baseline,
                'baseline_difficulty': baseline,
                'difficulty_adjustment': 0
            }
    
    def process_csv(self, input_path: Path, output_path: Path, resume: bool = True, start_from: int = None):
        """Process the CSV file, adding classification columns.
        
        Args:
            input_path: Input CSV file path
            output_path: Output CSV file path
            resume: Whether to resume from previous state
            start_from: If provided, force processing to start from this row index (0-based),
                       but still use cached results for rows before this point
        """
        
        # Read input
        with open(input_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        print(f"Loaded {len(rows)} problems from {input_path}")
        
        # Determine starting point
        if start_from is not None:
            start_idx = start_from
            print(f"Starting from row {start_idx} (--start-from override)")
        else:
            start_idx = self.state['processed'] if resume else 0
            if start_idx > 0:
                print(f"Resuming from problem {start_idx}")
        
        # Process each row
        for i, row in enumerate(rows):
            if i < start_idx:
                # Before start_idx - use cached result if available
                key = f"{i}"
                if key in self.state['results']:
                    result = self.state['results'][key]
                    row['problem_type'] = result['problem_type']
                    row['reasonable_answer'] = result['reasonable_answer']
                    row['aime_suitability'] = result['aime_suitability']
                    row['aime_answer'] = result['aime_answer'] if result['aime_answer'] is not None else ''
                    row['difficulty'] = result.get('difficulty', 5.0)
                continue
            
            source = row.get('source', '')
            print(f"[{i+1}/{len(rows)}] {source[:50]}", end="", flush=True)
            
            result = self.classify_problem(
                row.get('problem', ''),
                row.get('answer', ''),
                source
            )
            
            # Add to row
            row['problem_type'] = result['problem_type']
            row['reasonable_answer'] = result['reasonable_answer']
            row['aime_suitability'] = result['aime_suitability']
            row['aime_answer'] = result['aime_answer'] if result['aime_answer'] is not None else ''
            row['difficulty'] = result['difficulty']
            
            # Cache result
            self.state['results'][str(i)] = result
            self.state['processed'] = i + 1
            
            # Print summary
            ptype = "P" if result['problem_type'] == 'proof' else "N"
            reasonable = "✓" if result['reasonable_answer'] else "✗"
            stars = "★" * result['aime_suitability']
            aime = result['aime_answer'] if result['aime_answer'] is not None else "-"
            diff = result['difficulty']
            baseline = result.get('baseline_difficulty')
            adj = result.get('difficulty_adjustment', 0)
            
            if diff is not None and baseline is not None:
                adj_str = f"{adj:+.1f}" if adj != 0 else "±0"
                print(f" → {ptype} {reasonable} {stars} [{aime}] D:{diff:.1f} (B:{baseline:.1f}{adj_str})")
            elif diff is not None:
                print(f" → {ptype} {reasonable} {stars} [{aime}] D:{diff:.1f} (no baseline)")
            else:
                print(f" → {ptype} {reasonable} {stars} [{aime}] D:? (no baseline)")
            
            # Save state periodically
            if (i + 1) % 10 == 0:
                self.save_state()
                # Also write partial output
                self._write_csv(rows[:i+1], output_path)
            
            time.sleep(DELAY_BETWEEN_CALLS)
        
        # Final save
        self.save_state()
        self._write_csv(rows, output_path)
        
        # Summary stats
        self._print_summary(rows)
    
    def _write_csv(self, rows: list, output_path: Path):
        """Write rows to CSV."""
        if not rows:
            return
        
        # Get all fieldnames from first row (includes input columns + new classification columns)
        fieldnames = list(rows[0].keys())
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)
    
    def _print_summary(self, rows: list):
        """Print classification summary."""
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        total = len(rows)
        proofs = sum(1 for r in rows if r.get('problem_type') == 'proof')
        reasonable = sum(1 for r in rows if r.get('reasonable_answer') == True)
        
        print(f"Total problems: {total}")
        print(f"Proof problems: {proofs} ({100*proofs/total:.1f}%)")
        print(f"Numerical problems: {total - proofs} ({100*(total-proofs)/total:.1f}%)")
        print(f"Reasonable answers: {reasonable} ({100*reasonable/total:.1f}%)")
        
        print("\nAIME Suitability distribution:")
        for star in range(1, 6):
            count = sum(1 for r in rows if r.get('aime_suitability') == star)
            bar = "█" * (count // 20)
            print(f"  {star}★: {count:4d} ({100*count/total:5.1f}%) {bar}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Classify math problems for AIME suitability")
    parser.add_argument("--input", "-i", default=str(INPUT_CSV), help="Input CSV file")
    parser.add_argument("--output", "-o", default=str(OUTPUT_CSV), help="Output CSV file")
    parser.add_argument("--reset", action="store_true", help="Start fresh, ignore previous progress")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    parser.add_argument("--start-from", type=int, default=None, help="Start from this row index (0-based)")
    args = parser.parse_args()
    
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        return
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return
    
    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("State reset.")
    
    if args.dry_run:
        with open(input_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        print(f"Would process {len(rows)} problems")
        print(f"Output: {output_path}")
        return
    
    classifier = ProblemClassifier(api_key)
    classifier.process_csv(input_path, output_path, resume=not args.reset, start_from=args.start_from)
    
    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    main()