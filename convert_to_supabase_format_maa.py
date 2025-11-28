import pandas as pd

df = pd.read_csv("maa_problems_typed.csv")

# Create Supabase-compatible dataframe
out = pd.DataFrame({
    "text": df["text"],
    "difficulty": df["difficulty"],
    "source": df["source"],
    "link": df["link"],
    "answer": df["answer"],
    "aime_answer": df["aime_answer"],
    "year": df["year"],
    "title": df["source"],  # Use source as title
    "answer_type": df.apply(lambda r: "positive integer <= 1000" if r["contest"] == "AIME" else "multiple choice", axis=1),
    "solution": df["solution"],
    "manually_reviewed": True,
    "bad_problem": False,
    "quality": 5,
    "rewritten_problem": "",
    "finalized": True,
    "type": df["type"]
})

out.to_csv("maa_for_supabase.csv", index=False)
print(f"Saved {len(out)} problems to maa_for_supabase.csv")