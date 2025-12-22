#!/usr/bin/env python3
"""
Problem Analyzer for MockAIME
Analyzes all problems using Claude Batch API and inserts issues into problem_reports table.

Usage:
1. Set environment variables:
   - ANTHROPIC_API_KEY: Your Anthropic API key
   - SUPABASE_URL: Your Supabase project URL
   - SUPABASE_KEY: Your Supabase service role key (not anon key, needs insert permissions)

2. Run the script:
   python analyze_problems.py --create-batch    # Create and submit batch
   python analyze_problems.py --check-batch BATCH_ID  # Check batch status
   python analyze_problems.py --process-batch BATCH_ID  # Process completed batch results
"""

import os
import json
import argparse
import time
from datetime import datetime
from typing import Optional
import anthropic
from supabase import create_client, Client

# Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ftdbplxkyaocyrjpmjyb.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # Use service role key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "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")

MODEL = "claude-opus-4-20250514"

ANALYSIS_PROMPT = """You are a math competition problem quality reviewer. Analyze this problem and identify ONLY significant issues that require attention.

<problem>
ID: {problem_id}
Source: {source}
Current Difficulty: {difficulty}
Current Quality: {quality}
Original Answer: {answer}
AIME Answer: {aime_answer}

Original Problem Text:
{text}

Rewritten Problem Text:
{rewritten_problem}
</problem>

Check for these issues ONLY. Be conservative - only flag things you're confident about:

1. **INCOHERENT/MULTIPLE PROBLEMS**: The text contains multiple unrelated problems mashed together, or is completely incoherent/nonsensical.

2. **MISSING DIAGRAM**: Problem explicitly mentions "figure", "diagram", "shown below", "the following figure", "as shown", or similar phrases that indicate a visual is required, but no diagram exists. Do NOT flag if the problem can be solved without a diagram.

3. **DIFFICULTY WAY OFF** (2+ points): Only flag if:
   - Problem is trivially easy (basic arithmetic, simple substitution) but rated 2+ points higher than it should be
   - Problem is very hard (requires advanced techniques, multiple insights) but rated 2+ points lower than it should be
   - You must be confident the rating is off by AT LEAST 2 points
   - Use the AoPS difficulty scale: 1-1.5 is AMC 8, 2-3 is AMC 10, 3-4 is AMC 12, 4-6 is AIME, 6-7 is hard AIME, 7+ is olympiad

4. **UNSOLVABLE**: Missing critical information, contradictory conditions, or mathematically impossible.

5. **GARBLED/UNREADABLE**: LaTeX is so broken the problem cannot be understood at all.

Respond with a JSON object. If there are NO significant issues, respond with exactly:
{{"issues": null}}

If there ARE issues, respond with:
{{
  "issues": {{
    "types": ["list", "of", "issue", "types"],
    "difficulty_suggestion": null or number (only if difficulty is 2+ points off),
    "quality_suggestion": null or number (only if problem is clearly broken, suggest 1 or 2),
    "problem_suggestion": null or "corrected problem text" (only if you can fix it),
    "explanation": "Brief explanation of what's wrong"
  }}
}}

Issue types can be: "incoherent", "missing_diagram", "difficulty", "unsolvable", "garbled"

Remember:
- Be conservative. When in doubt, don't flag.
- Only flag difficulty if it's 2+ points off
- Only flag quality if the problem is fundamentally broken (suggest 1-2 stars)
- Don't flag minor LaTeX issues that don't affect readability
- Don't flag style preferences or minor wording issues"""


def get_supabase_client() -> Client:
    """Create Supabase client."""
    if not SUPABASE_KEY:
        raise ValueError("SUPABASE_KEY environment variable not set")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_anthropic_client() -> anthropic.Anthropic:
    """Create Anthropic client."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def fetch_all_problems(supabase: Client) -> list[dict]:
    """Fetch all problems from Supabase."""
    print("Fetching problems from Supabase...")
    all_problems = []
    chunk_size = 1000
    offset = 0
    
    while True:
        response = supabase.table("problems").select("*").range(offset, offset + chunk_size - 1).execute()
        if not response.data:
            break
        all_problems.extend(response.data)
        offset += chunk_size
        print(f"  Fetched {len(all_problems)} problems...")
    
    print(f"Total: {len(all_problems)} problems")
    return all_problems


def create_batch_request(problem: dict, row_index: int, batch_num: int = 1) -> dict:
    """Create a single batch request for a problem."""
    prompt = ANALYSIS_PROMPT.format(
        problem_id=problem.get("id"),
        source=problem.get("source") or "Unknown",
        difficulty=problem.get("difficulty") or "Unknown",
        quality=problem.get("quality") or "Unknown",
        answer=problem.get("answer") or "Unknown",
        aime_answer=problem.get("aime_answer") or "Unknown",
        text=problem.get("text") or "(empty)",
        rewritten_problem=problem.get("rewritten_problem") or "(empty)"
    )
    
    return {
        "custom_id": f"batch{batch_num}-row{row_index}-pid{problem['id']}",
        "params": {
            "model": MODEL,
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"}
            ]
        }
    }


def create_batch(problems: list[dict], output_file: str = "batch_requests.jsonl", batch_num: int = 1, start_row: int = 0) -> str:
    """Create batch request file and submit to Anthropic."""
    client = get_anthropic_client()
    
    # Create JSONL file
    actual_output_file = output_file.replace(".jsonl", f"_{batch_num}.jsonl")
    print(f"Creating batch request file: {actual_output_file}")
    with open(actual_output_file, "w") as f:
        for i, problem in enumerate(problems):
            row_index = start_row + i
            request = create_batch_request(problem, row_index=row_index, batch_num=batch_num)
            f.write(json.dumps(request) + "\n")
    
    print(f"Wrote {len(problems)} requests to {actual_output_file}")
    
    # Upload and create batch
    print("Uploading batch to Anthropic...")
    
    # Read requests from file
    requests = []
    with open(actual_output_file, "r") as f:
        for line in f:
            requests.append(json.loads(line))
    
    batch = client.messages.batches.create(requests=requests)
    
    print(f"Batch created successfully!")
    print(f"  Batch ID: {batch.id}")
    print(f"  Status: {batch.processing_status}")
    print(f"  Total requests: {batch.request_counts.processing}")
    
    return batch.id


def create_all_batches(problems: list[dict], batch_size: int = 3000, start_batch_num: int = 1, start_row: int = 0) -> list[str]:
    """Split problems into multiple batches and submit all."""
    batch_ids = []
    total_batches = (len(problems) + batch_size - 1) // batch_size
    
    print(f"Splitting {len(problems)} problems into {total_batches} batches of up to {batch_size} each\n")
    
    for i in range(0, len(problems), batch_size):
        batch_num = start_batch_num + (i // batch_size)
        batch_problems = problems[i:i + batch_size]
        row_offset = start_row + i
        print(f"=== Batch {batch_num} ({len(batch_problems)} problems, rows {row_offset}-{row_offset + len(batch_problems) - 1}) ===")
        
        batch_id = create_batch(batch_problems, batch_num=batch_num, start_row=row_offset)
        batch_ids.append(batch_id)
        print()
    
    return batch_ids


def check_batch_status(batch_id: str) -> dict:
    """Check the status of a batch."""
    client = get_anthropic_client()
    batch = client.messages.batches.retrieve(batch_id)
    
    print(f"Batch ID: {batch.id}")
    print(f"Status: {batch.processing_status}")
    print(f"Request counts:")
    print(f"  Processing: {batch.request_counts.processing}")
    print(f"  Succeeded: {batch.request_counts.succeeded}")
    print(f"  Errored: {batch.request_counts.errored}")
    print(f"  Canceled: {batch.request_counts.canceled}")
    print(f"  Expired: {batch.request_counts.expired}")
    
    if batch.ended_at:
        print(f"Ended at: {batch.ended_at}")
    
    return {
        "id": batch.id,
        "status": batch.processing_status,
        "counts": {
            "processing": batch.request_counts.processing,
            "succeeded": batch.request_counts.succeeded,
            "errored": batch.request_counts.errored,
            "canceled": batch.request_counts.canceled,
            "expired": batch.request_counts.expired
        }
    }


def parse_claude_response(response_text: str) -> Optional[dict]:
    """Parse Claude's JSON response."""
    try:
        # Try to find JSON in the response
        text = response_text.strip()
        
        # Handle case where response is wrapped in markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()
        
        data = json.loads(text)
        return data
    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse JSON: {e}")
        return None


def process_batch_results(batch_id: str):
    """Process completed batch results and insert into problem_reports."""
    client = get_anthropic_client()
    supabase = get_supabase_client()
    
    # Check batch status first
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        print(f"Batch is not complete. Status: {batch.processing_status}")
        return
    
    print(f"Processing batch results...")
    print(f"  Succeeded: {batch.request_counts.succeeded}")
    print(f"  Errored: {batch.request_counts.errored}")
    
    # Get results
    issues_found = 0
    errors = 0
    no_issues = 0
    reports_to_insert = []
    
    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        # Extract problem_id - handle both formats:
        # Old: "problem-123" 
        # New: "batch1-row0-pid123"
        if "-pid" in custom_id:
            problem_id = int(custom_id.split("-pid")[1])
        else:
            problem_id = int(custom_id.replace("problem-", ""))
        
        if result.result.type == "error":
            print(f"  Error for problem {problem_id}: {result.result.error}")
            errors += 1
            continue
        
        # Get the response text (prepend { since we used prefill)
        response = result.result.message
        if not response.content:
            errors += 1
            continue
            
        response_text = "{" + response.content[0].text
        
        # Parse the response
        parsed = parse_claude_response(response_text)
        if parsed is None:
            errors += 1
            continue
        
        # Check if there are issues
        issues = parsed.get("issues")
        if issues is None:
            no_issues += 1
            continue
        
        # We have issues - create a report
        issues_found += 1
        
        report_types = issues.get("types", [])
        
        # Build the report data matching the existing schema
        report_data = {
            "problem_id": problem_id,
            "report_types": report_types,
            "ai_generated": True,
            "ai_model": MODEL,
            "timestamp": datetime.now().isoformat()
        }
        
        if issues.get("difficulty_suggestion"):
            report_data["difficulty_rating"] = issues["difficulty_suggestion"]
            report_data["difficulty_details"] = issues.get("explanation", "")
        
        if issues.get("quality_suggestion"):
            report_data["quality_rating"] = issues["quality_suggestion"]
            report_data["quality_details"] = issues.get("explanation", "")
        
        if issues.get("problem_suggestion"):
            report_data["proposed_problem"] = issues["problem_suggestion"]
            report_data["problem_details"] = issues.get("explanation", "")
        
        # Always include explanation
        if "explanation" in issues:
            report_data["general_details"] = issues["explanation"]
        
        reports_to_insert.append({
            "problem_id": problem_id,
            "report_type": ",".join(report_types) if report_types else "ai_review",
            "details": json.dumps(report_data)
        })
        
        print(f"  Problem {problem_id}: {report_types} - {issues.get('explanation', '')[:50]}...")
    
    print(f"\nSummary:")
    print(f"  No issues: {no_issues}")
    print(f"  Issues found: {issues_found}")
    print(f"  Errors: {errors}")
    
    # Insert reports into database
    if reports_to_insert:
        print(f"\nInserting {len(reports_to_insert)} reports into problem_reports...")
        
        # Insert in batches of 100
        batch_size = 100
        for i in range(0, len(reports_to_insert), batch_size):
            batch = reports_to_insert[i:i + batch_size]
            try:
                supabase.table("problem_reports").insert(batch).execute()
                print(f"  Inserted {i + len(batch)}/{len(reports_to_insert)}")
            except Exception as e:
                print(f"  Error inserting batch: {e}")
        
        print("Done!")
    else:
        print("No reports to insert.")


def test_single_problem(problem_id: int):
    """Test analysis on a single problem (for debugging)."""
    supabase = get_supabase_client()
    client = get_anthropic_client()
    
    # Fetch the problem
    response = supabase.table("problems").select("*").eq("id", problem_id).execute()
    if not response.data:
        print(f"Problem {problem_id} not found")
        return
    
    problem = response.data[0]
    print(f"Testing problem {problem_id}:")
    print(f"  Source: {problem.get('source')}")
    print(f"  Difficulty: {problem.get('difficulty')}")
    print(f"  Text preview: {(problem.get('text') or '')[:100]}...")
    
    # Create and send request
    prompt = ANALYSIS_PROMPT.format(
        problem_id=problem.get("id"),
        source=problem.get("source") or "Unknown",
        difficulty=problem.get("difficulty") or "Unknown",
        quality=problem.get("quality") or "Unknown",
        answer=problem.get("answer") or "Unknown",
        aime_answer=problem.get("aime_answer") or "Unknown",
        text=problem.get("text") or "(empty)",
        rewritten_problem=problem.get("rewritten_problem") or "(empty)"
    )
    
    print("\nSending to Claude...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"}
        ]
    )
    
    response_text = "{" + response.content[0].text
    print(f"\nRaw response:\n{response_text}")
    
    parsed = parse_claude_response(response_text)
    print(f"\nParsed response:\n{json.dumps(parsed, indent=2)}")


def main():
    parser = argparse.ArgumentParser(description="Analyze MockAIME problems with Claude")
    parser.add_argument("--create-batch", action="store_true", help="Create and submit batches")
    parser.add_argument("--batch-size", type=int, default=3000, help="Problems per batch (default: 3000)")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N problems (for resuming)")
    parser.add_argument("--start-batch-num", type=int, default=1, help="Starting batch number (default: 1)")
    parser.add_argument("--check-batch", type=str, help="Check status of a batch by ID")
    parser.add_argument("--check-all", type=str, help="Check status of multiple batch IDs (comma-separated)")
    parser.add_argument("--process-batch", type=str, help="Process completed batch results")
    parser.add_argument("--process-all", type=str, help="Process multiple batch IDs (comma-separated)")
    parser.add_argument("--test-problem", type=int, help="Test analysis on a single problem ID")
    parser.add_argument("--limit", type=int, help="Limit number of problems (for testing)")
    
    args = parser.parse_args()
    
    if args.test_problem:
        test_single_problem(args.test_problem)
    elif args.create_batch:
        supabase = get_supabase_client()
        problems = fetch_all_problems(supabase)
        start_row = args.skip
        if args.skip:
            problems = problems[args.skip:]
            print(f"Skipped first {args.skip} problems, {len(problems)} remaining")
        if args.limit:
            problems = problems[:args.limit]
            print(f"Limited to {len(problems)} problems for testing")
        batch_ids = create_all_batches(problems, batch_size=args.batch_size, start_batch_num=args.start_batch_num, start_row=start_row)
        print(f"\n{'='*50}")
        print(f"Created {len(batch_ids)} batches:")
        for i, bid in enumerate(batch_ids, 1):
            print(f"  Batch {i}: {bid}")
        print(f"\nSave these batch IDs!")
        print(f"Check status with: python analyze_problems.py --check-all {','.join(batch_ids)}")
        print(f"Process results with: python analyze_problems.py --process-all {','.join(batch_ids)}")
    elif args.check_batch:
        check_batch_status(args.check_batch)
    elif args.check_all:
        batch_ids = [b.strip() for b in args.check_all.split(",")]
        for i, bid in enumerate(batch_ids, 1):
            print(f"\n=== Batch {i}/{len(batch_ids)} ===")
            check_batch_status(bid)
    elif args.process_batch:
        process_batch_results(args.process_batch)
    elif args.process_all:
        batch_ids = [b.strip() for b in args.process_all.split(",")]
        for i, bid in enumerate(batch_ids, 1):
            print(f"\n{'='*50}")
            print(f"=== Processing Batch {i}/{len(batch_ids)}: {bid} ===")
            print(f"{'='*50}")
            process_batch_results(bid)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()