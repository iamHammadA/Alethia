import re
import json
import nltk
import os
from pathlib import Path
import sys
import ollama

# from evidence_retriever import main

def analyze_evidence(evidence_item):
    
    input_payload = (
        json.dumps(evidence_item, indent=2)
        if isinstance(evidence_item, dict)
        else evidence_item
    )

    response = ollama.chat(
        model="llama3.2",
        format="json",
        messages=[
            {"role": "system", "content": """You are the Evidence Analysis module of Alethia, an AI system for analyzing scientific research papers.

    Your task is to determine whether candidate passages from a scientific paper provide evidence for a specific claim.

    You must evaluate the semantic relationship between the claim and each candidate passage.

    IMPORTANT RULES:

    1. DO NOT assume that a passage is evidence merely because it has a high similarity score.

    2. DO NOT invent information that is not present in the claim or candidate passage.

    3. DO NOT use outside knowledge.

    4. A candidate passage can be:
    - "supports": The passage provides information that supports the claim.
    - "contradicts": The passage provides information that conflicts with the claim.
    - "insufficient": The passage is related to the claim but does not provide enough information to establish or evaluate it.
    - "irrelevant": The passage does not provide useful evidence for evaluating the claim.

    5. Evaluate EVERY candidate passage independently.

    6. Determine the strength of the evidence:
    - 0.0–0.2: no meaningful evidence
    - 0.2–0.4: very weak
    - 0.4–0.6: moderate
    - 0.6–0.8: strong
    - 0.8–1.0: very strong

    7. Evidence strength measures how strongly the passage supports or contradicts the claim.
    It does NOT measure whether the scientific claim itself is true.

    8. A passage that merely discusses the same topic is NOT necessarily evidence.

    9. A passage that directly reports an experimental result, measurement, comparison, observation, or theoretical derivation relevant to the claim can provide strong evidence.

    10. If the claim requires evidence but none of the candidate passages actually establish it, mark the overall relationship as "insufficient".

    11. Select the strongest candidate passage as "best_evidence".
    If no candidate provides meaningful evidence, set "best_evidence" to null.

    12. Give a short explanation for every candidate explaining why it supports, contradicts, is insufficient, or is irrelevant.

    INPUT:

    {
        "claim": "...",
        "evidence_candidates": [
            {
                "sentence": "...",
                "similarity": 0.0
            }
        ]
    }

    OUTPUT:

    Return ONLY valid JSON.

    {
        "claim": "...",
        "evidence_analysis": [
            {
                "sentence": "...",
                "similarity": 0.0,
                "relationship": "supports",
                "strength": 0.0,
                "reason": "..."
            }
        ],
        "best_evidence": "...",
        "overall_relationship": "supports",
        "overall_strength": 0.0
    }
    """},
            {"role": "user", "content": f"""
    Analyze the following scientific claim and its retrieved evidence candidates.

    INPUT:
    {evidence_item}

    Evaluate each candidate passage according to the instructions in the system prompt.

    Return ONLY the required JSON output.
    """},
        ],
        options={
            "temperature":0.0
        }
    )
    raw_content = response["message"]["content"].strip()
    return json.loads(raw_content)


CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next(
    (p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"),
    CURRENT_FILE.parent,
)

# 2. Target the 'arXiv papers' folder inside ALETHEIA
SAVE_DIR = ROOT_DIR / "arXiv papers"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def json_importer():
    json_file_path = SAVE_DIR / "matched_evidence.json"
    with open(json_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    analysed_results = {}
    for article, evidence in data.items():
        evidences = []
        for evidence_item in evidence["claims_analyzed"]:
            current_evidence = analyze_evidence(evidence_item)
            evidences.append(current_evidence)
            print(current_evidence)
        analysed_results[article] = evidences
    return analysed_results

def evidence_main():
    
    data = json_importer()
    CURRENT_FILE = Path(__file__).resolve()

    ROOT_DIR = next(
        (p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"),
        CURRENT_FILE.parent,
    )

    SAVE_DIR = ROOT_DIR / "arXiv papers"
    
    output_path = SAVE_DIR / "analyzed_evidences.json"
    with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
            
# main()
print(evidence_main())