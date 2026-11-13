import json
from pathlib import Path


def linker():
    current_file = Path(__file__).resolve()
    root_dir = next(
        (p for p in current_file.parents if p.name.lower() == "alethia"),
        current_file.parent,
    )
    save_dir = root_dir / "arXiv papers"
    input_path = save_dir / "analyzed_evidences.json"
    if not input_path.exists():
        raise FileNotFoundError(f"Evidence analysis output not found: {input_path}")
    with input_path.open("r", encoding="utf-8") as file:
        evidence_data = json.load(file)

    claim_evidence_final = {}
    for article, claims_list in evidence_data.items():
        linked = []
        for item in claims_list:
            for evidence in item.get("evidence_analysis", []):
                if evidence.get("similarity", 0) < 0.1:
                    continue
                if evidence.get("relationship") != "supports":
                    continue
                if evidence.get("strength", 0) < 0.3:
                    continue
                linked.append({
                    "sentence": evidence.get("sentence", ""),
                    "similarity": evidence.get("similarity", 0),
                    "relationship": evidence.get("relationship", ""),
                    "strength": evidence.get("strength", 0),
                    "reason": evidence.get("reason", ""),
                })
        claim_evidence_final[article] = linked

    output_path = save_dir / "final_evidences.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(claim_evidence_final, file, indent=2, ensure_ascii=False)
    return claim_evidence_final
