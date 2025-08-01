import json
import re

# === Difficulty mappings ===
difficulty_map = {
    "Algebra": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "Geometry": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "NT": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "Discrete": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "Combinatorics": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "Analysis": {i: d for i, d in enumerate([1.5, 2, 2.5, 3, 3.5, 4, 5, 5.5, 6, 7], 1)},
    "Team": {i: d for i, d in enumerate(
        [1.5, 2, 2.5, 3, 3, 3.5, 4, 4.5, 5, 5, 5.5, 6, 6.5, 7, 7.5], 1)},
    "Team-20": {i: d for i, d in enumerate(
        [2, 2, 2.5, 2.5, 2.5, 3, 3.5, 4, 4, 4.5, 4.5, 4.5, 4.5, 5, 5, 5.5, 6, 6.5, 7, 7.5], 1)},
    "Guts": {
        1: 1.5, 2: 2, 3: 2.5, 4: 2, 5: 2.5, 6: 3, 7: 3, 8: 3.5, 9: 4, 10: 3.5,
        11: 4, 12: 4.5, 13: 4, 14: 4.5, 15: 5, 16: 5, 17: 5.5, 18: 6, 19: 5.5,
        20: 6, 21: 6.5, 22: 6, 23: 6.5, 24: 7, 25: 6.5, 26: 7, 27: 7.5
    },
    "General": {
        **{i: 1 for i in range(1, 6)},
        **{i: 1.5 for i in range(6, 10)},
        **{i: 2 for i in range(10, 13)},
        **{i: 2.5 for i in range(13, 15)},
        **{i: 3 for i in range(15, 18)},
        **{i: 3.5 for i in range(18, 20)},
        20: 4, 21: 4.5, 22: 5, 23: 5.5, 24: 6, 25: 6.5
    },
    "General Tiebreaker": {1: 1.5, 2: 3, 3: 3.5, 4: 4, 5: 4.5},
    "Algebra Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
    "Geometry Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
    "NT Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
    "Discrete Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
    "Combinatorics Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
    "Analysis Tiebreaker": {1: 1.5, 2: 3, 3: 4.5},
}

keywords = [
    "Algebra", "Geometry", "Number Theory", "NT", "Discrete", "Combinatorics",
    "Analysis", "Team", "Guts", "General"
]

aliases = {
    "Number Theory": "NT",
    "Team Round": "Team",
    "Individual": "General"
}

def parse_bmt_subject_and_number(source, title):
    if "BMT" not in source:
        return None, None

    text = source.split("same as")[0].strip()
    tokens = text.split()
    subject, number = None, None

    # Lowercase keyword support
    lower_keywords = [k.lower() for k in keywords]
    lower_aliases = {k.lower(): v for k, v in aliases.items()}

    for i, word in enumerate(tokens):
        word_lower = word.lower()
        normalized = lower_aliases.get(word_lower, word_lower)
        if normalized.lower() in lower_keywords:
            subject = normalized.capitalize()
            for j in range(i + 1, min(i + 4, len(tokens))):
                m = re.search(r"(?:#|P)?(\d+)", tokens[j])
                if m:
                    number = int(m.group(1))
                    break
            break

    if subject is None or number is None:
        m = re.search(r"(Algebra|Geometry|Number Theory|NT|Discrete|Combinatorics|Analysis|Team|Individual|General).*?(?:#|P)?(\d+)", title, re.IGNORECASE)
        if m:
            subject = aliases.get(m.group(1), m.group(1))
            subject = subject.capitalize()
            number = int(m.group(2))

    if subject is None or number is None:
        return None, None

    if re.search(r"tie", text, re.IGNORECASE):
        subject += " Tiebreaker"

    year_match = re.search(r"20\d{2}", text)
    year = int(year_match.group()) if year_match else None

    if subject == "Team":
        if year == 2020:
            subject = "Guts"
        elif year in (2014, 2015):
            subject = "Team-20"

    return subject, number

# === Load and log to file ===

with open("all_problems_with_all_difficulties.json") as f:
    problems = json.load(f)

output_lines = ["📊 Assigned Difficulties for BMT Problems:\n"]

for prob in problems:
    source = prob.get("source", "")
    if "BMT" not in source:
        continue

    subject, number = parse_bmt_subject_and_number(source, prob.get("title", ""))
    if subject and number:
        diff = difficulty_map.get(subject, {}).get(number)
        if diff is not None:
            output_lines.append(
                f"[{source}] {prob.get('title')} → subject={subject}, number={number} → difficulty = {diff}"
            )
        else:
            output_lines.append(
                f"[{source}] {prob.get('title')} → subject={subject}, number={number} → ❌ No difficulty found"
            )
    else:
        output_lines.append(
            f"[{source}] {prob.get('title')} → ❌ Failed to parse subject/number"
        )

with open("bmt_difficulty_assignments.txt", "w") as f:
    f.write("\n".join(output_lines))

print("✅ Difficulty assignments written to bmt_difficulty_assignments.txt")
