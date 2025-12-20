#!/usr/bin/env python3
"""
Solution Markdown Answer Extractor

Extracts answers from Mathpix-generated markdown files using Claude.
Outputs a single CSV with source and answer columns for matching to Supabase.
"""

import os
import re
import csv
import json
from pathlib import Path
import anthropic

# ============================================================================
# CONFIGURATION
# ============================================================================

MD_DIRS = [
    Path("mathpix_output/hmmt_pdfs"),
    Path("mathpix_output/pumac_pdfs"),
    Path("mathpix_output/smt_pdfs"),
]

OUTPUT_CSV = Path("extracted_answers_md.csv")
STATE_FILE = Path("md_extractor_state.json")
MODEL = "claude-sonnet-4-20250514"

# ============================================================================
# SOURCE NAME PARSING
# ============================================================================

def parse_filename_to_source_prefix(filename: str) -> str | None:
    """Convert markdown filename to source prefix."""
    name = filename.replace(".md", "")
    
    if "Solutions" not in name and "Solution" not in name:
        return None
    
    name = re.sub(r"_?Solutions?$", "", name, flags=re.IGNORECASE)
    source_prefix = name.replace("_", " ")
    
    return source_prefix


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed": [], "results": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Solution Markdown Answer Extractor")
    print("=" * 50)
    
    client = anthropic.Anthropic()
    
    # Collect all solution markdown files
    md_files = []
    for md_dir in MD_DIRS:
        if not md_dir.exists():
            print(f"Warning: Directory {md_dir} not found, skipping")
            continue
        
        for md_file in sorted(md_dir.glob("*.md")):
            source_prefix = parse_filename_to_source_prefix(md_file.name)
            if source_prefix:
                md_files.append((md_file, source_prefix))
    
    print(f"Found {len(md_files)} solution markdown files")
    
    # Load state for resume support
    state = load_state()
    processed = set(state["processed"])
    all_results = state["results"]
    
    if processed:
        print(f"Resuming - {len(processed)} already processed")
    
    system_prompt = """You extract answers from math competition solution documents.

STEP 1: First, scan the document and list ALL problem numbers you find (e.g., "Found problems: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10")

STEP 2: For EACH problem number, extract its answer. Look for patterns like:
- "Answer: X"
- "(ANS: X)"
- Boxed answers
- Answers stated at the beginning of solutions

STEP 3: Output in JSONL format, one line per problem:
{"num": "1", "answer": "42"}
{"num": "2", "answer": "\\frac{5}{3}"}

Rules:
- "num" is the problem number
- "answer" is the final answer in LaTeX exactly as written
- Skip proof problems without numerical/expression answers
- Make sure you don't miss any problems!"""

    # Process each file
    for i, (md_path, source_prefix) in enumerate(md_files):
        if md_path.name in processed:
            continue
        
        print(f"[{i+1}/{len(md_files)}] {md_path.name}...", end=" ", flush=True)
        
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": f"Extract every answer from this document. First list all problem numbers you find, then extract each answer:\n\n{content}"}],
            )
            
            response_text = response.content[0].text
            
            # Parse JSONL (skip the "Found problems" line)
            count = 0
            for line in response_text.strip().split("\n"):
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                    source = f"{source_prefix} #{obj['num']}"
                    all_results.append({
                        "source": source,
                        "answer": obj["answer"],
                        "source_file": md_path.name
                    })
                    count += 1
                except (json.JSONDecodeError, KeyError):
                    pass
            
            print(f"✓ {count} answers")
            
            # Update state
            processed.add(md_path.name)
            state["processed"] = list(processed)
            state["results"] = all_results
            save_state(state)
            
        except Exception as e:
            print(f"✗ Error: {e}")
    
    # Write final CSV
    print(f"\nWriting {len(all_results)} answers to {OUTPUT_CSV}...")
    
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "answer", "source_file"])
        writer.writeheader()
        writer.writerows(all_results)
    
    # Clean up state file
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    
    print(f"✓ Done!")
    
    # Summary
    print("\nSummary:")
    print("-" * 30)
    competitions = {}
    for r in all_results:
        comp = r["source"].split()[0]
        competitions[comp] = competitions.get(comp, 0) + 1
    
    for comp, count in sorted(competitions.items()):
        print(f"  {comp}: {count} answers")


if __name__ == "__main__":
    main()