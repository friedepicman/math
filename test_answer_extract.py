#!/usr/bin/env python3
"""
Test extraction on a single file to debug
"""

import os
import json
from pathlib import Path
import anthropic

client = anthropic.Anthropic()

# Read the test file
md_path = Path("mathpix_output/hmmt_pdfs/HMMT_February_2008_Geometry_Solutions.md")
with open(md_path, 'r', encoding='utf-8') as f:
    content = f.read()

system_prompt = """You extract answers from math competition solution documents.

For each problem, extract the problem number and its final answer in LaTeX format.

Output format - one JSON object per line (JSONL):
{"num": "1", "answer": "42"}
{"num": "2", "answer": "\\frac{5}{3}"}

Rules:
- "num" is the problem number as shown in the document
- "answer" is the final answer in LaTeX, exactly as written
- Extract ONLY the final answer, not intermediate steps
- If a problem has no clear answer, skip it
- Output ONLY the JSONL lines, no other text
- Extract ALL problems - there are usually 10 problems per file"""

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=8192,
    system=system_prompt,
    messages=[{"role": "user", "content": f"Extract ALL answers from this document. Make sure to get every problem:\n\n{content}"}],
)

print(response.content[0].text)