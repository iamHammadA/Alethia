import json
from pathlib import Path
import nltk
import pymupdf4llm
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ai_claim_analyzer import analyzer

nltk.download("punkt", quiet=True)


def extract_claim_and_original(claim_item):
    """Extracts claim text and source sentence from str or dict structures.

    Checks key schemas used across extraction pipelines (e.g., 'normalized_claim').
    """
    if isinstance(claim_item, str):
        return claim_item, claim_item

    if isinstance(claim_item, dict):
        claim_text = (
            claim_item.get("normalized_claim")
            or claim_item.get("claim")
            or claim_item.get("text")
            or claim_item.get("statement")
            or claim_item.get("extracted_claim")
            or ""
        )
        orig_sentence = (
            claim_item.get("original_sentence")
            or claim_item.get("source_sentence")
            or claim_item.get("sentence")
            or claim_item.get("raw_claim")
            or claim_text
        )
        return str(claim_text), str(orig_sentence)

    return str(claim_item), str(claim_item)


def retrieve_evidence(
    claim: str,
    paper_text: str,
    original_sentence: str = None,
    top_k: int = 3,
    similarity_threshold: float = 0.98,
):
    sentences = nltk.sent_tokenize(paper_text)

    if not sentences or not claim.strip():
        return []

    norm_claim = claim.strip().lower()
    norm_orig = original_sentence.strip().lower() if original_sentence else norm_claim

    documents = [claim] + sentences

    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        vectors = vectorizer.fit_transform(documents)
    except ValueError:
        return []

    scores = cosine_similarity(vectors[0:1], vectors[1:])[0]

    filtered_candidates = []
    for sentence, score in zip(sentences, scores):
        norm_sent = sentence.strip().lower()

        # Exclude exact matches against original sentence or claim
        if norm_sent == norm_claim or norm_sent == norm_orig:
            continue

        # Exclude near-identical duplicates
        if float(score) >= similarity_threshold:
            continue

        filtered_candidates.append((sentence, float(score)))

    ranked = sorted(filtered_candidates, key=lambda x: x[1], reverse=True)

    return [
        {"sentence": sentence, "similarity": round(score, 4)}
        for sentence, score in ranked[:top_k]
    ]


def process_all_papers(claims_by_article: dict, arxiv_dir: Path, top_k: int = 3):
    results = {}
    pdf_files = sorted(arxiv_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in directory: {arxiv_dir}")
        return results

    for idx, pdf_path in enumerate(pdf_files):
        article_key = f"article{idx}"

        claims = claims_by_article.get(article_key, [])
        if not claims:
            claims = claims_by_article.get(pdf_path.name, [])

        if not claims:
            print(f"Skipping {pdf_path.name}: No claims found for '{article_key}'")
            continue

        print(f"Processing {pdf_path.name} ({len(claims)} claims)...")

        try:
            paper_text = pymupdf4llm.to_markdown(str(pdf_path))
        except Exception as e:
            print(f"Error reading {pdf_path.name}: {e}")
            continue

        article_evidence = []
        for claim_item in claims:
            # Skip claims marked as not requiring evidence or low confidence
            if isinstance(claim_item, dict):
                if not claim_item.get("requires_evidence", True):
                    continue
                if claim_item.get("confidence", 1.0) < 0.4:
                    continue

            claim_text, orig_sentence = extract_claim_and_original(claim_item)

            if not claim_text.strip():
                print(f"Warning: Found empty claim item in {article_key}: {claim_item}")
                continue

            matches = retrieve_evidence(
                claim=claim_text,
                paper_text=paper_text,
                original_sentence=orig_sentence,
                top_k=top_k,
            )

            article_evidence.append({
                "claim": claim_text,
                "evidence_candidates": matches
            })

        results[article_key] = {
            "file": pdf_path.name,
            "claims_analyzed": article_evidence
        }

    return results


def main():
    CURRENT_FILE = Path(__file__).resolve()

    ROOT_DIR = next(
        (p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"),
        CURRENT_FILE.parent,
    )

    SAVE_DIR = ROOT_DIR / "arXiv papers"

    claims_by_article = analyzer()

    # Debug check: verify claim structure if needed
    for key, val in claims_by_article.items():
        if val:
            print(f"Sample claim item for {key}: {val[0]} (Type: {type(val[0])})")
            break

    extracted_data = process_all_papers(claims_by_article, SAVE_DIR, top_k=3)

    output_path = SAVE_DIR / "matched_evidence.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=2)

    print(f"\nProcessing complete. Evidence saved to: {output_path}")


main()