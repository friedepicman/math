import anthropic
import base64
import json
import csv
from pathlib import Path

client = anthropic.Anthropic()

# ============ CONFIG ============

CSV_PATH = "most_recent_data/problems_with_types.csv"
PDF_PATH = "/Users/jasonyuan/Documents/git/math/hmmt_pdfs/HMMT_November_2014_General_Solutions.pdf"
OUTPUT_PATH = "hmmt_2014_general_processed.json"
COMPETITION_FILTER = "HMMT November 2014 General"

# ============ STEP 1: LOAD PROBLEMS FROM CSV ============

def load_problems_from_csv(csv_path, competition_filter):
    """Load problems matching a competition filter."""
    problems = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            source = row.get('source', '') or row.get('title', '') or ''
            if competition_filter.lower() in source.lower():
                problems.append(row)
    
    print(f"Found {len(problems)} problems matching '{competition_filter}'")
    return problems


# ============ STEP 2: EXTRACT ANSWERS FROM PDF ============

def extract_answers_from_pdf(pdf_path):
    """Use Claude vision to extract all answers from a solutions PDF."""
    
    with open(pdf_path, 'rb') as f:
        pdf_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    print(f"Extracting answers from {pdf_path}...")
    
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_data
                    }
                },
                {
                    "type": "text",
                    "text": """Extract ALL answers from this math competition solutions PDF.

For each problem, find the final answer. Look for:
- "Answer:" or "Ans:" labels
- Boxed answers
- Final numerical/algebraic results

Return ONLY valid JSON in this exact format:
{
  "1": "answer for problem 1",
  "2": "answer for problem 2",
  ...
}

Use LaTeX notation for math (e.g., "\\frac{1}{2}", "\\sqrt{3}").
If a problem is a proof with no numerical answer, use "PROOF".
Do NOT include any text outside the JSON object."""
                }
            ]
        }]
    )
    
    result_text = response.content[0].text.strip()
    
    # Clean up potential markdown wrapper
    if result_text.startswith("```"):
        result_text = result_text.split("```")[1]
        if result_text.startswith("json"):
            result_text = result_text[4:]
        result_text = result_text.strip()
    
    try:
        answers = json.loads(result_text)
        print(f"Extracted {len(answers)} answers")
        return answers
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Raw response:\n{result_text[:500]}")
        return {}


# ============ STEP 3: COMPUTE AIME ANSWER ============

def compute_aime_answers(problems_with_answers):
    """Convert LaTeX answers to AIME format (0-999)."""
    
    prompt_template = """Convert this math answer to an integer from 0-999 (AIME format).

Answer: {answer}

Rules:
- If it's already an integer 0-999, return it
- If it's a fraction like 3/4, return the numerator + denominator = 7
- If it's a fraction p/q in lowest terms, often return p + q
- If it's sqrt(n), return n
- If it's a + b*sqrt(c) where answer asks for a+b+c, compute that
- If the result would be > 999, return result mod 1000
- If it's "PROOF" or non-numeric, return -1

Return ONLY the integer, nothing else."""

    results = []
    
    for p in problems_with_answers:
        answer = p.get('extracted_answer', '')
        
        if not answer or answer == "PROOF":
            p['aime_answer'] = -1
            results.append(p)
            continue
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=32,
            messages=[{
                "role": "user",
                "content": prompt_template.format(answer=answer)
            }]
        )
        
        try:
            aime_ans = int(response.content[0].text.strip())
            p['aime_answer'] = aime_ans
        except ValueError:
            p['aime_answer'] = -1
        
        results.append(p)
    
    return results


# ============ STEP 4: RATE QUALITY ============

def rate_quality(problems):
    """Rate problem quality 1-5."""
    
    prompt_template = """Rate this math competition problem's quality from 1-5.

Problem:
{problem_text}

Answer: {answer}

Rating criteria:
1 = Poorly written, ambiguous, or trivial
2 = Below average - unclear or uninteresting  
3 = Average - standard competition problem
4 = Good - clear, interesting, well-crafted
5 = Excellent - elegant, memorable, perfect difficulty

Return ONLY a single digit 1-5, nothing else."""

    for p in problems:
        problem_text = p.get('text', '') or p.get('latex', '') or p.get('problem', '')
        answer = p.get('extracted_answer', 'N/A')
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8,
            messages=[{
                "role": "user",
                "content": prompt_template.format(problem_text=problem_text, answer=answer)
            }]
        )
        
        try:
            quality = int(response.content[0].text.strip())
            p['quality'] = max(1, min(5, quality))
        except ValueError:
            p['quality'] = 3
    
    return problems


# ============ STEP 5: REPHRASE TO AIME FORMAT ============

def rephrase_problems(problems):
    """Rephrase problems in AIME format."""
    
    prompt_template = """Rephrase this math problem in AIME style.

Original problem:
{problem_text}

Answer: {answer}
AIME Answer (0-999): {aime_answer}

AIME format rules:
- Clear, concise problem statement
- Answer must be an integer 0-999
- If original answer isn't 0-999, add "find the remainder when X is divided by 1000" or rephrase to get p+q format
- Use proper LaTeX: $...$ for inline math
- No multiple choice

Return ONLY the rephrased problem, no explanation."""

    for p in problems:
        # Skip proofs or low quality
        if p.get('aime_answer', -1) == -1 or p.get('quality', 0) < 3:
            p['rephrased'] = None
            continue
        
        problem_text = p.get('text', '') or p.get('latex', '') or p.get('problem', '')
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": prompt_template.format(
                    problem_text=problem_text,
                    answer=p.get('extracted_answer', ''),
                    aime_answer=p.get('aime_answer', '')
                )
            }]
        )
        
        p['rephrased'] = response.content[0].text.strip()
    
    return problems


# ============ MAIN ============

def main():
    # Step 1: Load problems
    problems = load_problems_from_csv(CSV_PATH, COMPETITION_FILTER)
    
    if not problems:
        print("No problems found! Trying alternate filters...")
        alternates = [
            "HMMT 2014 General",
            "HMMT November 2014",
            "November 2014 General",
            "2014 General"
        ]
        for f in alternates:
            problems = load_problems_from_csv(CSV_PATH, f)
            if problems:
                print(f"Found with filter: '{f}'")
                break
    
    if not problems:
        print("\nStill no problems. Printing HMMT-related sources from CSV:")
        with open(CSV_PATH, 'r') as f:
            reader = csv.DictReader(f)
            sources = set()
            for row in reader:
                src = row.get('source', row.get('title', ''))
                if 'hmmt' in src.lower():
                    sources.add(src)
            for s in sorted(sources)[:20]:
                print(f"  {s}")
        return
    
    # Step 2: Extract answers from PDF
    answers = extract_answers_from_pdf(PDF_PATH)
    
    # Match answers to problems
    for p in problems:
        prob_num = p.get('problem_number') or p.get('num') or p.get('number')
        if prob_num:
            p['extracted_answer'] = answers.get(str(prob_num), '')
    
    print(f"\nMatched answers to {sum(1 for p in problems if p.get('extracted_answer'))} problems")
    
    # Step 3: Compute AIME answers
    print("\nComputing AIME answers...")
    problems = compute_aime_answers(problems)
    
    # Step 4: Rate quality
    print("\nRating quality...")
    problems = rate_quality(problems)
    
    # Step 5: Rephrase
    print("\nRephrasing problems...")
    problems = rephrase_problems(problems)
    
    # Save results
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(problems, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Done! Saved to {OUTPUT_PATH}")
    
    # Print summary
    print("\n📊 Summary:")
    print(f"  Total problems: {len(problems)}")
    print(f"  With answers: {sum(1 for p in problems if p.get('extracted_answer'))}")
    print(f"  With AIME answers: {sum(1 for p in problems if p.get('aime_answer', -1) >= 0)}")
    print(f"  Quality distribution:")
    for q in range(1, 6):
        count = sum(1 for p in problems if p.get('quality') == q)
        print(f"    {q}★: {count}")
    print(f"  Rephrased: {sum(1 for p in problems if p.get('rephrased'))}")


if __name__ == "__main__":
    main()