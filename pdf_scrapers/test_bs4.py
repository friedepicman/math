import requests
import re

url = "https://artofproblemsolving.com/wiki/api.php"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

for page in ["2007 AMC 10A Problems/Problem 13", "2022 AMC 10B Problems/Problem 2"]:
    params = {
        "action": "query",
        "titles": page,
        "prop": "revisions",
        "rvprop": "content",
        "format": "json",
        "redirects": "1"
    }
    
    res = requests.get(url, params=params, headers=headers, timeout=15)
    data = res.json()
    
    print(f"\n=== {page} ===")
    
    # Check for redirects
    if "redirects" in data.get("query", {}):
        print(f"Redirects: {data['query']['redirects']}")
    
    # Get content
    pages = data.get("query", {}).get("pages", {})
    for page_id, page_data in pages.items():
        print(f"Page ID: {page_id}")
        if page_id == "-1":
            print("PAGE DOES NOT EXIST")
            continue
        revisions = page_data.get("revisions", [])
        if revisions:
            content = revisions[0].get("*", "")
            print(f"Content length: {len(content)}")
            print(f"First 500 chars:\n{content[:500]}")
            
            # Test the regex
            match = re.search(r'==\s*Problem(?:\s+\d+)?\s*==\s*(.*?)(?=\n==|$)', content, re.DOTALL | re.IGNORECASE)
            if match:
                print(f"\nRegex matched! Extracted: {match.group(1)[:200]}...")
            else:
                print("\nRegex DID NOT match!")