#!/usr/bin/env python3
"""Check for duplicate problem IDs in the database fetch."""

import os
from collections import Counter
from supabase import create_client

SUPABASE_URL = "https://ftdbplxkyaocyrjpmjyb.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def main():
    if not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_KEY environment variable")
        return
    
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print("Fetching problems...")
    all_problems = []
    chunk_size = 1000
    offset = 0
    
    while True:
        response = supabase.table("problems").select("id").range(offset, offset + chunk_size - 1).execute()
        if not response.data:
            break
        all_problems.extend(response.data)
        offset += chunk_size
        print(f"  Fetched {len(all_problems)} problems...")
    
    print(f"\nTotal problems fetched: {len(all_problems)}")
    
    # Check for duplicates
    ids = [p['id'] for p in all_problems]
    id_counts = Counter(ids)
    duplicates = {k: v for k, v in id_counts.items() if v > 1}
    
    if duplicates:
        print(f"\nDUPLICATES FOUND: {len(duplicates)} IDs appear more than once")
        for id, count in sorted(duplicates.items()):
            print(f"  ID {id}: appears {count} times")
    else:
        print("\nNo duplicate IDs found in fetch.")
    
    print(f"\nUnique IDs: {len(set(ids))}")
    print(f"Total rows: {len(ids)}")

if __name__ == "__main__":
    main()