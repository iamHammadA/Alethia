import json
import os
from pathlib import Path

import ollama


# --------------------------------------------------
# PATH CONFIGURATION
# --------------------------------------------------

CURRENT_FILE = Path(__file__).resolve()

ROOT_DIR = next(
    (p for p in CURRENT_FILE.parents if p.name.lower() == "alethia"),
    CURRENT_FILE.parent
)

SAVE_DIR = ROOT_DIR / "arXiv papers"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

INPUT_PATH = SAVE_DIR / "matched_evidence.json"
OUTPUT_PATH = SAVE_DIR / "analyzed_evidences.json"


# --------------------------------------------------
# MODEL CONFIGURATION
# --------------------------------------------------

MODEL = os.getenv("OLLAMA_EVIDENCE_MODEL", "llama3.2")


# --------------------------------------------------
# SYSTEM INSTRUCTION
# --------------------------------------------------

SYSTEM_INSTRUCTION = """
You are the Evidence Analysis module of Alethia,
an AI system for analyzing scientific research papers.

Your task is to determine whether candidate passages from a
scientific paper provide evidence for a specific scientific claim.

Evaluate the semantic relationship between the claim and
each candidate passage independently.

IMPORTANT RULES:

1. Never assume that a passage is evidence merely because
   it has a high similarity score.

2. Never invent information that is not present in the
   claim or candidate passage.

3. Do not use outside knowledge.

4. A candidate passage can have one of four relationships:

   - supports:
     The passage provides information that supports the claim.

   - contradicts:
     The passage provides information that conflicts with the claim.

   - insufficient:
     The passage is related to the claim but does not provide
     enough information to establish or evaluate it.

   - irrelevant:
     The passage does not provide useful evidence for evaluating
     the claim.

5. Evaluate EVERY candidate passage independently.

6. Determine evidence strength:

   - 0.0–0.2: No meaningful evidence
   - 0.2–0.4: Very weak evidence
   - 0.4–0.6: Moderate evidence
   - 0.6–0.8: Strong evidence
   - 0.8–1.0: Very strong evidence

7. Evidence strength measures how strongly the passage supports
   or contradicts the claim. It does not measure whether
   the claim itself is scientifically true.

8. A passage discussing the same topic is not necessarily evidence.

9. Direct experimental results, measurements, comparisons,
   observations, and theoretical derivations can provide strong
   evidence when relevant to the claim.

10. Select the strongest meaningful candidate as best_evidence.
    If no candidate provides meaningful evidence, use null.

11. Provide a short, specific explanation for every candidate.

12. Determine overall_relationship based on the complete
    collection of candidate passages.

13. Never classify a claim as supported merely because most
    candidates are topically similar.

14. Preserve the original candidate sentences and similarity
    scores exactly.

OUTPUT FORMAT:

Return ONLY a valid JSON object with this structure:

{
    "claim": "Original scientific claim",

    "evidence_analysis": [
        {
            "sentence": "Original candidate sentence",
            "similarity": 0.0,
            "relationship": "supports",
            "strength": 0.0,
            "reason": "Explanation"
        }
    ],

    "best_evidence": "Strongest evidence sentence or null",

    "overall_relationship": "supports",

    "overall_strength": 0.0
}

Allowed overall_relationship values:
supports, contradicts, insufficient, irrelevant.

All strength values must be between 0.0 and 1.0.

Return valid JSON only. No markdown or additional text.
"""


# --------------------------------------------------
# OUTPUT VALIDATION
# --------------------------------------------------

def validate_analysis(result, evidence_item):

    if not isinstance(result, dict):
        raise ValueError("Model output must be a JSON object.")

    required_fields = [
        "claim",
        "evidence_analysis",
        "best_evidence",
        "overall_relationship",
        "overall_strength"
    ]

    for field in required_fields:
        if field not in result:
            raise ValueError(f"Missing output field: {field}")

    valid_relationships = {
        "supports",
        "contradicts",
        "insufficient",
        "irrelevant"
    }

    if result["overall_relationship"] not in valid_relationships:
        raise ValueError("Invalid overall relationship.")

    def valid_score(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= value <= 1.0
        )

    if not valid_score(result["overall_strength"]):
        raise ValueError("Invalid overall strength.")

    if not isinstance(result["evidence_analysis"], list):
        raise ValueError("evidence_analysis must be a list.")

    for item in result["evidence_analysis"]:

        if not isinstance(item, dict):
            raise ValueError("Invalid evidence item.")

        for field in [
            "sentence",
            "similarity",
            "relationship",
            "strength",
            "reason"
        ]:
            if field not in item:
                raise ValueError(f"Missing evidence field: {field}")

        if item["relationship"] not in valid_relationships:
            raise ValueError("Invalid evidence relationship.")

        if not valid_score(item["strength"]):
            raise ValueError("Invalid evidence strength.")

        if not valid_score(item["similarity"]):
            raise ValueError("Invalid similarity score.")

    return result


# --------------------------------------------------
# EVIDENCE ANALYSIS
# --------------------------------------------------

def analyze_evidence(evidence_item):

    if isinstance(evidence_item, dict):
        input_payload = json.dumps(
            evidence_item,
            indent=2,
            ensure_ascii=False
        )
    else:
        input_payload = str(evidence_item)

    response = ollama.chat(
        model=MODEL,
        format="json",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_INSTRUCTION
            },
            {
                "role": "user",
                "content": (
                    "Analyze the following scientific claim "
                    "and its retrieved evidence candidates.\n\n"
                    f"INPUT:\n{input_payload}\n\n"
                    "Evaluate every candidate independently. "
                    "Return ONLY the required JSON."
                )
            }
        ],
        options={
            "temperature": 0.0
        }
    )

    raw_content = response["message"]["content"].strip()

    try:
        result = json.loads(raw_content)

    except json.JSONDecodeError as e:
        raise ValueError(
            f"Invalid JSON returned by {MODEL}: {raw_content}"
        ) from e

    return validate_analysis(result, evidence_item)


# --------------------------------------------------
# IMPORT MATCHED EVIDENCE
# --------------------------------------------------

def json_importer():

    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_PATH}"
        )

    with open(INPUT_PATH, "r", encoding="utf-8") as file:
        data = json.load(file)

    analysed_results = {}

    for article, evidence in data.items():

        evidences = []

        for index, evidence_item in enumerate(
            evidence.get("claims_analyzed", [])
        ):

            print(
                f"\nArticle: {article} | "
                f"Claim: {index + 1}"
            )

            current_evidence = analyze_evidence(evidence_item)

            evidences.append(current_evidence)

            print(
                "Relationship:",
                current_evidence["overall_relationship"]
            )

            print(
                "Strength:",
                current_evidence["overall_strength"]
            )

        analysed_results[article] = evidences

    return analysed_results


# --------------------------------------------------
# MAIN EVIDENCE ANALYSIS PIPELINE
# --------------------------------------------------

def evidence_main():

    data = json_importer()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    print("\nEvidence analysis completed.")

    print(f"Output saved to: {OUTPUT_PATH}")

    return data


# --------------------------------------------------
# EXECUTION
# --------------------------------------------------

if __name__ == "__main__":
    evidence_main()
