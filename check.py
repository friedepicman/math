import csv
import random

with open('problems_database.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"Total rows: {len(rows)}")
print()

for row in random.sample(rows, 10):
    prob = row.get('problem', '')[:50].replace('\n', ' ')
    sol = row.get('solution', '')[:50].replace('\n', ' ')
    print(f"SRC: {row.get('source', '')}")
    print(f"  P: {prob}...")
    print(f"  S: {sol}...")
    print()