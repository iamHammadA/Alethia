from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "arXiv papers"
GRAPH_DIR = DATA_DIR / "knowledge_graph"
GRAPH_PATH = GRAPH_DIR / "alethia_knowledge_graph.json"
REPORT_PATH = GRAPH_DIR / "build_report.json"
INSIGHTS_PATH = GRAPH_DIR / "research_insights.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alethia.api")

app = FastAPI(
    title="Alethia API",
    description="Research literature analysis and scientific knowledge graph API.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
PIPELINE_LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def graph_data() -> dict:
    return read_json(GRAPH_PATH, {"graph": {}, "nodes": [], "edges": []})


def build_indexes(data: dict) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    nodes = {node.get("id"): node for node in data.get("nodes", []) if node.get("id")}
    evidence_by_claim: dict[str, list[dict]] = {}
    for edge in data.get("edges", []):
        rel = str(edge.get("relationship", "")).upper()
        if rel in {"SUPPORTS", "CONTRADICTS", "INSUFFICIENT", "IRRELEVANT"}:
            source, target = edge.get("source"), edge.get("target")
            if nodes.get(source, {}).get("node_type") == "evidence":
                evidence_id, claim_id = source, target
            else:
                evidence_id, claim_id = target, source
            evidence = nodes.get(evidence_id)
            if evidence and nodes.get(claim_id, {}).get("node_type") == "claim":
                evidence_by_claim.setdefault(claim_id, []).append({**evidence, "relationship": rel.lower()})
    return nodes, evidence_by_claim


def dashboard_payload() -> dict:
    data = graph_data()
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    report = read_json(REPORT_PATH, {})
    insights = read_json(INSIGHTS_PATH, {})
    by_type: dict[str, int] = {}
    for node in nodes:
        kind = node.get("node_type", "other")
        by_type[kind] = by_type.get(kind, 0) + 1
    papers = [node for node in nodes if node.get("node_type") == "paper"]
    claims = [node for node in nodes if node.get("node_type") == "claim"]
    evidence = [node for node in nodes if node.get("node_type") == "evidence"]
    supported = sum(1 for edge in edges if str(edge.get("relationship", "")).upper() == "SUPPORTS")
    return {
        "available": GRAPH_PATH.exists(),
        "stats": {
            "papers": len(papers) or report.get("papers_created", 0),
            "claims": len(claims) or report.get("claims_created", 0),
            "evidence": len(evidence) or report.get("evidence_created", 0),
            "relationships": len(edges) or report.get("total_edges", 0),
            "supported_links": supported,
        },
        "node_types": by_type,
        "papers": papers[:6],
        "insights": insights,
        "report": report,
        "updated_at": datetime.fromtimestamp(GRAPH_PATH.stat().st_mtime, timezone.utc).isoformat() if GRAPH_PATH.exists() else None,
    }


class ResearchRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    max_results: int = Field(default=5, ge=1, le=10)


def update_job(job_id: str, **values: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values, updated_at=now())


def run_job(job_id: str, topic: str, max_results: int) -> None:
    if not PIPELINE_LOCK.acquire(blocking=False):
        update_job(job_id, status="failed", error="Another research pipeline is already running. Please try again when it finishes.", completed_at=now())
        return
    try:
        update_job(job_id, status="running", stage="starting", progress=1, message="Preparing the research pipeline.")
        from backend.app.services.pipeline import run_research

        def progress(stage: str, percent: int, message: str) -> None:
            update_job(job_id, stage=stage, progress=percent, message=message)

        result = run_research(topic, max_results, progress)
        update_job(job_id, status="completed", stage="complete", progress=100, message="Investigation completed.", result=result, completed_at=now())
    except Exception as exc:
        logger.exception("Alethia research job failed")
        update_job(job_id, status="failed", error=str(exc), message="The pipeline stopped before completion.", completed_at=now())
    finally:
        PIPELINE_LOCK.release()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Alethia API",
        "graph_available": GRAPH_PATH.exists(),
        "ollama_configured": True,
        "data_directory": str(DATA_DIR),
    }


@app.get("/api/dashboard")
def dashboard():
    return dashboard_payload()


@app.get("/api/graph")
def get_graph(
    node_type: str | None = None,
    limit: int = Query(default=700, ge=1, le=2500),
):
    data = graph_data()
    nodes = data.get("nodes", [])
    if node_type:
        nodes = [node for node in nodes if node.get("node_type") == node_type]
        allowed = {node.get("id") for node in nodes}
        edges = [edge for edge in data.get("edges", []) if edge.get("source") in allowed and edge.get("target") in allowed]
    else:
        nodes = nodes[:limit]
        allowed = {node.get("id") for node in nodes}
        edges = [edge for edge in data.get("edges", []) if edge.get("source") in allowed and edge.get("target") in allowed]
    return {"nodes": nodes, "edges": edges, "total_nodes": len(data.get("nodes", [])), "total_edges": len(data.get("edges", []))}


@app.get("/api/papers")
def papers(search: str = ""):
    data = graph_data()
    nodes, _ = build_indexes(data)
    paper_nodes = [node for node in nodes.values() if node.get("node_type") == "paper"]
    result = []
    for paper in paper_nodes:
        related_claims = [
            node for node in nodes.values()
            if node.get("node_type") == "claim" and node.get("source_paper_id") == paper.get("id")
        ]
        item = {**paper, "claim_count": len(related_claims)}
        if search.lower() in json.dumps(item, ensure_ascii=False).lower():
            result.append(item)
    return {"items": result, "total": len(result)}


@app.get("/api/claims")
def claims(search: str = "", relationship: str = "all", limit: int = Query(default=300, ge=1, le=1000)):
    data = graph_data()
    nodes, evidence_by_claim = build_indexes(data)
    result = []
    for node in nodes.values():
        if node.get("node_type") != "claim":
            continue
        evidence = evidence_by_claim.get(node.get("id"), [])
        if relationship != "all" and not any(item.get("relationship") == relationship for item in evidence):
            continue
        paper = nodes.get(node.get("source_paper_id"), {})
        item = {
            **node,
            "paper_title": paper.get("title") or paper.get("label") or "Research paper",
            "evidence": evidence,
            "evidence_count": len(evidence),
        }
        if search.lower() in json.dumps(item, ensure_ascii=False).lower():
            result.append(item)
    return {"items": result[:limit], "total": len(result)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Research job not found.")
        return dict(job)


@app.post("/api/research", status_code=202)
async def start_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    if not PIPELINE_LOCK.locked():
        pass
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "topic": request.topic.strip(),
        "max_results": request.max_results,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "Your investigation has been queued.",
        "created_at": now(),
        "updated_at": now(),
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    background_tasks.add_task(run_job, job_id, request.topic.strip(), request.max_results)
    return job


@app.get("/api/exports")
def exports():
    return {
        "graph_json": GRAPH_PATH.exists(),
        "graphml": (GRAPH_DIR / "alethia_knowledge_graph.graphml").exists(),
        "interactive_html": (GRAPH_DIR / "alethia_knowledge_graph.html").exists(),
        "research_insights": INSIGHTS_PATH.exists(),
        "build_report": REPORT_PATH.exists(),
    }


@app.get("/api/exports/{filename}")
def download_export(filename: str):
    allowed = {
        "graph.json": GRAPH_PATH,
        "graph.graphml": GRAPH_DIR / "alethia_knowledge_graph.graphml",
        "graph.html": GRAPH_DIR / "alethia_knowledge_graph.html",
        "insights.json": INSIGHTS_PATH,
        "report.json": REPORT_PATH,
    }
    path = allowed.get(filename)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Export not found.")
    from fastapi.responses import FileResponse
    return FileResponse(path, filename=path.name)


@app.get("/")
def root():
    return {"name": "Alethia", "api": "/docs", "health": "/api/health"}
