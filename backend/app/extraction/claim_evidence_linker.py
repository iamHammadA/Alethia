import json
from pathlib import Path


def linker():
    current_file = Path(__file__).resolve()
    root_dir = next(
        (p for p in current_file.parents
         if (p / "backend").is_dir() and (p / "frontend").is_dir()),
        None,
    )
    if root_dir is None:
        raise RuntimeError("Could not locate the Alethia project root.")
    save_dir = root_dir / "arXiv papers"
    input_path = save_dir / "analyzed_evidences.json"
    if not input_path.exists():
        raise FileNotFoundError(f"Evidence analysis output not found: {input_path}")
    with input_path.open("r", encoding="utf-8") as file:
        evidence_data = json.load(file)

    claim_evidence_final = {}
    for article, claims_list in evidence_data.items():
        article_links = []
        for item in claims_list:
            linked = []
            for evidence in item.get("evidence_analysis", []):
                # Keep every classified candidate, including insufficient and
                # simulated records. The UI can distinguish them by provenance.
                linked.append({
                    "sentence": evidence.get("sentence", ""),
                    "similarity": evidence.get("similarity", 0),
                    "relationship": evidence.get("relationship", "insufficient"),
                    "strength": evidence.get("strength", 0),
                    "reason": evidence.get("reason", ""),
                    "analysis_mode": evidence.get("analysis_mode", item.get("analysis_mode", "unknown")),
                })
            article_links.append(linked)
        claim_evidence_final[article] = article_links

    output_path = save_dir / "final_evidences.json"
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(claim_evidence_final, file, indent=2, ensure_ascii=False)
    return claim_evidence_final
