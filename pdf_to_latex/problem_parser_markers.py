#!/usr/bin/env python3
"""
Problem Parser - Marker-based approach

Claude just identifies problem boundaries and types.
We split the original document ourselves using those markers.

Much faster, cheaper, and more robust than JSON-based extraction.
"""

import os
import re
import csv
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
import anthropic

# ============================================================================
# CONFIGURATION
# ============================================================================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MATHPIX_OUTPUT_DIR = Path("mathpix_output")
OUTPUT_CSV = Path("problems_database.csv")
STATE_FILE = Path("parser_state.json")

MODEL = "claude-sonnet-4-20250514"
DELAY_BETWEEN_CALLS = 0.5

# ============================================================================
# PROMPTS
# ============================================================================

MARKER_PROMPT = '''Look at this math competition document and identify each problem.

For each problem, output ONE line in this format:
NUMBER|TYPE|START|END

Where:
- NUMBER = problem number (integer)
- TYPE = algebra, counting, geometry, number_theory, or misc
- START = first ~20 characters of the problem text
- END = last ~20 characters of the problem text (how the problem ends)

For problems to SKIP (relay problems, problems referencing other answers like "Let $A = H_1$"), output:
SKIP|NUMBER|reason

Example output:
1|algebra|Find the sum of all|solutions to $x^2=5$.
2|counting|There are 100 people|in this room?
3|geometry|Let $ABC$ be a trian|is the area of $ABC$?
SKIP|33|relay problem

Rules:
- One line per problem, no extra text
- Skip any relay/chain problems that reference other answers
- START should be enough to find where the problem begins
- END should be the actual ending of that problem (usually ends with ? or .)

Document:
'''

SOLUTION_MARKER_PROMPT = '''Look at this math competition solutions document and identify each solution.

For each solution, output ONE line in this format:
NUMBER|ANSWER|START|END

Where:
- NUMBER = problem number (integer)  
- ANSWER = the final answer (from \\boxed{} if present), or NONE
- START = first ~20 characters of the solution
- END = last ~20 characters of the solution

For solutions to SKIP, output:
SKIP|NUMBER|reason

Example output:
1|0|The equation has no|so the answer is $0$.
2|29|We count the pairs|giving us $\\boxed{29}$.
SKIP|33|relay problem

Rules:
- One line per solution, no extra text
- Extract answer from \\boxed{} if present
- START/END should identify the solution boundaries

Document:
'''

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Problem:
    competition: str
    year: int
    round: str
    division: str
    problem_number: int
    problem_text: str
    problem_type: str = "misc"
    solution_text: str = ""
    answer: str = ""

@dataclass
class Marker:
    number: int
    type_or_answer: str
    start_snippet: str
    end_snippet: str
    skip: bool = False
    skip_reason: str = ""

# ============================================================================
# MARKER PARSING
# ============================================================================

def parse_markers(response: str) -> List[Marker]:
    """Parse Claude's marker output into Marker objects."""
    markers = []
    for line in response.strip().split('\n'):
        line = line.strip()
        if not line or '|' not in line:
            continue
        
        parts = line.split('|')
        if len(parts) < 2:
            continue
        
        if parts[0] == 'SKIP':
            try:
                num = int(parts[1])
                reason = parts[2] if len(parts) > 2 else ""
                markers.append(Marker(num, "", "", "", skip=True, skip_reason=reason))
            except ValueError:
                continue
        else:
            try:
                num = int(parts[0])
                type_or_ans = parts[1] if len(parts) > 1 else ""
                start_snip = parts[2] if len(parts) > 2 else ""
                end_snip = parts[3] if len(parts) > 3 else ""
                markers.append(Marker(num, type_or_ans, start_snip, end_snip))
            except ValueError:
                continue
    
    return markers

def find_snippet_position(content: str, snippet: str, start_from: int = 0) -> int:
    """Find position of snippet in content, with fuzzy matching."""
    if not snippet:
        return -1
    
    search_content = content[start_from:]
    
    # Direct search first
    pos = search_content.find(snippet)
    if pos != -1:
        return start_from + pos
    
    # Try with normalized whitespace
    normalized_snippet = re.sub(r'\s+', ' ', snippet).strip()
    for i in range(len(search_content) - len(normalized_snippet)):
        window = re.sub(r'\s+', ' ', search_content[i:i+len(normalized_snippet)+20])
        if normalized_snippet in window:
            return start_from + i
    
    # Try first 10 chars only
    if len(snippet) >= 10:
        pos = search_content.find(snippet[:10])
        if pos != -1:
            return start_from + pos
    
    # Try last 10 chars
    if len(snippet) >= 10:
        pos = search_content.find(snippet[-10:])
        if pos != -1:
            return start_from + pos
    
    return -1

def split_by_markers(content: str, markers: List[Marker]) -> Dict[int, str]:
    """Split content into problems using start AND end markers."""
    result = {}
    
    for m in markers:
        if m.skip:
            continue
        
        # Find start position
        start_pos = find_snippet_position(content, m.start_snippet)
        if start_pos == -1:
            continue
        
        # Find end position (search after start)
        if m.end_snippet:
            end_pos = find_snippet_position(content, m.end_snippet, start_pos)
            if end_pos != -1:
                # Include the end snippet itself
                end_pos += len(m.end_snippet)
                # Look for actual end (period, question mark, newline)
                while end_pos < len(content) and content[end_pos] in ' \t':
                    end_pos += 1
            else:
                # Fallback: find next problem number pattern
                next_prob = re.search(r'\n\d+\.\s*(?:\[\d+\])?\s*[A-Z]', content[start_pos + 50:])
                if next_prob:
                    end_pos = start_pos + 50 + next_prob.start()
                else:
                    end_pos = len(content)
        else:
            # No end snippet - find next problem
            next_prob = re.search(r'\n\d+\.\s*(?:\[\d+\])?\s*[A-Z]', content[start_pos + 50:])
            if next_prob:
                end_pos = start_pos + 50 + next_prob.start()
            else:
                end_pos = len(content)
        
        text = content[start_pos:end_pos].strip()
        result[m.number] = text
    
    return result

# ============================================================================
# API CLIENT
# ============================================================================

class MarkerParser:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def get_problem_markers(self, content: str) -> List[Marker]:
        """Get problem markers from Claude."""
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": MARKER_PROMPT + content}]
        )
        return parse_markers(response.content[0].text)
    
    def get_solution_markers(self, content: str) -> List[Marker]:
        """Get solution markers from Claude."""
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": SOLUTION_MARKER_PROMPT + content}]
        )
        return parse_markers(response.content[0].text)

# ============================================================================
# FILE HANDLING
# ============================================================================

@dataclass
class FileEntry:
    competition: str
    year: int
    round: str
    division: str
    doc_type: str
    path: Path

def parse_filename(path: Path) -> Optional[FileEntry]:
    """Parse metadata from filename."""
    name = path.stem
    parts = name.split('_')
    
    doc_type = ""
    if parts and parts[-1].lower() in ['problems', 'solutions']:
        doc_type = parts[-1].lower()
        parts = parts[:-1]
    else:
        return None
    
    year = 0
    year_idx = -1
    for i, p in enumerate(parts):
        if p.isdigit() and len(p) == 4:
            year = int(p)
            year_idx = i
            break
    
    if year == 0:
        return None
    
    competition = ' '.join(parts[:year_idx])
    remaining = parts[year_idx+1:]
    
    division = ""
    if remaining and len(remaining[-1]) == 1 and remaining[-1].isalpha():
        division = remaining[-1]
        remaining = remaining[:-1]
    
    round_name = ' '.join(remaining)
    
    return FileEntry(competition, year, round_name, division, doc_type, path)

def find_files(mathpix_dir: Path, competition_filter: str = None) -> List[dict]:
    """Find and group problem/solution files."""
    files = []
    
    for subdir in mathpix_dir.iterdir():
        if not subdir.is_dir():
            continue
        for md_file in subdir.glob("*.md"):
            entry = parse_filename(md_file)
            if entry:
                files.append(entry)
    
    if competition_filter:
        files = [f for f in files if competition_filter.lower() in f.competition.lower()]
    
    groups = {}
    for f in files:
        key = (f.competition, f.year, f.round, f.division)
        if key not in groups:
            groups[key] = {'problems': None, 'solutions': None, 'meta': f}
        groups[key][f.doc_type] = f.path
    
    return list(groups.values())

# ============================================================================
# MAIN PROCESSING
# ============================================================================

def format_source(p: Problem) -> str:
    parts = [p.competition, str(p.year), p.round]
    if p.division:
        parts.append(f"Div {p.division}")
    parts.append(f"#{p.problem_number}")
    return " ".join(parts)

def process_group(parser: MarkerParser, group: dict) -> List[Problem]:
    """Process a problem/solution group."""
    meta = group['meta']
    problems_path = group.get('problems')
    solutions_path = group.get('solutions')
    
    problems = []
    
    # Process problems file
    if problems_path and problems_path.exists():
        content = problems_path.read_text(encoding='utf-8')
        markers = parser.get_problem_markers(content)
        texts = split_by_markers(content, markers)
        
        for m in markers:
            if m.skip:
                continue
            if m.number in texts:
                problems.append(Problem(
                    competition=meta.competition,
                    year=meta.year,
                    round=meta.round,
                    division=meta.division,
                    problem_number=m.number,
                    problem_text=texts[m.number],
                    problem_type=m.type_or_answer,
                ))
    
    # Process solutions file
    if solutions_path and solutions_path.exists():
        content = solutions_path.read_text(encoding='utf-8')
        markers = parser.get_solution_markers(content)
        texts = split_by_markers(content, markers)
        
        # Match solutions to problems
        sol_map = {}
        ans_map = {}
        for m in markers:
            if m.skip:
                continue
            if m.number in texts:
                sol_map[m.number] = texts[m.number]
                ans_map[m.number] = m.type_or_answer if m.type_or_answer != "NONE" else ""
        
        for p in problems:
            if p.problem_number in sol_map:
                p.solution_text = sol_map[p.problem_number]
                p.answer = ans_map.get(p.problem_number, "")
    
    return problems

def write_csv(problems: List[Problem], output_path: Path, append: bool = False):
    """Write problems to CSV. If append=True, adds to existing file."""
    fieldnames = ['problem', 'answer', 'solution', 'source', 'type']
    
    mode = 'a' if append else 'w'
    write_header = not append or not output_path.exists()
    
    with open(output_path, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for p in problems:
            writer.writerow({
                'problem': p.problem_text,
                'answer': p.answer,
                'solution': p.solution_text,
                'source': format_source(p),
                'type': p.problem_type,
            })

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def load_state(path: Path) -> dict:
    if path.exists():
        return json.load(open(path))
    return {"processed": [], "failed": []}

def save_state(state: dict, path: Path):
    json.dump(state, open(path, 'w'), indent=2)

# ============================================================================
# MAIN
# ============================================================================

def main():
    argparser = argparse.ArgumentParser(description="Marker-based problem parser")
    argparser.add_argument("--dir", default=str(MATHPIX_OUTPUT_DIR))
    argparser.add_argument("--output", "-o", default=str(OUTPUT_CSV))
    argparser.add_argument("--competition", "-c")
    argparser.add_argument("--dry-run", action="store_true")
    argparser.add_argument("--reset", action="store_true")
    args = argparser.parse_args()
    
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not set")
        return
    
    print("Problem Parser (marker-based)")
    print("=" * 60)
    
    state = load_state(STATE_FILE)
    if args.reset:
        state = {"processed": [], "failed": []}
        Path(args.output).unlink(missing_ok=True)
    
    mathpix_dir = Path(args.dir)
    groups = find_files(mathpix_dir, args.competition)
    
    # Filter already processed
    pending = []
    for g in groups:
        m = g['meta']
        key = f"{m.competition}_{m.year}_{m.round}_{m.division}"
        if key not in state['processed']:
            pending.append((key, g))
    
    print(f"Found {len(groups)} groups, {len(pending)} to process")
    
    if args.dry_run:
        for key, g in pending[:20]:
            m = g['meta']
            print(f"  {m.competition} {m.year} {m.round} {m.division}")
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more")
        return
    
    if not pending:
        print("All done!")
        return
    
    parser = MarkerParser(ANTHROPIC_API_KEY)
    total_problems = 0
    output_path = Path(args.output)
    
    # If reset, delete existing output
    if args.reset:
        output_path.unlink(missing_ok=True)
    
    for i, (key, group) in enumerate(pending):
        m = group['meta']
        print(f"[{i+1}/{len(pending)}] {m.competition} {m.year} {m.round} {m.division}", end="", flush=True)
        
        try:
            problems = process_group(parser, group)
            
            # Write immediately after each group
            if problems:
                write_csv(problems, output_path, append=output_path.exists())
                total_problems += len(problems)
            
            state['processed'].append(key)
            
            with_sol = sum(1 for p in problems if p.solution_text)
            with_ans = sum(1 for p in problems if p.answer)
            print(f" → {len(problems)} problems ({with_sol} sols, {with_ans} ans)")
            
        except KeyboardInterrupt:
            print("\nInterrupted, progress saved!")
            break
        except Exception as e:
            print(f" → ERROR: {e}")
            state['failed'].append({'key': key, 'error': str(e)})
        
        save_state(state, STATE_FILE)
        time.sleep(DELAY_BETWEEN_CALLS)
    
    print(f"\n{'='*60}")
    print(f"Total: {total_problems} problems")
    print(f"Output: {args.output}")

if __name__ == "__main__":
    main()