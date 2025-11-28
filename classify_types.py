#!/usr/bin/env python3
"""
Classify MAA problems by type using Claude Batch API.
Types: algebra, geometry, number_theory, counting
"""

import pandas as pd
import json
import time
import argparse
import anthropic

# Initialize client
client = anthropic.Anthropic()

CLASSIFICATION_PROMPT = """Classify this math competition problem into ONE of these categories:
- algebra (equations, polynomials, functions, sequences, inequalities)
- geometry (shapes, angles, areas, volumes, coordinate geometry, trigonometry)
- number_theory (divisibility, primes, modular arithmetic, digits)
- counting (combinatorics, probability, permutations, combinations)
- other (game theory, logic puzzles, or doesn't fit the above)

If the problem clearly fits multiple categories equally, choose the most dominant one.

Problem:
{problem_text}

Respond with ONLY the category name, nothing else. Just one word: algebra, geometry, number_theory, counting, or other."""


def create_batch_requests(problems_df):
    """Create batch requests for classification."""
    requests = []
    
    for idx, row in problems_df.iterrows():
        problem_text = row['text']
        
        request = {
            "custom_id": str(idx),
            "params": {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 20,
                "messages": [
                    {"role": "user", "content": CLASSIFICATION_PROMPT.format(problem_text=problem_text)}
                ]
            }
        }
        requests.append(request)
    
    return requests


def submit_batch(requests):
    """Submit batch to Claude API."""
    print(f"Submitting batch with {len(requests)} requests...")
    
    batch = client.messages.batches.create(requests=requests)
    
    print(f"Batch ID: {batch.id}")
    print(f"Status: {batch.processing_status}")
    
    # Save batch info
    with open("classify_batch_info.json", "w") as f:
        json.dump({"batch_id": batch.id}, f)
    
    return batch.id


def poll_batch(batch_id):
    """Poll until batch is complete."""
    print(f"Polling batch {batch_id}...")
    
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        
        completed = batch.request_counts.succeeded + batch.request_counts.errored
        total = completed + batch.request_counts.processing
        
        print(f"  Status: {status} | Progress: {completed}/{total}")
        
        if status == "ended":
            print(f"Batch complete!")
            print(f"  Succeeded: {batch.request_counts.succeeded}")
            print(f"  Errored: {batch.request_counts.errored}")
            return batch
        
        time.sleep(10)


def download_results(batch_id, df):
    """Download results and update dataframe."""
    batch = client.messages.batches.retrieve(batch_id)
    
    if not batch.results_url:
        print("No results URL available")
        return df
    
    print(f"Downloading results...")
    
    # Get results
    results = {}
    for result in client.messages.batches.results(batch_id):
        custom_id = result.custom_id
        if result.result.type == "succeeded":
            response_text = result.result.message.content[0].text.strip().lower()
            # Validate response
            if response_text in ["algebra", "geometry", "number_theory", "counting", "other"]:
                results[int(custom_id)] = response_text
            else:
                print(f"  Warning: Invalid type '{response_text}' for {custom_id}")
                results[int(custom_id)] = "other"  # Default fallback
        else:
            print(f"  Error for {custom_id}: {result.result}")
    
    print(f"Got {len(results)} results")
    
    # Update dataframe
    df['type'] = df.index.map(lambda x: results.get(x, ""))
    
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['submit', 'poll', 'download', 'run'])
    parser.add_argument('--input', default='maa_problems_deduped.csv', help='Input CSV file')
    parser.add_argument('--output', default='maa_problems_typed.csv', help='Output CSV file')
    parser.add_argument('--batch-id', type=str, help='Batch ID for poll/download')
    
    args = parser.parse_args()
    
    if args.command in ['submit', 'run']:
        # Load data
        df = pd.read_csv(args.input)
        print(f"Loaded {len(df)} problems from {args.input}")
        
        # Create and submit batch
        requests = create_batch_requests(df)
        batch_id = submit_batch(requests)
        
        if args.command == 'run':
            # Wait for completion
            poll_batch(batch_id)
            
            # Download and save
            df = download_results(batch_id, df)
            df.to_csv(args.output, index=False)
            print(f"Saved to {args.output}")
            
            # Print type distribution
            print("\nType distribution:")
            print(df['type'].value_counts())
    
    elif args.command == 'poll':
        batch_id = args.batch_id
        if not batch_id:
            with open("classify_batch_info.json") as f:
                batch_id = json.load(f)['batch_id']
        poll_batch(batch_id)
    
    elif args.command == 'download':
        batch_id = args.batch_id
        if not batch_id:
            with open("classify_batch_info.json") as f:
                batch_id = json.load(f)['batch_id']
        
        df = pd.read_csv(args.input)
        df = download_results(batch_id, df)
        df.to_csv(args.output, index=False)
        print(f"Saved to {args.output}")
        
        # Print type distribution
        print("\nType distribution:")
        print(df['type'].value_counts())


if __name__ == "__main__":
    main()