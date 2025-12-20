#!/usr/bin/env python3
"""
Solution PDF Answer Extractor

Extracts answers from HMMT, SMT, and PUMaC solution PDFs using Claude API.
Outputs a single CSV with source and answer columns for matching to Supabase.
"""

import os
import csv
import base64
import time
import re
from pathlib import Path
import anthropic

# ============================================================================
# CONFIGURATION
# ============================================================================

PDF_DIRS = [
    Path("hmmt_pdfs"),
    Path("pumac_pdfs"),
    Path("smt_pdfs"),
]

OUTPUT_CSV = Path("extracted_answers.csv")

# Rate limiting
DELAY_BETWEEN_REQUESTS = 1.0  # seconds

# ============================================================================
# SOURCE NAME PARSING
# ============================================================================

def parse_filename_to_source_prefix(filename: str) -> str | None:
    """
    Convert PDF filename to source prefix for matching.
    
    Examples:
        HMMT_February_2008_Algebra_Solutions.pdf -> HMMT February 2008 Algebra
        SMT_2019_Geometry_Solutions.pdf -> SMT 2019 Geometry
        PUMaC_2017_Combinatorics_A_Solutions.pdf -> PUMaC 2017 Combinatorics A
    """
    # Remove .pdf extension
    name = filename.replace(".pdf", "")
    
    # Skip if not a solutions file
    if "Solutions" not in name and "Solution" not in name:
        return None
    
    # Remove Solutions/Solution suffix
    name = re.sub(r"_?Solutions?$", "", name, flags=re.IGNORECASE)
    
    # Replace underscores with spaces
    source_prefix = name.replace("_", " ")
    
    return source_prefix


def generate_source(prefix: str, problem_num: int | str) -> str:
    """Generate full source string like 'HMMT February 2008 Algebra #3'."""
    return f"{prefix} #{problem_num}"


# ============================================================================
# PDF PROCESSING WITH CLAUDE
# ============================================================================

def extract_answers_from_pdf(client: anthropic.Anthropic, pdf_path: Path) -> list[dict]:
    """
    Send PDF to Claude and extract problem numbers and answers.
    Returns list of {"problem_num": x, "answer": y} dicts.
    """
    # Read and encode PDF
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    prompt = """Extract all problem numbers and their final answers from this solutions PDF.

For each problem, provide:
1. The problem number (as it appears in the document)
2. The final answer in LaTeX format (preserve exact formatting)

Output as a simple list in this exact format, one per line:
PROBLEM: <number> | ANSWER: <latex answer>

Examples of correct output format:
PROBLEM: 1 | ANSWER: 42
PROBLEM: 2 | ANSWER: \\frac{7}{3}
PROBLEM: 3 | ANSWER: 2\\sqrt{5}

Important:
- Extract ONLY the final boxed/highlighted answer, not intermediate steps
- Preserve LaTeX formatting exactly as shown (fractions, square roots, etc.)
- If a problem has multiple parts (a, b, c), list each separately as 1a, 1b, 1c
- If you cannot determine the answer for a problem, skip it
- Do not include any other text or explanation, just the PROBLEM/ANSWER lines"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )
    
    # Parse response
    results = []
    response_text = response.content[0].text
    
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        
        match = re.match(r"PROBLEM:\s*(.+?)\s*\|\s*ANSWER:\s*(.+)", line)
        if match:
            prob_num = match.group(1).strip()
            answer = match.group(2).strip()
            results.append({"problem_num": prob_num, "answer": answer})
    
    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Solution PDF Answer Extractor")
    print("=" * 50)
    
    # Initialize client
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    
    # Collect all solution PDFs
    pdf_files = []
    for pdf_dir in PDF_DIRS:
        if not pdf_dir.exists():
            print(f"Warning: Directory {pdf_dir} not found, skipping")
            continue
        
        for pdf_file in sorted(pdf_dir.glob("*.pdf")):
            source_prefix = parse_filename_to_source_prefix(pdf_file.name)
            if source_prefix:  # Only solution files
                pdf_files.append((pdf_file, source_prefix))
    
    print(f"Found {len(pdf_files)} solution PDFs to process\n")
    
    # Process each PDF and collect results
    all_results = []
    
    for i, (pdf_path, source_prefix) in enumerate(pdf_files):
        print(f"[{i+1}/{len(pdf_files)}] Processing {pdf_path.name}...")
        
        try:
            answers = extract_answers_from_pdf(client, pdf_path)
            
            for entry in answers:
                source = generate_source(source_prefix, entry["problem_num"])
                all_results.append({
                    "source": source,
                    "answer": entry["answer"],
                    "source_file": pdf_path.name,
                })
            
            print(f"    ✓ Extracted {len(answers)} answers")
            
        except Exception as e:
            print(f"    ✗ Error: {e}")
        
        # Rate limiting
        if i < len(pdf_files) - 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)
    
    # Write to CSV
    print(f"\nWriting {len(all_results)} answers to {OUTPUT_CSV}...")
    
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "answer", "source_file"])
        writer.writeheader()
        writer.writerows(all_results)
    
    print(f"✓ Done! Results saved to {OUTPUT_CSV}")
    
    # Summary by competition
    print("\nSummary:")
    print("-" * 30)
    competitions = {}
    for r in all_results:
        comp = r["source"].split()[0]  # HMMT, SMT, or PUMaC
        competitions[comp] = competitions.get(comp, 0) + 1
    
    for comp, count in sorted(competitions.items()):
        print(f"  {comp}: {count} answers")


if __name__ == "__main__":
    main()