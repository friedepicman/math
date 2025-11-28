import pandas as pd
import re

# Load the scraped data
df = pd.read_csv("/Users/jasonyuan/Documents/git/math/maa_problems_scraped.csv")
print(f"Before dedup: {len(df)} problems")

# Group by problem text and merge sources
def merge_rows(group):
    """Merge duplicate rows, combining sources."""
    if len(group) == 1:
        return group.iloc[0]
    
    # Take the first row as base
    merged = group.iloc[0].copy()
    
    # Collect all unique sources
    sources = []
    for _, row in group.iterrows():
        src = row['source']
        if pd.notna(src) and src not in sources:
            sources.append(src)
    
    # Sort sources so AMC 10 comes before AMC 12
    def sort_key(s):
        # Extract contest number and problem number for sorting
        match = re.search(r'AMC\s*(\d+)', s)
        contest_num = int(match.group(1)) if match else 99
        return contest_num
    
    sources.sort(key=sort_key)
    
    # Merge sources with " / " - but make it more compact for duplicates
    # e.g., "2007 AMC 10A #13 / 12A #9" instead of "2007 AMC 10A #13 / 2007 AMC 12A #9"
    if len(sources) > 1:
        # Check if they're from the same year
        years = set()
        for s in sources:
            year_match = re.match(r'(\d{4})', s)
            if year_match:
                years.add(year_match.group(1))
        
        if len(years) == 1:
            # Same year - compact format
            year = list(years)[0]
            compact_sources = []
            for i, s in enumerate(sources):
                if i == 0:
                    compact_sources.append(s)
                else:
                    # Remove year prefix for subsequent sources
                    compact = re.sub(r'^\d{4}\s+AMC\s+', '', s)
                    compact_sources.append(compact)
            merged['source'] = ' / '.join(compact_sources)
        else:
            # Different years - full format
            merged['source'] = ' / '.join(sources)
    
    return merged

# Group by text and merge
df_deduped = df.groupby('text', as_index=False).apply(merge_rows, include_groups=False).reset_index(drop=True)

print(f"After dedup: {len(df_deduped)} problems")
print(f"Removed {len(df) - len(df_deduped)} duplicates")

# Show some examples of merged sources
merged_examples = df_deduped[df_deduped['source'].str.contains(' / ', na=False)].head(10)
print(f"\nExamples of merged sources:")
for _, row in merged_examples.iterrows():
    print(f"  {row['source']}")

# Save
df_deduped.to_csv("maa_problems_deduped.csv", index=False)
print(f"\nSaved to maa_problems_deduped.csv")