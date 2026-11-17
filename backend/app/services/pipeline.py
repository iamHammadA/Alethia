"""Orchestrates Alethia's existing research modules for the web API."""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger("alethia.pipeline")
Progress = Callable[[str, int, str], None]


def run_research(topic: str, max_results: int = 5, progress: Progress | None = None) -> dict:
    def update(stage: str, percent: int, message: str) -> None:
        if progress:
            progress(stage, percent, message)
        logger.info("[%s%%] %s", percent, message)

    update("retrieval", 5, f"Searching arXiv for “{topic}”")
    download = importlib.import_module("backend.app.search.arxiv.download")
    download = importlib.reload(download)
    papers = download.get_data(topic, max_results=max_results, progress=update)

    # Reload in dependency order so a second investigation in the same server
    # process uses the newly downloaded papers, not module-level cached claims.
    update("papers", 20, f"Downloaded {len(papers)} papers. Metadata and PDFs are saved.")
    update("claims", 24, "Extracting and normalizing scientific claims.")
    claim_extractor = importlib.import_module("backend.app.extraction.claim_extractor")
    importlib.reload(claim_extractor)
    claim_normalizer = importlib.import_module("backend.app.extraction.claim_normalizer")
    importlib.reload(claim_normalizer)
    claim_analyzer = importlib.import_module("backend.app.extraction.ai_claim_analyzer")
    importlib.reload(claim_analyzer)

    evidence_retriever = importlib.import_module("backend.app.extraction.evidence_retriever")
    evidence_retriever = importlib.reload(evidence_retriever)
    evidence_retriever.main(progress=update)

    update("evidence", 60, "Candidate evidence retrieved. Running local LLM evidence analysis.")
    evidence_analyzer = importlib.import_module("backend.app.extraction.ai_evidence_analyzer")
    evidence_analyzer = importlib.reload(evidence_analyzer)
    evidence_analyzer.evidence_main(progress=update)

    update("linking", 78, "Linking evidence to claims and preserving source relationships.")
    linker = importlib.import_module("backend.app.extraction.claim_evidence_linker")
    linker = importlib.reload(linker)
    linker.linker()

    update("graph", 88, "Building the scientific knowledge graph and research insights.")
    graph_builder = importlib.import_module("backend.app.extraction.knowledge_graph_builder")
    graph_builder = importlib.reload(graph_builder)
    graph = graph_builder.main()

    report = {}
    if graph_builder.REPORT_PATH.exists():
        import json
        report = json.loads(graph_builder.REPORT_PATH.read_text(encoding="utf-8"))

    update("complete", 100, "Investigation completed.")
    return {
        "topic": topic,
        "papers_downloaded": len(papers),
        "paper_titles": [paper.get("title", "") for paper in papers],
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "analysis_mode": "dummy" if __import__("os").getenv("ALETHIA_DUMMY_AI", "0").lower() in {"1", "true", "yes", "on"} else "automatic_fallback",
        "report": report,
    }



def resume_existing_research(progress: Progress | None = None) -> dict:
    """Continue from saved metadata, PDFs, and claims without re-downloading or re-extracting."""
    def update(stage: str, percent: int, message: str) -> None:
        if progress:
            progress(stage, percent, message)
        logger.info("[%s%%] %s", percent, message)

    current_file = Path(__file__).resolve()
    root_dir = next(
        (parent for parent in current_file.parents
         if (parent / "backend").is_dir() and (parent / "frontend").is_dir()),
        None,
    )
    if root_dir is None:
        raise RuntimeError("Could not locate the Alethia project root.")

    data_dir = root_dir / "arXiv papers"
    metadata_path = data_dir / "paper_metadata.json"
    claims_path = data_dir / "ai_claims.json"
    if not metadata_path.exists() or not claims_path.exists():
        raise FileNotFoundError("Resume requires saved paper_metadata.json and ai_claims.json files.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    claims_by_article = json.loads(claims_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("No saved paper metadata was found.")
    if not isinstance(claims_by_article, dict) or not claims_by_article:
        raise ValueError("No saved scientific claims were found.")

    article_keys = list(metadata.keys())
    missing = [key for key in article_keys if not isinstance(claims_by_article.get(key), list)]
    if missing:
        raise ValueError("Saved claims are missing for: " + ", ".join(missing))

    pdf_files = sorted(data_dir.glob("*.pdf"))
    if len(pdf_files) < len(article_keys):
        raise FileNotFoundError(
            f"Found {len(pdf_files)} PDFs for {len(article_keys)} saved papers. Restore missing PDFs first."
        )

    claim_count = sum(len(claims_by_article[key]) for key in article_keys)
    update("claims", 28, f"Loaded {claim_count} saved claims from {len(article_keys)} papers. Claim extraction skipped.")

    evidence_retriever = importlib.import_module("backend.app.extraction.evidence_retriever")
    evidence_retriever = importlib.reload(evidence_retriever)
    evidence_retriever.main(
        progress=update,
        claims_by_article=claims_by_article,
        include_all_claims=True,
    )

    update("evidence", 60, "Retrieved passages from saved PDFs. Running explicitly simulated evidence classification.")
    evidence_analyzer = importlib.import_module("backend.app.extraction.ai_evidence_analyzer")
    evidence_analyzer = importlib.reload(evidence_analyzer)
    evidence_analyzer.evidence_main(progress=update, force_dummy=True)

    update("linking", 78, "Linking retrieved passages to the saved claims.")
    linker = importlib.import_module("backend.app.extraction.claim_evidence_linker")
    linker = importlib.reload(linker)
    linker.linker()

    update("graph", 88, "Rebuilding the knowledge graph from saved research.")
    graph_builder = importlib.import_module("backend.app.extraction.knowledge_graph_builder")
    graph_builder = importlib.reload(graph_builder)
    graph = graph_builder.main()

    report = {}
    if graph_builder.REPORT_PATH.exists():
        report = json.loads(graph_builder.REPORT_PATH.read_text(encoding="utf-8"))

    titles = [
        str(metadata[key].get("title", key))
        for key in article_keys
        if isinstance(metadata.get(key), dict)
    ]
    topic = titles[0] if titles else "Resumed saved research"
    update("complete", 100, "Saved research resumed. Evidence retrieval and graph rebuilding completed.")
    return {
        "topic": topic,
        "papers_downloaded": len(article_keys),
        "paper_titles": titles,
        "claims_loaded": claim_count,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "analysis_mode": "simulated",
        "report": report,
    }
