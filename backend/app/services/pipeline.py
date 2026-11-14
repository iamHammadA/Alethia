"""Orchestrates Alethia's existing research modules for the web API."""
from __future__ import annotations

import importlib
import logging
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
    papers = download.get_data(topic, max_results=max_results)

    # Reload in dependency order so a second investigation in the same server
    # process uses the newly downloaded papers, not module-level cached claims.
    update("claims", 22, f"Downloaded {len(papers)} papers. Extracting scientific claims.")
    claim_extractor = importlib.import_module("backend.app.extraction.claim_extractor")
    importlib.reload(claim_extractor)
    claim_normalizer = importlib.import_module("backend.app.extraction.claim_normalizer")
    importlib.reload(claim_normalizer)
    claim_analyzer = importlib.import_module("backend.app.extraction.ai_claim_analyzer")
    importlib.reload(claim_analyzer)

    evidence_retriever = importlib.import_module("backend.app.extraction.evidence_retriever")
    evidence_retriever = importlib.reload(evidence_retriever)
    evidence_retriever.main()

    update("evidence", 58, "Candidate evidence retrieved. Running local LLM evidence analysis.")
    evidence_analyzer = importlib.import_module("backend.app.extraction.ai_evidence_analyzer")
    evidence_analyzer = importlib.reload(evidence_analyzer)
    evidence_analyzer.evidence_main()

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
        "report": report,
    }
