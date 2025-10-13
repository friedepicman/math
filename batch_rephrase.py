#!/usr/bin/env python3
"""
Batch rephrase problems for AIME format using Claude Sonnet 4.5
"""

import os
import time
import re
from datetime import datetime
from anthropic import Anthropic
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize clients
anthropic_client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_KEY')
)

SYSTEM_PROMPT = """You are an expert at rephrasing mathematics competition problems into AIME (American Invitational Mathematics Examination) format.

CRITICAL REQUIREMENTS:
1. Answer must be an integer from 000 to 999
2. Keep the problem statement IDENTICAL - do NOT simplify, clarify, or reword the problem itself
3. Only change the final question to apply the appropriate answer format template

YOUR TASK:
Given an original problem and its answer, determine the appropriate AIME format template and apply it.

COMMON ANSWER FORMAT TEMPLATES:

For FRACTIONS (answer like 5/3):
"can be written in the form $\\frac{a}{b}$, where $a$ and $b$ are relatively prime positive integers. Compute $a+b$"

For SIMPLE RADICALS (answer like 6√3):
"can be written in the form $a\\sqrt{b}$, where $b$ is not divisible by the square of a prime. Compute $a+b$"
NOTE: If a+b > 999, use "Compute the remainder when $a+b$ is divided by $1000$"

For RADICAL FRACTIONS (answer like 5√3/12):
"can be written in the form $\\frac{a\\sqrt{b}}{c}$, where $a$ and $c$ are relatively prime positive integers and $b$ is not divisible by the square of a prime. Compute $a+b+c$"
NOTE: If a+b+c > 999, use "Compute the remainder when $a+b+c$ is divided by $1000$"

For MIXED RADICALS (answer like 3+2√5):
"can be expressed in the form $a+b\\sqrt{c}$, where $c$ is not divisible by the square of a prime. Compute $a+b+c$"
NOTE: If a+b+c > 999, use "Compute the remainder when $a+b+c$ is divided by $1000$"

For MIXED WITH MINUS (answer like (3-√3)/6):
"can be written in the form $\\frac{a-\\sqrt{b}}{c}$, where $b$ is not divisible by the square of a prime. Compute $a+b+c$"
(Use minus sign if answer has minus, plus if answer has plus)

For PI FRACTIONS (answer like 5π/3):
"can be written in the form $\\frac{a\\pi}{b}$, where $a$ and $b$ are relatively prime positive integers. Compute $a+b$"

For SIMPLE PI (answer like 7π):
"can be written in the form $a\\pi$. Find $a$"

For MIXED WITH PI (answer like 6√3 + 4π):
"can be expressed in the form $a\\sqrt{b} + c\\pi$, where $b$ is not divisible by the square of a prime. Compute $a+b+c$"

For LARGE INTEGERS (answer > 999):
Introduce a variable and ask for remainder mod 1000.
Example: "Let $m$ denote [the value being asked for]. Compute the remainder when $m$ is divided by $1000$"
OR simply: "Compute the remainder when [expression] is divided by $1000$"
Choose based on complexity - use variable for long expressions, direct for short ones.

For NEGATIVE ANSWERS:
Add absolute value bars around the expression: $|...|$
Example: "Compute $|expression|$" or "Evaluate $|\\sum...|$"

CRITICAL RULES:
1. When using templates with sums (like a+b+c), check if the sum exceeds 999
2. If sum > 999 OR you're unsure, add "Compute the remainder when [sum] is divided by $1000$"
3. Always ensure $a$ and $c$ are "relatively prime" for fraction templates (this ensures lowest terms)
4. Match the sign in the answer (use + if answer has +, use - if answer has -)
5. Keep problem statement completely unchanged - only modify the final question
6. Change "Find" → "Compute", "What is" → "Compute", "Evaluate" → "Compute" for consistency

OUTPUT FORMAT - CRITICAL:
You must output ONLY the final rephrased problem statement. Do NOT include:
- Your reasoning or thought process
- Explanations of your approach
- Phrases like "Looking at this problem" or "Following the template"
- Any commentary about the answer or problem type
- Any text before or after the problem statement

Simply output the rephrased problem and nothing else. Start directly with the problem text."""

def analyze_answer_format(answer_str):
    """
    Analyze the answer format to help guide the AI.
    This is for logging purposes only - the AI makes the final decision.
    """
    if not answer_str:
        return "unknown"
    
    answer_str = str(answer_str).strip()
    
    # Check for common patterns
    if '/' in answer_str and 'sqrt' in answer_str.lower():
        return "radical_fraction"
    elif '/' in answer_str and 'pi' in answer_str.lower():
        return "pi_fraction"
    elif '/' in answer_str:
        return "fraction"
    elif 'sqrt' in answer_str.lower() and ('+' in answer_str or '-' in answer_str):
        return "mixed_radical"
    elif 'sqrt' in answer_str.lower():
        return "simple_radical"
    elif 'pi' in answer_str.lower():
        return "pi_related"
    elif answer_str.lstrip('-').isdigit():
        num = int(answer_str)
        if num < 0:
            return "negative_integer"
        elif num > 999:
            return "large_integer"
        else:
            return "integer_in_range"
    else:
        return "complex_expression"

def rephrase_problem(original_text, answer, source=None, difficulty=None):
    """
    Rephrase a single problem using Claude Sonnet 4.5
    """
    try:
        # Build context information
        context_parts = []
        if source:
            context_parts.append(f"Source: {source}")
        if difficulty:
            context_parts.append(f"Difficulty: {difficulty}")
        if answer:
            context_parts.append(f"Answer: {answer}")
        
        context = " | ".join(context_parts) if context_parts else "No context provided"
        
        user_prompt = f"""Context: {context}

Original Problem:
{original_text}

Task: Rephrase this problem into AIME format. Apply the appropriate answer format template based on the answer provided. Remember:
- Keep the problem statement IDENTICAL
- Only change the final question
- Ensure the final answer will be an integer from 0-999
- If template sum exceeds 999, add mod 1000"""

        message = anthropic_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            temperature=0.3,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        )

        return message.content[0].text.strip()
    
    except Exception as e:
        print(f"Error calling Claude API: {e}")
        return None

def save_ai_rephrase(problem_id, rephrased_text, dry_run=False):
    """
    Save AI rephrased text to ai_rephrased table
    """
    if dry_run:
        return True
    
    try:
        # Use upsert to handle both insert and update
        result = supabase.table('ai_rephrased').upsert({
            'problem_id': problem_id,
            'ai_rephrased_text': rephrased_text,
            'model_used': 'claude-sonnet-4-5-20250929',
            'created_at': datetime.utcnow().isoformat(),
            'approved': False
        }, on_conflict='problem_id').execute()
        
        return bool(result.data)
    
    except Exception as e:
        print(f"Error saving to database: {e}")
        return False

def process_problems(
    batch_size=50,
    start_from_id=None,
    only_reviewed=False,
    only_with_answers=True,
    test_mode=False,
    dry_run=False,
    skip_existing=True,
    limit=None
):
    """
    Process problems in batches
    
    Args:
        batch_size: Number of problems to process before checkpoint
        start_from_id: Resume from specific problem ID
        only_reviewed: Only process manually reviewed problems
        only_with_answers: Only process problems with answers
        test_mode: Only process first 10 problems
        dry_run: Don't save to database, just show what would be done
        skip_existing: Skip problems that already have AI rephrases
        limit: Maximum number of problems to process (applied AFTER filtering)
    """
    
    print("\n" + "="*70)
    print("BATCH REPHRASE PROBLEMS FOR AIME FORMAT")
    print("="*70)
    print(f"Model: Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)")
    print(f"Max tokens: 4000")
    print(f"Output table: ai_rephrased")
    print(f"Dry run mode: {dry_run}")
    print(f"Skip existing: {skip_existing}")
    if limit:
        print(f"Limit: {limit} problems (applied after filtering)")
    print("="*70 + "\n")
    
    # Get existing AI rephrases if skip_existing is True
    existing_problem_ids = set()
    if skip_existing:
        existing_result = supabase.table('ai_rephrased').select('problem_id').execute()
        existing_problem_ids = {row['problem_id'] for row in existing_result.data}
        print(f"Found {len(existing_problem_ids)} existing AI rephrases (will skip)\n")
    
    # Build query - fetch ALL problems matching criteria
    # We'll apply limit AFTER filtering out existing ones
    query = supabase.table('problems').select('*')
    
    if only_reviewed:
        query = query.eq('manually_reviewed', True)
    
    if only_with_answers:
        query = query.not_.is_('answer', 'null')
    
    if start_from_id:
        query = query.gte('id', start_from_id)
    
    query = query.order('id')
    
    # Execute query to get ALL matching problems
    print("Loading all problems from database...")
    all_matching_problems = []
    from_index = 0
    chunk_size = 1000
    
    while True:
        result = query.range(from_index, from_index + chunk_size - 1).execute()
        if not result.data:
            break
        all_matching_problems.extend(result.data)
        from_index += chunk_size
        print(f"  Loaded {len(all_matching_problems)} problems so far...")
        if len(result.data) < chunk_size:
            break
    
    print(f"Total problems loaded: {len(all_matching_problems)}\n")
    
    if not all_matching_problems:
        print("No problems found matching criteria.")
        return
    
    # Filter out existing problems FIRST
    if skip_existing:
        problems_before_filter = len(all_matching_problems)
        all_matching_problems = [p for p in all_matching_problems if p['id'] not in existing_problem_ids]
        print(f"After filtering existing: {len(all_matching_problems)} problems remaining\n")
    
    # NOW apply limit AFTER filtering
    if test_mode:
        problems = all_matching_problems[:10]
    elif limit:
        problems = all_matching_problems[:limit]
    else:
        problems = all_matching_problems
    
    print(f"Will process {len(problems)} problems\n")
    
    if len(problems) == 0:
        print("All problems already have AI rephrases!")
        return
    
    # Statistics
    processed = 0
    errors = 0
    skipped = 0
    
    for i, problem in enumerate(problems):
        progress = f"[{i+1}/{len(problems)}]"
        problem_id = problem['id']
        
        print(f"{progress} Processing problem {problem_id}...")
        
        # Skip if no original text
        if not problem.get('text') or not problem['text'].strip():
            print(f"{progress} ⊘ Skipping (no original text)")
            skipped += 1
            continue
        
        # Skip if no answer
        if not problem.get('answer'):
            print(f"{progress} ⊘ Skipping (no answer)")
            skipped += 1
            continue
        
        # Analyze answer format (for logging)
        answer_format = analyze_answer_format(problem.get('answer'))
        print(f"{progress}    Answer format: {answer_format}")
        
        try:
            # Rephrase the problem
            rephrased = rephrase_problem(
                original_text=problem['text'],
                answer=problem.get('answer'),
                source=problem.get('source'),
                difficulty=problem.get('difficulty')
            )
            
            if rephrased:
                # Show preview
                preview = rephrased[:150].replace('\n', ' ')
                print(f"{progress}    Preview: {preview}...")
                
                # Save to ai_rephrased table
                success = save_ai_rephrase(problem_id, rephrased, dry_run)
                
                if success:
                    processed += 1
                    if dry_run:
                        print(f"{progress} ✓ Would save to ai_rephrased table (dry run mode)")
                    else:
                        print(f"{progress} ✓ Successfully saved to ai_rephrased table")
                else:
                    errors += 1
                    print(f"{progress} ✗ Error saving to database")
            else:
                errors += 1
                print(f"{progress} ✗ Failed to rephrase")
            
            # Rate limiting: wait 1 second between requests
            if i < len(problems) - 1:
                time.sleep(1)
            
            # Checkpoint every batch_size problems
            if (i + 1) % batch_size == 0:
                print(f"\n{'─'*70}")
                print(f"CHECKPOINT: {i+1}/{len(problems)} problems processed")
                print(f"✓ Success: {processed} | ✗ Errors: {errors} | ⊘ Skipped: {skipped}")
                print(f"{'─'*70}\n")
        
        except Exception as e:
            print(f"{progress} ✗ Unexpected error: {e}")
            errors += 1
    
    # Final summary
    print("\n" + "="*70)
    print("PROCESSING COMPLETE")
    print("="*70)
    print(f"✓ Successfully processed: {processed}")
    print(f"✗ Errors: {errors}")
    print(f"⊘ Skipped: {skipped}")
    print(f"Total: {processed + errors + skipped}")
    
    # Estimate cost
    avg_input_tokens = 250
    avg_output_tokens = 300
    total_input_tokens = (processed + errors) * avg_input_tokens
    total_output_tokens = processed * avg_output_tokens
    input_cost = (total_input_tokens / 1_000_000) * 3
    output_cost = (total_output_tokens / 1_000_000) * 15
    total_cost = input_cost + output_cost
    
    print(f"\nEstimated cost: ${total_cost:.2f}")
    print(f"  Input:  ${input_cost:.2f} ({total_input_tokens:,} tokens)")
    print(f"  Output: ${output_cost:.2f} ({total_output_tokens:,} tokens)")
    print("="*70 + "\n")

def main():
    """Main entry point with command line argument parsing"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Batch rephrase problems for AIME format using Claude Sonnet 4.5'
    )
    parser.add_argument('--test', action='store_true',
                       help='Test mode: only process first 10 problems')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run: show what would be done without saving')
    parser.add_argument('--start-from', type=int, metavar='ID',
                       help='Resume from specific problem ID')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Checkpoint interval (default: 50)')
    parser.add_argument('--only-reviewed', action='store_true',
                       help='Only process manually reviewed problems')
    parser.add_argument('--all-problems', action='store_true',
                       help='Process all problems, even without answers')
    parser.add_argument('--reprocess', action='store_true',
                       help='Reprocess problems even if they have AI rephrases')
    parser.add_argument('--limit', type=int, metavar='N',
                       help='Process N unrephrased problems (limit applied AFTER filtering existing)')
    
    args = parser.parse_args()
    
    # Run the batch process
    process_problems(
        batch_size=args.batch_size,
        start_from_id=args.start_from,
        only_reviewed=args.only_reviewed,
        only_with_answers=not args.all_problems,
        test_mode=args.test,
        dry_run=args.dry_run,
        skip_existing=not args.reprocess,
        limit=args.limit
    )

if __name__ == '__main__':
    main()