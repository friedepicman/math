#!/usr/bin/env python3
"""
Compare extracted answers CSV against Supabase problems table.
"""

import csv
import os
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

CSV_PATH = Path("extracted_answers_with_aime.csv")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Answer Comparison: CSV vs Supabase")
    print("=" * 60)
    
    # Load CSV
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
    
    print(f"Loaded {len(csv_rows)} rows from CSV")
    
    # Build lookup: source -> {answer, aime_answer}
    csv_lookup = {}
    for row in csv_rows:
        source = row["source"].strip()
        aime = row.get("aime_answer", "").strip()
        answer = row.get("answer", "").strip()
        if source and aime:
            csv_lookup[source] = {
                "aime_answer": int(aime),
                "answer": answer
            }
    
    print(f"Sources with aime_answer in CSV: {len(csv_lookup)}")
    
    # Connect to Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Fetch all problems (paginated)
    print("\nFetching problems from Supabase...")
    all_problems = []
    page_size = 1000
    offset = 0
    
    while True:
        response = supabase.table("problems").select("id, source, answer, aime_answer").range(offset, offset + page_size - 1).execute()
        batch = response.data
        if not batch:
            break
        all_problems.extend(batch)
        offset += page_size
        print(f"  Fetched {len(all_problems)} problems...")
    
    print(f"Total problems in DB: {len(all_problems)}")
    
    # Compare
    matched = 0
    no_match = 0
    
    # Categories for matched sources
    can_fill = []        # DB has no aime_answer, CSV has one
    both_match = []      # Both have aime_answer, they match
    both_differ = []     # Both have aime_answer, they differ
    
    for prob in all_problems:
        db_source = (prob.get("source") or "").strip()
        db_aime = prob.get("aime_answer")
        db_answer = prob.get("answer") or ""
        
        if db_source in csv_lookup:
            matched += 1
            csv_data = csv_lookup[db_source]
            csv_aime = csv_data["aime_answer"]
            csv_answer = csv_data["answer"]
            
            if db_aime is None:
                # Can fill this one!
                can_fill.append({
                    "id": prob["id"],
                    "source": db_source,
                    "csv_answer": csv_answer,
                    "csv_aime_answer": csv_aime
                })
            elif db_aime == csv_aime:
                both_match.append(prob["id"])
            else:
                both_differ.append({
                    "id": prob["id"],
                    "source": db_source,
                    "db_answer": db_answer,
                    "db_aime_answer": db_aime,
                    "csv_answer": csv_answer,
                    "csv_aime_answer": csv_aime
                })
        else:
            no_match += 1
    
    # Results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    print(f"\nSource matching:")
    print(f"  Matched sources: {matched}")
    print(f"  No match in CSV: {no_match}")
    
    print(f"\nFor matched sources:")
    print(f"  ✓ Can fill (DB empty, CSV has aime_answer): {len(can_fill)}")
    print(f"  ✓ Both match: {len(both_match)}")
    print(f"  ⚠ Both differ: {len(both_differ)}")
    
    # Save results for review
    if can_fill:
        with open("can_fill.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "source", "csv_answer", "csv_aime_answer"])
            writer.writeheader()
            writer.writerows(can_fill)
        print(f"\n→ Saved {len(can_fill)} fillable problems to can_fill.csv")
    
    if both_differ:
        with open("aime_conflicts.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "source", "db_answer", "db_aime_answer", "csv_answer", "csv_aime_answer"])
            writer.writeheader()
            writer.writerows(both_differ)
        print(f"→ Saved {len(both_differ)} conflicts to aime_conflicts.csv")


if __name__ == "__main__":
    main()