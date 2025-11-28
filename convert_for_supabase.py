import pandas as pd

# Load the typed CSV (which already works fine)
df = pd.read_csv("maa_problems_typed.csv")
print(f"Loaded {len(df)} problems")

# Build output with Supabase columns
out = pd.DataFrame()
out['text'] = df['text']
out['difficulty'] = df['difficulty']
out['source'] = df['source']
out['link'] = df['link']
out['answer'] = df['answer']

# Fix aime_answer - convert to int string
out['aime_answer'] = df['aime_answer'].apply(
    lambda x: str(int(float(x))) if pd.notna(x) and str(x).strip() != '' else ''
)

out['year'] = df['year'].astype(int)
out['title'] = df['source']
out['answer_type'] = df['contest'].apply(
    lambda x: "positive integer <= 1000" if x == "AIME" else "multiple choice"
)
out['solution'] = df['solution'].fillna('')
out['manually_reviewed'] = True
out['bad_problem'] = False
out['quality'] = 5
out['rewritten_problem'] = ''
out['finalized'] = True
out['type'] = df['type']

# Add IDs starting from 10000
out.insert(0, 'id', range(10000, 10000 + len(out)))

# Save - same way maa_problems_typed.csv was saved
out.to_csv("maa_for_supabase.csv", index=False)
print(f"Saved {len(out)} problems to maa_for_supabase.csv")