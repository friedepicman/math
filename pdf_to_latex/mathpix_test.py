#!/usr/bin/env python3
"""
Mathpix API Test

Tests the Mathpix API with a single PDF to verify your credentials work
and see what the LaTeX output looks like.

Usage:
    1. Get your API credentials from https://mathpix.com/ocr
    2. Set your credentials below or as environment variables
    3. Run: python mathpix_test.py path/to/your.pdf
"""

import os
import sys
import time
import requests
import json

# ============================================================================
# CONFIGURATION - Set your credentials here or use environment variables
# ============================================================================

APP_ID = os.environ.get("MATHPIX_APP_ID", "YOUR_APP_ID_HERE")
APP_KEY = os.environ.get("MATHPIX_APP_KEY", "YOUR_APP_KEY_HERE")

# ============================================================================
# API FUNCTIONS
# ============================================================================

def upload_pdf(pdf_path: str) -> dict:
    """Upload a PDF to Mathpix and start conversion."""
    
    headers = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
    }
    
    options = {
        "conversion_formats": {
            "tex.zip": True,    # Full LaTeX with images
            "md": True,         # Markdown (for quick preview)
        },
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
    }
    
    with open(pdf_path, "rb") as f:
        response = requests.post(
            "https://api.mathpix.com/v3/pdf",
            headers=headers,
            files={"file": f},
            data={"options_json": json.dumps(options)},
            timeout=60,
        )
    
    if response.status_code != 200:
        print(f"Error uploading PDF: {response.status_code}")
        print(response.text)
        sys.exit(1)
    
    return response.json()


def check_status(pdf_id: str) -> dict:
    """Check the conversion status of a PDF."""
    
    headers = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
    }
    
    response = requests.get(
        f"https://api.mathpix.com/v3/pdf/{pdf_id}",
        headers=headers,
        timeout=30,
    )
    
    return response.json()


def get_result(pdf_id: str, format: str = "md") -> str:
    """Download the converted result."""
    
    headers = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
    }
    
    response = requests.get(
        f"https://api.mathpix.com/v3/pdf/{pdf_id}.{format}",
        headers=headers,
        timeout=60,
    )
    
    return response.text


def download_tex_zip(pdf_id: str, output_path: str):
    """Download the LaTeX zip file."""
    
    headers = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
    }
    
    response = requests.get(
        f"https://api.mathpix.com/v3/pdf/{pdf_id}.tex.zip",
        headers=headers,
        timeout=60,
    )
    
    with open(output_path, "wb") as f:
        f.write(response.content)
    
    return output_path


# ============================================================================
# MAIN
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python mathpix_test.py <path_to_pdf>")
        print("\nExample:")
        print("  python mathpix_test.py bmt_pdfs/BMT_2024_Algebra_Solutions.pdf")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    
    if APP_ID == "YOUR_APP_ID_HERE" or APP_KEY == "YOUR_APP_KEY_HERE":
        print("Error: Please set your Mathpix credentials!")
        print("\nOption 1: Edit this script and replace YOUR_APP_ID_HERE and YOUR_APP_KEY_HERE")
        print("\nOption 2: Set environment variables:")
        print("  export MATHPIX_APP_ID='your_app_id'")
        print("  export MATHPIX_APP_KEY='your_app_key'")
        print("\nGet credentials at: https://mathpix.com/ocr")
        sys.exit(1)
    
    print(f"Testing Mathpix API with: {pdf_path}")
    print("="*60)
    
    # Upload
    print("\n1. Uploading PDF...")
    result = upload_pdf(pdf_path)
    pdf_id = result.get("pdf_id")
    print(f"   PDF ID: {pdf_id}")
    
    # Poll for completion
    print("\n2. Waiting for conversion...")
    while True:
        status = check_status(pdf_id)
        state = status.get("status")
        percent = status.get("percent_done", 0)
        
        print(f"   Status: {state} ({percent}%)")
        
        if state == "completed":
            break
        elif state == "error":
            print(f"   Error: {status.get('error')}")
            sys.exit(1)
        
        time.sleep(2)
    
    # Get markdown preview
    print("\n3. Fetching results...")
    md_content = get_result(pdf_id, "md")
    
    # Save markdown preview
    md_output = pdf_path.replace(".pdf", "_mathpix.md")
    with open(md_output, "w") as f:
        f.write(md_content)
    print(f"   Markdown saved to: {md_output}")
    
    # Download LaTeX zip
    tex_output = pdf_path.replace(".pdf", "_mathpix.tex.zip")
    download_tex_zip(pdf_id, tex_output)
    print(f"   LaTeX zip saved to: {tex_output}")
    
    # Show preview
    print("\n" + "="*60)
    print("FULL MARKDOWN OUTPUT:")
    print("="*60)
    print(md_content)
    
    print("\n" + "="*60)
    print("SUCCESS! Check the output files:")
    print(f"  - {md_output} (markdown preview)")
    print(f"  - {tex_output} (full LaTeX source)")


if __name__ == "__main__":
    main()