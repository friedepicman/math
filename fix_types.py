import pandas as pd
import numpy as np

df = pd.read_csv("maa_problems_typed.csv")

# Fix aime_answer - convert float to int, handle NaN
if 'aime_answer' in df.columns:
    df['aime_answer'] = df['aime_answer'].apply(
        lambda x: int(x) if pd.notna(x) and x != '' else None
    )

# Fix any other float columns that should be int
if 'year' in df.columns:
    df['year'] = df['year'].astype(int)

if 'problem_num' in df.columns:
    df['problem_num'] = df['problem_num'].astype(int)

# Make sure difficulty stays as float (that's probably fine)
# df['difficulty'] is okay as float

# Save
df.to_csv("maa_problems_fixed.csv", index=False)
print(f"Saved {len(df)} problems to maa_problems_fixed.csv")

# Show sample of aime_answer values
print("\nSample aime_answer values:")
print(df[df['aime_answer'].notna()]['aime_answer'].head(10))