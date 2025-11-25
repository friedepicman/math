import anthropic
import csv
import time
import os
import re

# ============ CONFIG ============
CSV_PATH = "/Users/jasonyuan/Documents/git/math/most_recent_data/problems_rows.csv"
OUTPUT_PATH = "/Users/jasonyuan/Documents/git/math/most_recent_data/problems_with_types.csv"

BATCH_SIZE = 100  # Log every N problems for review
API_BATCH_SIZE = 10  # Problems per API call
# ================================

# Debug: check what key we're getting
api_key = os.environ.get("ANTHROPIC_API_KEY")
print(f"DEBUG: API key from env: {api_key[:20] if api_key else 'NONE'}...{api_key[-5:] if api_key else ''}")
print(f"DEBUG: Key length: {len(api_key) if api_key else 0}")

if not api_key:
    print("ERROR: No ANTHROPIC_API_KEY found in environment!")
    print("Run: export ANTHROPIC_API_KEY='your-key-here'")
    exit(1)

client = anthropic.Anthropic(api_key=api_key)

# Keywords to check in source column
SOURCE_PATTERNS = {
    "geometry": [r'geometry', r'geo\b'],
    "algebra": [r'algebra', r'alg\b'],
    "number_theory": [r'number\s*theory', r'nt\b'],
    "counting": [r'counting', r'combinatorics', r'combo\b', r'probability']
}


def get_type_from_source(source):
    """Try to extract type from the source string."""
    source_lower = source.lower()
    for prob_type, patterns in SOURCE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, source_lower):
                return prob_type
    return None


def classify_problem(problem_text):
    """Use Claude to classify a problem."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[
            {
                "role": "user",
                "content": f"""Classify this math problem as exactly one of: algebra, geometry, number_theory, counting

Problem: {problem_text}

Reply with just one word."""
            }
        ]
    )

    text = response.content[0].text.strip().lower()
    
    if "algebra" in text:
        return "algebra"
    elif "geometry" in text:
        return "geometry"
    elif "number" in text:
        return "number_theory"
    elif "counting" in text:
        return "counting"
    else:
        return "unknown"


def classify_batch(problems_batch):
    """Classify multiple problems in one API call."""
    # Build the prompt with numbered problems
    prompt_lines = ["Classify each math problem as exactly one of: algebra, geometry, number_theory, counting\n"]
    for i, (pid, text) in enumerate(problems_batch):
        prompt_lines.append(f"{i+1}. {text[:500]}")
    prompt_lines.append("\nReply with just the number and type for each, like:\n1. geometry\n2. algebra\netc.")
    
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {"role": "user", "content": "\n".join(prompt_lines)}
        ]
    )
    
    text = response.content[0].text.strip().lower()
    results = {}
    
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Parse "1. geometry" or "1: geometry" or "1 geometry"
        for i, (pid, _) in enumerate(problems_batch):
            prefix = str(i + 1)
            if line.startswith(prefix):
                if "algebra" in line:
                    results[pid] = "algebra"
                elif "geometry" in line:
                    results[pid] = "geometry"
                elif "number" in line:
                    results[pid] = "number_theory"
                elif "counting" in line:
                    results[pid] = "counting"
                break
    
    # Fill in any missing with "unknown"
    for pid, _ in problems_batch:
        if pid not in results:
            results[pid] = "unknown"
    
    return results


def main():
    print("Reading CSV...\n")
    
    # Read all problems
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        problems = list(reader)
    
    print(f"Found {len(problems)} total problems.\n")
    
    # Add 'type' to fieldnames if not present
    if 'type' not in fieldnames:
        fieldnames = list(fieldnames) + ['type']
    
    # Stats
    auto_classified = 0
    api_classified = 0
    
    # First pass: classify from source
    needs_api = []
    for i, problem in enumerate(problems):
        source = problem.get('source', '')
        type_from_source = get_type_from_source(source)
        
        if type_from_source:
            problem['type'] = type_from_source
            auto_classified += 1
        else:
            needs_api.append((i, problem))
    
    print(f"Auto-classified from source: {auto_classified}")
    print(f"Need API classification: {len(needs_api)}\n")
    
    # Second pass: use Claude API for remaining (in batches)
    for batch_start in range(0, len(needs_api), API_BATCH_SIZE):
        batch = needs_api[batch_start:batch_start + API_BATCH_SIZE]
        
        # Prepare batch: list of (id, text)
        problems_batch = []
        for i, problem in batch:
            problem_text = problem.get('rewritten_problem') or problem.get('text', '')
            problems_batch.append((problem.get('id'), problem_text))
        
        try:
            results = classify_batch(problems_batch)
            
            # Apply results
            for i, problem in batch:
                pid = problem.get('id')
                problem['type'] = results.get(pid, 'unknown')
            
            api_classified += len(batch)
            
            # Checkpoint every BATCH_SIZE
            if api_classified % BATCH_SIZE < API_BATCH_SIZE:
                sample = batch[0][1]  # First problem in this batch
                sample_text = sample.get('rewritten_problem') or sample.get('text', '')
                print(f"\n========== CHECKPOINT: {api_classified} classified ==========")
                print(f"Sample: {sample_text[:100]}...")
                print(f"Type: {sample.get('type')}")
                print("=======================================================\n")
            
            # Progress
            print(f"\rAPI Progress: {api_classified}/{len(needs_api)}", end="", flush=True)
            
        except Exception as err:
            print(f"\nError classifying batch starting at {batch_start}: {err}")
            for i, problem in batch:
                problem['type'] = 'unknown'
            api_classified += len(batch)
            time.sleep(1)
    
    # Write output CSV
    print(f"\n\nWriting output to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(problems)
    
    # Final report
    print("\n============ FINAL REPORT ============")
    print(f"Auto-classified from source: {auto_classified}")
    print(f"API-classified: {api_classified}")
    print("============ DONE ============")


if __name__ == "__main__":
    main()