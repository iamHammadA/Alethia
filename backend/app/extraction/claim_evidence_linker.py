import json
from pathlib import Path
from .ai_evidence_analyzer import evidence_main

def linker():
    CURRENT_FILE = Path(__file__).resolve()
    ROOT_DIR = next(
        (p for p in CURRENT_FILE.parents if p.name.lower() == "alethia"),
        CURRENT_FILE.parent,
    )

    SAVE_DIR = ROOT_DIR / "arXiv papers"
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    json_evidence_path = SAVE_DIR / "analyzed_evidences.json"

    with open(json_evidence_path, "r", encoding="utf-8") as file:
        evidence_data = json.load(file) 

    claim_evidence_final = {}

    for articles, claims_list in evidence_data.items():
        cl_evid = []
        for item in claims_list:
            evidence_analyses = item.get("evidence_analysis", [])
            
            for current_evidence in evidence_analyses:
                if current_evidence.get("similarity", 0) < 0.1:
                    continue
                if current_evidence.get("relationship") != "supports":
                    continue
                if current_evidence.get("strength", 0) < 0.3:
                    continue
                    
                cl_evid.append({
                    "sentence": current_evidence["sentence"],
                    "similarity": current_evidence["similarity"],
                    "relationship": current_evidence["relationship"],
                    "strength": current_evidence["strength"],
                    "reason": current_evidence["reason"]
                })
                
        claim_evidence_final[articles] = cl_evid

    print(claim_evidence_final)

    output_path = SAVE_DIR / "final_evidences.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(claim_evidence_final, f, indent=2, ensure_ascii=False)

# print("Done")

evidence_main()