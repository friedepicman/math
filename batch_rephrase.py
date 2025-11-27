#!/usr/bin/env python3
"""
Batch rephrase + quality rate + compute AIME answers using Claude Batch API
Uses triple verification: values + aime_answer + reconstructed answer
"""

import os
import json
import time
import re
import math
from fractions import Fraction
from datetime import datetime, timezone
from anthropic import Anthropic
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_KEY')
)

MODEL = "claude-opus-4-5-20251101"

# ============ DIFFICULTY MAPPING ============

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
            29:7, 30:7.5, 31:6.5, 32:7, 33:7.5, 34:7, 35:7.5, 36:8
        },
        'Team':          [2.5, 3, 3.5, 4, 4, 4.5, 5, 5.5, 6, 6.5],
        'General Part 1': [2,3,3.5,4,4,4,4,4.5,4.5,5],
        'General Part 2': [2.5,3,3.5,4,4,4.5,5,5.5,6,6.5],
        'Algebra':       [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        'Geometry':      [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        'Combinatorics': [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
        'Number Theory': [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5],
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
    'PUMAC': {
        'Division A':    [3,3,3.5,3.5,4,4.5,5,5.5,6,6.5],
        'Division B':    [1,1.5,2,2.5,2.5,3,3.5,3.5,4,4],
        'Team Round':    [3,3.5,4,4,4.5,5,5.5,6,6.5,7]
    },
    'PURPLE COMET': {
        'High School': {
            **{i: 1.5 for i in range(1, 4)},
            **{i: 2 for i in range(4, 7)},
            **{i: 2.5 for i in range(7, 11)},
            **{i: 3 for i in range(11, 15)},
            **{i: 3.5 for i in range(15, 19)},
            **{i: 4 for i in range(19, 23)},
            **{i: 4.5 for i in range(23, 26)},
            **{i: 5 for i in range(26, 29)},
            29: 5.5,
            30: 6
        },
        'Middle School': {
            **{i: 1 for i in range(1, 4)},
            **{i: 1.5 for i in range(4, 7)},
            **{i: 2 for i in range(7, 11)},
            **{i: 2.5 for i in range(11, 15)},
            **{i: 3 for i in range(15, 18)},
            18: 3.5,
            19: 4,
            20: 4.5
        }
    }
}

cmimc_team_15_years = set(range(2016, 2024))
pumac_division_a_years = set(range(2017, 2026))


def parse_source(source):
    s = source.lower()

    if 'purple comet' in s or 'purplecomet' in s:
        contest = 'PURPLE COMET'
    else:
        contest_match = re.search(r'\b(bmt|cmimc|hmmt|smt|pumac)\b', s)
        contest = contest_match.group(1).upper() if contest_match else None

    year_match = re.search(r'\b(20\d{2})\b', s)
    year = int(year_match.group(1)) if year_match else None

    is_tiebreaker = bool(re.search(r'\b(tie|tb|tiebreaker)\b', s))

    subject = None

    subject_keywords = [
        'algebra', 'geometry', 'nt', 'number theory', 'discrete', 'analysis',
        'combinatorics', 'calculus', 'advanced topics', 'team', 'guts',
        'general part 1', 'general part 2', 'general',
        'division a', 'division b', 'team round', 'theoretical computer science', 
        'computer science', 'high school', 'middle school', 'theme'
    ]

    for key in subject_keywords:
        if key in s:
            subject = key.title()
            if key == 'nt' or key == 'number theory':
                subject = 'Number Theory'
            elif key == 'team round':
                subject = 'Team Round'
            elif key == 'division a':
                subject = 'Division A'
            elif key == 'division b':
                subject = 'Division B'
            elif key == 'general part 1':
                subject = 'General Part 1'
            elif key == 'general part 2':
                subject = 'General Part 2'
            elif key == 'theoretical computer science':
                subject = 'Theoretical Computer Science'
            elif key == 'computer science':
                subject = 'Computer Science'
            elif key == 'high school':
                subject = 'High School'
            elif key == 'middle school':
                subject = 'Middle School'
            break

    number = None
    number_match = re.search(r'#([A-Z]?)(\d+)', source, re.I)
    if number_match:
        number = int(number_match.group(2))
    else:
        p_match = re.search(r'\bP(\d+)\b', source, re.I)
        if p_match:
            number = int(p_match.group(1))
        else:
            all_nums = re.findall(r'\b(\d+)\b', source)
            if all_nums:
                for n in reversed(all_nums):
                    if not (2000 <= int(n) <= 2030):
                        number = int(n)
                        break

    if contest == 'CMIMC':
        if subject in ['Algebra', 'Combinatorics', 'Geometry', 'Number Theory']:
            subject = 'Algebra'
        if subject in ['Team Round', 'Team']:
            subject = 'Team_15' if year in cmimc_team_15_years else 'Team_10'

    if contest == 'PUMAC':
        if subject in ['Algebra', 'Combinatorics', 'Geometry', 'Number Theory']:
            subject = 'Division A' if year in pumac_division_a_years else 'Division B'

    if contest == 'BMT' and is_tiebreaker:
        tiebreaker_map = {
            'Algebra': 'Tiebreaker Algebra',
            'Geometry': 'Tiebreaker Geometry',
            'Nt': 'Tiebreaker NT',
            'Number Theory': 'Tiebreaker NT',
            'Discrete': 'Tiebreaker Discrete',
            'Analysis': 'Tiebreaker Analysis'
        }
        subject = tiebreaker_map.get(subject, 'General Tiebreaker')

    if contest == 'HMMT':
        if subject == 'Nt':
            subject = 'Number Theory'

    return contest, subject, number, year


def get_difficulty(source):
    contest, subject, number, year = parse_source(source)
    if contest is None or subject is None or number is None:
        return None

    contest_map = difficulty_map.get(contest)
    if contest_map is None:
        return None

    difficulty_data = contest_map.get(subject)
    if difficulty_data is None:
        return None

    if isinstance(difficulty_data, dict):
        return difficulty_data.get(number)
    elif isinstance(difficulty_data, list):
        idx = number - 1
        if 0 <= idx < len(difficulty_data):
            return difficulty_data[idx]

    return None


def compute_aime_answer(template, values):
    """Compute AIME answer from template and values."""
    try:
        if template == "integer":
            n = int(values["n"])
            return abs(n) % 1000
        
        elif template == "fraction":
            a, b = int(values["a"]), int(values["b"])
            return (a + b) % 1000
        
        elif template == "sqrt_b":
            b = int(values["b"])
            return b % 1000
        
        elif template == "a_sqrt_b":
            a, b = int(values["a"]), int(values["b"])
            return (a + b) % 1000
        
        elif template == "a_plus_sqrt_b":
            a, b = int(values["a"]), int(values["b"])
            return (a + b) % 1000
        
        elif template == "a_plus_b_sqrt_c":
            a, b, c = int(values["a"]), int(values["b"]), int(values["c"])
            return (a + b + c) % 1000
        
        elif template == "a_sqrt_b_over_c":
            a, b, c = int(values["a"]), int(values["b"]), int(values["c"])
            return (a + b + c) % 1000
        
        elif template == "a_pi":
            a = int(values["a"])
            return a % 1000
        
        elif template == "a_pi_over_b":
            a, b = int(values["a"]), int(values["b"])
            return (a + b) % 1000
        
        else:
            raise ValueError(f"Unknown template: {template}")
    
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid values for template {template}: {values} - {e}")


def reconstruct_answer(template, values):
    """Reconstruct the answer string from template and values."""
    try:
        if template == "integer":
            return str(int(values["n"]))
        
        elif template == "fraction":
            a, b = int(values["a"]), int(values["b"])
            return f"{a}/{b}"
        
        elif template == "sqrt_b":
            b = int(values["b"])
            return f"√{b}"
        
        elif template == "a_sqrt_b":
            a, b = int(values["a"]), int(values["b"])
            return f"{a}√{b}"
        
        elif template == "a_plus_sqrt_b":
            a, b = int(values["a"]), int(values["b"])
            return f"{a}+√{b}"
        
        elif template == "a_plus_b_sqrt_c":
            a, b, c = int(values["a"]), int(values["b"]), int(values["c"])
            return f"{a}+{b}√{c}"
        
        elif template == "a_sqrt_b_over_c":
            a, b, c = int(values["a"]), int(values["b"]), int(values["c"])
            return f"{a}√{b}/{c}"
        
        elif template == "a_pi":
            a = int(values["a"])
            return f"{a}π"
        
        elif template == "a_pi_over_b":
            a, b = int(values["a"]), int(values["b"])
            return f"{a}π/{b}"
        
        else:
            return None
    except:
        return None


def normalize_answer(s):
    """Normalize answer string for comparison."""
    if s is None:
        return None
    s = str(s).strip()
    # Remove LaTeX
    s = s.replace('\\pi', 'π').replace('\\sqrt', '√')
    s = re.sub(r'\\frac\{(\d+)\}\{(\d+)\}', r'\1/\2', s)
    s = re.sub(r'sqrt\{(\d+)\}', r'√\1', s)
    s = re.sub(r'\{|\}', '', s)
    # Remove spaces
    s = s.replace(' ', '')
    # Normalize symbols
    s = s.replace('*', '').replace('\\', '')
    return s.lower()


def answers_match(original, reconstructed, template, values):
    """Check if original answer matches reconstructed answer."""
    orig_norm = normalize_answer(original)
    recon_norm = normalize_answer(reconstructed)
    
    if orig_norm is None or recon_norm is None:
        return False
    
    # Direct string match
    if orig_norm == recon_norm:
        return True
    
    # Try numeric comparison for fractions/decimals
    try:
        if template == "fraction":
            a, b = int(values["a"]), int(values["b"])
            expected_value = a / b
            
            # Try parsing original as decimal
            orig_clean = re.sub(r'[^\d.\-/]', '', original)
            if '/' in orig_clean:
                num, den = orig_clean.split('/')
                orig_value = float(num) / float(den)
            else:
                orig_value = float(orig_clean)
            
            if abs(expected_value - orig_value) < 0.0001:
                return True
        
        elif template == "integer":
            n = int(values["n"])
            orig_clean = re.sub(r'[^\d.\-]', '', original)
            orig_value = float(orig_clean)
            if abs(n - orig_value) < 0.0001:
                return True
        
        elif template == "a_pi":
            a = int(values["a"])
            # Check if original is like "504π" or "504\pi"
            match = re.search(r'(\d+)\s*\\?π|(\d+)\s*\\?pi', original, re.I)
            if match:
                orig_a = int(match.group(1) or match.group(2))
                if orig_a == a:
                    return True
        
        elif template == "a_pi_over_b":
            a, b = int(values["a"]), int(values["b"])
            # Check patterns like "504π/1" or "5π/3"
            match = re.search(r'(\d+)\s*\\?π?\s*/\s*(\d+)', original, re.I)
            if match:
                orig_a, orig_b = int(match.group(1)), int(match.group(2))
                if orig_a == a and orig_b == b:
                    return True
            # Also check just "aπ" which would be a_pi template
            match = re.search(r'^(\d+)\s*\\?π$', original.strip(), re.I)
            if match and b == 1:
                orig_a = int(match.group(1))
                if orig_a == a:
                    return True
    
    except:
        pass
    
    return False


# ============ SYSTEM PROMPT ============

SYSTEM_PROMPT = """You are an expert at evaluating and rephrasing mathematics competition problems into AIME format.

You will do THREE tasks and output ONLY a JSON object.

═══════════════════════════════════════════════════════════════════════
TASK 1: QUALITY RATING (1-5)
═══════════════════════════════════════════════════════════════════════

5 = Outstanding. TOP 20% only. Exceptionally elegant, clever, memorable.
4 = Good. DEFAULT for well-written problems. Clear, tests MAA concepts.
3 = Marginal. Unusual concept or unclear wording.
2 = Not MAA-relevant but educational. Calculus, physics, college math.
1 = Problematic. Unsolvable, ambiguous, garbled.

Default to 4. Only give 5 to truly exceptional problems.
If very few possible answers (≤20), rate 3 or lower.

═══════════════════════════════════════════════════════════════════════
TASK 2: CHECK IF ANSWER FITS STANDARD TEMPLATE
═══════════════════════════════════════════════════════════════════════

TEMPLATE NAME        | ANSWER FORM       | VALUES TO EXTRACT              | AIME ANSWER
---------------------|-------------------|--------------------------------|-------------
"integer"            | 42, -7, 1500      | {"n": <integer>}               | |n| mod 1000
"fraction"           | a/b OR decimal    | {"a": <num>, "b": <denom>}     | (a+b) mod 1000
"sqrt_b"             | √b like √13       | {"b": <radicand>}              | b mod 1000
"a_sqrt_b"           | a√b like 6√3      | {"a": <coef>, "b": <radicand>} | (a+b) mod 1000
"a_plus_sqrt_b"      | a+√b like 2+√3    | {"a": <int>, "b": <radicand>}  | (a+b) mod 1000
"a_plus_b_sqrt_c"    | a+b√c like 3+2√5  | {"a", "b", "c"}                | (a+b+c) mod 1000
"a_sqrt_b_over_c"    | a√b/c like 5√3/12 | {"a", "b", "c"}                | (a+b+c) mod 1000
"a_pi"               | aπ like 504π      | {"a": <coefficient>}           | a mod 1000
"a_pi_over_b"        | aπ/b like 5π/3    | {"a": <num>, "b": <denom>}     | (a+b) mod 1000

IMPORTANT FOR DECIMALS: Convert to fraction first!
- 20.5 = 41/2 → template: "fraction", values: {"a": 41, "b": 2}
- 0.25 = 1/4 → template: "fraction", values: {"a": 1, "b": 4}

IMPORTANT FOR PI WITHOUT DENOMINATOR:
- 504π → template: "a_pi", values: {"a": 504}
- NOT a_pi_over_b with b=1

NON-STANDARD FORMS (SKIP):
- Subtraction: √a - b√c, a - b√c, 1 - a/π
- Sum of radicals: √a + √b
- Nested radicals: √(a + √b)
- Variables, formulas, multiple values

═══════════════════════════════════════════════════════════════════════
TASK 3: EXTRACT, RECONSTRUCT, AND COMPUTE
═══════════════════════════════════════════════════════════════════════

If answer fits a template:
1. Extract numerical values
2. Reconstruct the answer from your values (to verify extraction)
3. Compute AIME answer using the formula

REPHRASING: If problem already asks for integer 0-999, keep it unchanged.

═══════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════

If SKIPPING:
{"quality": <1-5>, "quality_reason": "<reason>", "skip": true, "skip_reason": "<why>"}

If PROCESSING:
{
  "quality": <1-5>,
  "quality_reason": "<reason>",
  "skip": false,
  "template": "<template_name>",
  "values": {<extracted values>},
  "reconstructed": "<answer rebuilt from values>",
  "aime_answer": <integer 0-999>,
  "rephrased": "<problem text>"
}

═══════════════════════════════════════════════════════════════════════
EXAMPLES
═══════════════════════════════════════════════════════════════════════

Original: 2 + 3√2
→ template: "a_plus_b_sqrt_c"
→ values: {"a": 2, "b": 3, "c": 2}
→ reconstructed: "2+3√2"
→ aime_answer: 7

Original: 20.5
→ Convert: 20.5 = 41/2
→ template: "fraction"
→ values: {"a": 41, "b": 2}
→ reconstructed: "41/2"
→ aime_answer: 43

Original: 504π
→ template: "a_pi"
→ values: {"a": 504}
→ reconstructed: "504π"
→ aime_answer: 504

Original: 5π/3
→ template: "a_pi_over_b"
→ values: {"a": 5, "b": 3}
→ reconstructed: "5π/3"
→ aime_answer: 8

Original: √13
→ template: "sqrt_b"
→ values: {"b": 13}
→ reconstructed: "√13"
→ aime_answer: 13

START WITH { AND END WITH }. No other text."""


def load_problems(start_id=9617):
    """Load problems that have answer."""
    print(f"Loading problems starting from ID {start_id}...")
    
    all_problems = []
    from_index = 0
    chunk_size = 1000
    
    while True:
        query = supabase.table('problems') \
            .select('id, text, answer, aime_answer, source, difficulty, type, quality') \
            .gte('id', start_id) \
            .not_.is_('answer', 'null') \
            .order('id') \
            .range(from_index, from_index + chunk_size - 1)
        
        result = query.execute()
        
        if not result.data:
            break
        
        all_problems.extend(result.data)
        from_index += chunk_size
        print(f"  Loaded {len(all_problems)} problems...")
        
        if len(result.data) < chunk_size:
            break
    
    problems = [p for p in all_problems if p.get('text') and p['text'].strip()]
    print(f"Total problems with text and answer: {len(problems)}\n")
    
    return problems


def create_batch_request(problem, custom_id):
    """Create a single batch request."""
    
    answer = problem.get('answer', '')
    
    user_prompt = f"""Problem ID: {problem['id']}
Source: {problem.get('source', 'Unknown')}
Original Answer: {answer}

Original Problem:
{problem['text']}

═══════════════════════════════════════════════════════════════════════
CHECKLIST
═══════════════════════════════════════════════════════════════════════

1. Quality: 1-5 (default 4, only top 20% get 5)

2. Does answer fit a template? If not, skip.

3. If processing:
   - template: which one?
   - values: extract the numbers
   - reconstructed: rebuild answer from values (e.g., "41/2" for fraction with a=41,b=2)
   - aime_answer: compute using formula
   - rephrased: AIME format (or unchanged if already asks for integer)

REMEMBER:
- Decimals → convert to fraction (20.5 = 41/2, so a=41, b=2, answer=43)
- aπ without denominator → use "a_pi" template, answer = a
- aπ/b with denominator → use "a_pi_over_b" template, answer = a+b

Output JSON only."""

    return {
        "custom_id": custom_id,
        "params": {
            "model": MODEL,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}]
        }
    }


def submit_batch(problems):
    """Submit batch to Anthropic API."""
    requests = []
    
    for p in problems:
        custom_id = f"prob_{p['id']}"
        requests.append(create_batch_request(p, custom_id))
    
    print(f"Submitting batch of {len(requests)} problems...")
    
    batch = client.messages.batches.create(requests=requests)
    
    print(f"✅ Batch ID: {batch.id}")
    print(f"   Status: {batch.processing_status}")
    
    return batch.id


def poll_batch(batch_id):
    """Poll until batch is complete."""
    print(f"\nPolling batch {batch_id}...")
    
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


def download_and_apply(batch_id, problems):
    """Download results and apply to Supabase."""
    print(f"\nDownloading results and writing to Supabase...")
    
    problems_by_id = {p['id']: p for p in problems}
    
    success = 0
    errors = 0
    skipped_nonstandard = 0
    skipped_mismatch = 0
    skipped_reconstruction = 0
    quality_updated = 0
    quality_skipped = 0
    difficulty_updated = 0
    difficulty_skipped = 0
    rephrases_updated = 0
    aime_answers_updated = 0
    manually_reviewed_true = 0
    manually_reviewed_false = 0
    quality_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    template_dist = {}
    skip_reasons = []
    mismatch_log = []
    reconstruction_log = []
    
    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        problem_id = int(custom_id.replace("prob_", ""))
        
        if result.result.type != "succeeded":
            print(f"  ❌ {custom_id}: {result.result.type}")
            errors += 1
            continue
        
        try:
            response_text = result.result.message.content[0].text.strip()
            
            data = None
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError:
                pass
            
            if not data:
                cleaned = response_text
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0].strip()
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError:
                    pass
            
            if not data:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        pass
            
            if not data:
                print(f"  ❌ {custom_id}: Could not parse JSON")
                errors += 1
                continue
            
            # Check if skipped by Claude
            if data.get('skip', False):
                skipped_nonstandard += 1
                skip_reasons.append((problem_id, data.get('skip_reason', 'Unknown')))
                
                supabase.table('problems').update({
                    'manually_reviewed': False
                }).eq('id', problem_id).execute()
                manually_reviewed_false += 1
                
                success += 1
                continue
            
            quality = data.get('quality')
            rephrased = data.get('rephrased')
            template = data.get('template')
            values = data.get('values')
            claude_answer = data.get('aime_answer')
            claude_reconstructed = data.get('reconstructed')
            
            orig = problems_by_id.get(problem_id, {})
            original_answer = orig.get('answer', '')
            
            # VERIFICATION 1: Our computation matches Claude's
            our_answer = None
            if template and values:
                try:
                    our_answer = compute_aime_answer(template, values)
                except Exception as e:
                    pass
            
            if our_answer is None or claude_answer is None or our_answer != claude_answer:
                skipped_mismatch += 1
                mismatch_log.append((problem_id, original_answer, template, values, claude_answer, our_answer))
                
                supabase.table('problems').update({
                    'manually_reviewed': False
                }).eq('id', problem_id).execute()
                manually_reviewed_false += 1
                
                success += 1
                continue
            
            # VERIFICATION 2: Reconstruction matches original
            our_reconstructed = reconstruct_answer(template, values)
            if not answers_match(original_answer, our_reconstructed, template, values):
                skipped_reconstruction += 1
                reconstruction_log.append((problem_id, original_answer, template, values, claude_reconstructed, our_reconstructed))
                
                supabase.table('problems').update({
                    'manually_reviewed': False
                }).eq('id', problem_id).execute()
                manually_reviewed_false += 1
                
                success += 1
                continue
            
            # All verifications passed!
            aime_answer = our_answer
            
            if template:
                template_dist[template] = template_dist.get(template, 0) + 1
            
            existing_quality = orig.get('quality')
            existing_difficulty = orig.get('difficulty')
            source = orig.get('source', '')
            
            update_data = {}
            
            if quality and 1 <= quality <= 5:
                if existing_quality is not None and existing_quality > 0:
                    quality_skipped += 1
                else:
                    update_data['quality'] = quality
                    quality_updated += 1
                    quality_dist[quality] += 1
            
            final_difficulty = existing_difficulty
            if existing_difficulty is None or existing_difficulty == 0:
                computed_diff = get_difficulty(source)
                if computed_diff is not None:
                    update_data['difficulty'] = computed_diff
                    final_difficulty = computed_diff
                    difficulty_updated += 1
                else:
                    difficulty_skipped += 1
            else:
                difficulty_skipped += 1
            
            final_rephrased = None
            if rephrased and rephrased.strip():
                update_data['rewritten_problem'] = rephrased
                final_rephrased = rephrased
                rephrases_updated += 1
            
            final_aime_answer = aime_answer
            update_data['aime_answer'] = aime_answer
            aime_answers_updated += 1
            
            has_answer = orig.get('answer') is not None
            has_aime_answer = final_aime_answer is not None
            has_difficulty = final_difficulty is not None and final_difficulty > 0
            has_rephrase = final_rephrased is not None and final_rephrased.strip()
            
            if has_answer and has_aime_answer and has_difficulty and has_rephrase:
                update_data['manually_reviewed'] = True
                manually_reviewed_true += 1
            else:
                update_data['manually_reviewed'] = False
                manually_reviewed_false += 1
            
            if update_data:
                supabase.table('problems').update(update_data).eq('id', problem_id).execute()
            
            success += 1
            
            if success % 100 == 0:
                print(f"  ✅ Processed {success}...")
        
        except Exception as e:
            print(f"  ❌ {custom_id}: {e}")
            errors += 1
    
    total_skipped = skipped_nonstandard + skipped_mismatch + skipped_reconstruction
    
    print(f"\n{'='*60}")
    print(f"DONE - Wrote to Supabase")
    print(f"{'='*60}")
    print(f"✅ Success: {success}")
    print(f"❌ Errors: {errors}")
    print(f"\n⏭️  Skipped ({total_skipped} total):")
    print(f"   Non-standard answer: {skipped_nonstandard}")
    print(f"   AIME answer mismatch: {skipped_mismatch}")
    print(f"   Reconstruction mismatch: {skipped_reconstruction}")
    print(f"\n📝 Rephrases updated: {rephrases_updated}")
    print(f"🔢 AIME answers updated (triple verified): {aime_answers_updated}")
    print(f"\n✅ Manually reviewed:")
    print(f"   Set to TRUE:  {manually_reviewed_true}")
    print(f"   Set to FALSE: {manually_reviewed_false}")
    print(f"\n📊 Quality ratings:")
    print(f"   Updated: {quality_updated}")
    print(f"   Skipped (already rated): {quality_skipped}")
    print(f"\n📏 Difficulty ratings:")
    print(f"   Updated: {difficulty_updated}")
    print(f"   Skipped (already set or no mapping): {difficulty_skipped}")
    if quality_updated > 0:
        print(f"\n📊 New quality distribution:")
        for q in range(5, 0, -1):
            bar = "█" * (quality_dist[q] // 5) if quality_dist[q] > 0 else ""
            print(f"   {q}★: {quality_dist[q]:4d} {bar}")
    if template_dist:
        print(f"\n📐 Template distribution (verified):")
        for t, count in sorted(template_dist.items(), key=lambda x: -x[1]):
            print(f"   {t}: {count}")
    if skip_reasons:
        print(f"\n⏭️  Non-standard skips (first 5):")
        for pid, reason in skip_reasons[:5]:
            print(f"   {pid}: {reason[:60]}...")
    if mismatch_log:
        print(f"\n⚠️  AIME answer mismatches (first 5):")
        for pid, orig_ans, tmpl, vals, claude_ans, our_ans in mismatch_log[:5]:
            print(f"   {pid}: '{orig_ans}' → {tmpl} {vals}")
            print(f"        Claude: {claude_ans}, Ours: {our_ans}")
    if reconstruction_log:
        print(f"\n⚠️  Reconstruction mismatches (first 5):")
        for pid, orig_ans, tmpl, vals, claude_recon, our_recon in reconstruction_log[:5]:
            print(f"   {pid}: Original='{orig_ans}'")
            print(f"        Template={tmpl}, Values={vals}")
            print(f"        Claude reconstructed='{claude_recon}', Ours='{our_recon}'")
    print(f"{'='*60}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['submit', 'poll', 'download', 'run'])
    parser.add_argument('--start-from', type=int, default=9617)
    parser.add_argument('--batch-id', type=str)
    parser.add_argument('--limit', type=int)
    
    args = parser.parse_args()
    
    if args.command in ['submit', 'run']:
        problems = load_problems(args.start_from)
        
        if args.limit:
            problems = problems[:args.limit]
            print(f"Limited to {len(problems)} problems\n")
        
        if not problems:
            print("No problems to process!")
            return
        
        with open('batch_problems.json', 'w') as f:
            json.dump(problems, f)
        
        batch_id = submit_batch(problems)
        
        with open('batch_info.json', 'w') as f:
            json.dump({'batch_id': batch_id}, f)
        
        if args.command == 'run':
            poll_batch(batch_id)
            download_and_apply(batch_id, problems)
    
    elif args.command == 'poll':
        batch_id = args.batch_id or json.load(open('batch_info.json'))['batch_id']
        poll_batch(batch_id)
    
    elif args.command == 'download':
        batch_id = args.batch_id or json.load(open('batch_info.json'))['batch_id']
        problems = json.load(open('batch_problems.json'))
        download_and_apply(batch_id, problems)


if __name__ == '__main__':
    main()