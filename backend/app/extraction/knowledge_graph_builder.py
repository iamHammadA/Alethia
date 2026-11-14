"""
Alethia Knowledge Graph Builder
--------------------------------
Builds a provenance-preserving research knowledge graph from:

    arXiv papers/matched_evidence.json
    arXiv papers/analyzed_evidences.json
    arXiv papers/paper_metadata.json       (optional)

Outputs:
    arXiv papers/knowledge_graph/
        alethia_knowledge_graph.graphml
        alethia_knowledge_graph.json
        alethia_knowledge_graph.html      (premium animated viewer)
        research_insights.json
        build_report.json

Install:
    pip install networkx scikit-learn
    (PyVis is no longer needed; the HTML viewer is self-contained and loads
     vis-network + a web font from a CDN, so open it with internet access.)

Optional cross-paper LLM classification:
    export ALETHIA_CROSS_PAPER_LLM=1
    export OLLAMA_CROSS_PAPER_MODEL=llama3.2

The cross-paper classifier is deliberately conservative. Its contradiction
edges are labelled POTENTIAL_CONTRADICTION, never established fact.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any
from .claim_evidence_linker import linker

import networkx as nx

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next(
    (parent for parent in CURRENT_FILE.parents
     if parent.name.lower() == "alethia"),
    CURRENT_FILE.parent,
)

DATA_DIR = ROOT_DIR / "arXiv papers"
OUTPUT_DIR = DATA_DIR / "knowledge_graph"

MATCHED_EVIDENCE_PATH = DATA_DIR / "matched_evidence.json"
ANALYZED_EVIDENCE_PATH = DATA_DIR / "analyzed_evidences.json"
FINAL_EVIDENCE_PATH = DATA_DIR / "final_evidences.json"
PAPER_METADATA_PATH = DATA_DIR / "paper_metadata.json"

GRAPHML_PATH = OUTPUT_DIR / "alethia_knowledge_graph.graphml"
GRAPH_JSON_PATH = OUTPUT_DIR / "alethia_knowledge_graph.json"
HTML_PATH = OUTPUT_DIR / "alethia_knowledge_graph.html"
INSIGHTS_PATH = OUTPUT_DIR / "research_insights.json"
REPORT_PATH = OUTPUT_DIR / "build_report.json"

# Cross-paper comparisons are bounded to avoid an uncontrolled O(n²)
# number of LLM requests.
SIMILARITY_THRESHOLD = float(
    os.getenv("ALETHIA_CLAIM_SIMILARITY_THRESHOLD", "0.35")
)
MAX_LLM_PAIRS = int(os.getenv("ALETHIA_MAX_LLM_PAIRS", "40"))
ENABLE_LLM_CROSS_PAPER = (
    os.getenv("ALETHIA_CROSS_PAPER_LLM", "0").lower()
    in {"1", "true", "yes"}
)
OLLAMA_CROSS_PAPER_MODEL = os.getenv(
    "OLLAMA_CROSS_PAPER_MODEL", "llama3.2"
)

# Keep HTML usable on large graphs. The complete graph is still saved to
# GraphML and JSON; only the browser visualization is capped.
MAX_HTML_NODES = int(os.getenv("ALETHIA_MAX_HTML_NODES", "2500"))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)
logger = logging.getLogger("alethia.graph")


# ---------------------------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------------------------

def stable_id(prefix: str, *parts: Any) -> str:
    """Create a deterministic ID that remains stable between graph updates."""
    raw = "||".join(
        normalize_text(str(part)) if part is not None else ""
        for part in parts
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return text.strip()


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    value = str(value).strip()
    return value or None


def safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if 0.0 <= number <= 1.0:
            return number
    except (TypeError, ValueError):
        pass
    return None


def load_json(path: Path, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required JSON file not found: {path}")
        logger.warning("Optional input not found: %s", path.name)
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {path}: line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc


def parse_claim_payload(value: Any) -> dict:
    """
    Supports:
      - a normal dictionary
      - a JSON-encoded dictionary
      - Python-dict-looking strings containing True/False/None
      - plain claim text
    Uses literal_eval, never eval.
    """
    if isinstance(value, dict):
        return value

    if not isinstance(value, str):
        return {"original_text": clean_text(value)}

    raw = value.strip()
    if not raw:
        return {}

    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError, json.JSONDecodeError):
            continue

    return {"original_text": raw}


def first_value(mapping: dict, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return [value]


def add_edge(
    graph: nx.MultiDiGraph,
    source: str,
    target: str,
    relationship: str,
    **attributes: Any
) -> None:
    """Add a uniquely keyed edge; duplicate edges are ignored."""
    if source not in graph or target not in graph:
        return

    edge_id = stable_id(
        "edge",
        source,
        target,
        relationship,
        attributes.get("evidence_id", ""),
        attributes.get("reason", ""),
    )

    if graph.has_edge(source, target, key=edge_id):
        return

    graph.add_edge(
        source,
        target,
        key=edge_id,
        edge_id=edge_id,
        relationship=relationship,
        **attributes,
    )


# ---------------------------------------------------------------------------
# INPUT NORMALIZATION
# ---------------------------------------------------------------------------

def normalize_article_container(data: Any) -> dict:
    """
    Normalizes article containers without assuming every JSON file has
    exactly the same nesting structure.
    """
    if not isinstance(data, dict):
        logger.warning("Expected article-keyed JSON object; got %s", type(data))
        return {}

    # Some exports wrap the article mapping in a top-level key.
    for wrapper_key in ("articles", "papers", "results", "data"):
        wrapped = data.get(wrapper_key)
        if isinstance(wrapped, dict):
            return wrapped

    return data


def get_analyzed_records(value: Any) -> list[dict]:
    """
    Supports:
      article_id -> [analysis, analysis]
      article_id -> {"claims_analyzed": [...]}
      article_id -> {"evidence_analysis": [...]}
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]

    if isinstance(value, dict):
        for key in (
            "claims_analyzed",
            "analyzed_claims",
            "evidences",
            "evidence_analysis",
            "results",
        ):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]

        # A single analysis object.
        if "claim" in value or "evidence_analysis" in value:
            return [value]

    return []


def claim_identity(claim_payload: dict, fallback: Any = None) -> str:
    text = first_value(
        claim_payload,
        "normalized_claim",
        "text",
        "original_claim",
        "claim",
        "original_text",
    )
    if text is None:
        text = fallback
    return normalize_text(text)


def extract_metadata(
    article_id: str,
    article_record: Any,
    external_metadata: Any
) -> dict:
    article = article_record if isinstance(article_record, dict) else {}
    external = {}

    if isinstance(external_metadata, dict):
        candidate = external_metadata.get(article_id)
        if isinstance(candidate, dict):
            external = candidate

    # Metadata can be nested under "metadata" or stored at article level.
    nested = article.get("metadata")
    if isinstance(nested, dict):
        article = {**article, **nested}

    nested_external = external.get("metadata")
    if isinstance(nested_external, dict):
        external = {**external, **nested_external}

    merged = {**article, **external}

    source_pdf = first_value(
        merged, "file", "pdf", "pdf_file", "source_pdf", "filename"
    )

    arxiv_id = first_value(
        merged, "arxiv_id", "arxiv", "arxiv_identifier", "id"
    )

    title = first_value(
        merged, "title", "paper_title", "document_title"
    )

    if not arxiv_id:
        candidates = " ".join(
            str(value) for value in (source_pdf, article_id, title)
            if value
        )
        match = re.search(
            r"(?:arxiv[:\s/]*)?(\d{4}\.\d{4,5})(?:v\d+)?",
            candidates,
            flags=re.IGNORECASE,
        )
        if match:
            arxiv_id = match.group(1)

    authors = first_value(merged, "authors", "author", "creators")
    if isinstance(authors, str):
        authors = [part.strip() for part in re.split(r";|,", authors)
                   if part.strip()]
    elif not isinstance(authors, list):
        authors = []

    year = first_value(
        merged, "year", "publication_year", "published_year"
    )
    if year is not None:
        try:
            year = int(str(year)[:4])
        except (TypeError, ValueError):
            year = None

    return {
        "title": clean_text(title),
        "authors": authors,
        "publication_year": year,
        "arxiv_id": clean_text(arxiv_id),
        "abstract": clean_text(first_value(merged, "abstract", "summary")),
        "source_pdf": clean_text(source_pdf),
        "metadata_source": (
            "paper_metadata.json"
            if external else "article_record_or_filename"
        ),
    }


# ---------------------------------------------------------------------------
# GRAPH NODE CONSTRUCTION
# ---------------------------------------------------------------------------

def add_paper_node(
    graph: nx.MultiDiGraph,
    article_id: str,
    metadata: dict
) -> str:
    identity = metadata.get("arxiv_id") or metadata.get("source_pdf") or article_id
    paper_id = stable_id("paper", identity)

    if paper_id not in graph:
        graph.add_node(
            paper_id,
            node_type="paper",
            label=metadata.get("title") or metadata.get("source_pdf")
                  or article_id,
            title=metadata.get("title") or "Unknown title",
            authors=json.dumps(metadata.get("authors", []), ensure_ascii=False),
            publication_year=metadata.get("publication_year") or "",
            arxiv_id=metadata.get("arxiv_id") or "",
            abstract=metadata.get("abstract") or "",
            source_pdf=metadata.get("source_pdf") or "",
            article_key=article_id,
            metadata_source=metadata.get("metadata_source", ""),
        )

    return paper_id


def add_claim_node(
    graph: nx.MultiDiGraph,
    paper_id: str,
    claim_payload: dict,
    fallback_claim: Any = None,
) -> str | None:
    original = first_value(
        claim_payload, "original_text", "text", "original_claim"
    )
    normalized = first_value(
        claim_payload, "normalized_claim", "normalized_text"
    )

    if not normalized:
        normalized = clean_text(fallback_claim) or clean_text(original)

    if not original:
        original = clean_text(fallback_claim) or normalized

    if not normalized:
        return None

    claim_id = stable_id("claim", paper_id, normalized)

    if claim_id not in graph:
        graph.add_node(
            claim_id,
            node_type="claim",
            label=(normalized[:105] + "…")
                  if len(normalized) > 105 else normalized,
            original_text=clean_text(original) or "",
            normalized_claim=clean_text(normalized) or "",
            source_paper_id=paper_id,
            claim_type=clean_text(claim_payload.get("claim_type")) or "unknown",
            subject=clean_text(claim_payload.get("subject")) or "",
            relation=clean_text(claim_payload.get("relation")) or "",
            object=clean_text(claim_payload.get("object")) or "",
            requires_evidence=str(
                claim_payload.get("requires_evidence", "")
            ),
            claim_confidence=safe_float(
                claim_payload.get("confidence")
            ) if safe_float(claim_payload.get("confidence")) is not None else "",
        )

    add_edge(graph, paper_id, claim_id, "CONTAINS")
    return claim_id


def add_standalone_evidence_node(
    graph: nx.MultiDiGraph,
    paper_id: str,
    evidence: dict,
) -> str | None:
    """Create evidence from a flat article->evidence JSON without guessing a claim."""
    sentence = clean_text(first_value(evidence, "sentence", "text", "passage"))
    if not sentence:
        return None

    page = first_value(evidence, "page", "page_number", "page_num")
    page_key = str(page) if page is not None else ""
    evidence_id = stable_id("evidence", paper_id, sentence, page_key)

    if evidence_id not in graph:
        similarity = safe_float(evidence.get("similarity"))
        strength = safe_float(first_value(evidence, "strength", "evidence_strength"))
        graph.add_node(
            evidence_id,
            node_type="evidence",
            label=(sentence[:90] + "…") if len(sentence) > 90 else sentence,
            sentence=sentence,
            source_paper_id=paper_id,
            page_number=page_key,
            section=clean_text(evidence.get("section")) or "",
            similarity=similarity if similarity is not None else "",
            strength=strength if strength is not None else "",
            relationship=clean_text(evidence.get("relationship")) or "unknown",
            reason=clean_text(first_value(evidence, "reason", "explanation", "reasoning")) or "",
            claim_link_status="unlinked_no_claim_in_source_json",
        )
    return evidence_id


def add_evidence_node(
    graph: nx.MultiDiGraph,
    paper_id: str,
    claim_id: str,
    evidence: dict,
) -> str | None:
    sentence = clean_text(
        first_value(evidence, "sentence", "text", "passage")
    )
    if not sentence:
        return None

    page = first_value(evidence, "page", "page_number", "page_num")
    page_key = str(page) if page is not None else ""

    # Evidence is deduplicated within a source paper, not globally across
    # different papers. Identical passages in different papers retain provenance.
    evidence_id = stable_id("evidence", paper_id, sentence, page_key)

    if evidence_id not in graph:
        graph.add_node(
            evidence_id,
            node_type="evidence",
            label=(sentence[:90] + "…") if len(sentence) > 90 else sentence,
            sentence=sentence,
            source_paper_id=paper_id,
            page_number=page_key,
            section=clean_text(evidence.get("section")) or "",
            similarity=safe_float(evidence.get("similarity"))
                        if safe_float(evidence.get("similarity")) is not None
                        else "",
            strength=safe_float(
                first_value(evidence, "strength", "evidence_strength")
            ) if safe_float(first_value(
                evidence, "strength", "evidence_strength"
            )) is not None else "",
            relationship=clean_text(evidence.get("relationship")) or "unknown",
            reason=clean_text(first_value(
                evidence, "reason", "explanation", "reasoning"
            )) or "",
        )

    relation = str(evidence.get("relationship", "insufficient")).lower()
    relation_map = {
        "supports": "SUPPORTS",
        "contradicts": "CONTRADICTS",
        "insufficient": "INSUFFICIENT",
        "irrelevant": "IRRELEVANT",
    }
    edge_type = relation_map.get(relation, "UNCLASSIFIED_EVIDENCE")

    add_edge(
        graph,
        evidence_id,
        claim_id,
        edge_type,
        similarity=safe_float(evidence.get("similarity")) or "",
        strength=safe_float(first_value(
            evidence, "strength", "evidence_strength"
        )) or "",
        reason=clean_text(first_value(
            evidence, "reason", "explanation", "reasoning"
        )) or "",
        source_paper_id=paper_id,
        page_number=page_key,
    )

    return evidence_id


# ---------------------------------------------------------------------------
# METHODS, DATASETS, CONCEPTS AND ENTITIES
# ---------------------------------------------------------------------------

METHOD_TERMS = [
    "self-attention", "multi-head attention", "direct preference optimization",
    "dpo", "reinforcement learning from human feedback", "rlhf",
    "fine-tuning", "fine tuning", "parameter-efficient fine-tuning",
    "lora", "retrieval-augmented generation", "rag",
    "convolutional neural network", "cnn", "recurrent neural network",
    "rnn", "lstm", "gru", "support vector machine", "svm",
    "random forest", "gradient boosting", "decision tree", "k-means",
    "kmeans", "word2vec", "fasttext", "backpropagation",
]

MODEL_TERMS = [
    "large language model", "llm", "gpt", "bert", "roberta",
    "t5", "bart", "llama", "gemma", "mistral", "qwen",
    "claude", "transformer model", "diffusion model",
]

ALGORITHM_TERMS = [
    "adamw", "adam optimizer", "adam", "gradient descent",
    "stochastic gradient descent", "sgd", "beam search",
    "a* search", "a-star search", "genetic algorithm",
    "simulated annealing", "dijkstra's algorithm",
]

CONCEPT_TERMS = [
    "attention mechanism", "attention", "generalization",
    "overfitting", "underfitting", "catastrophic forgetting",
    "representation learning", "transfer learning",
    "natural language processing", "natural language understanding",
    "conversational fluency", "user engagement", "linguistic accuracy",
    "semantic similarity", "knowledge representation",
    "reasoning", "interpretability", "explainability",
    "robustness", "scalability", "model alignment",
    "human feedback", "human-like responses",
]

DATASET_CUES = ("dataset", "benchmark", "corpus", "data set")


def add_named_node(
    graph: nx.MultiDiGraph,
    node_type: str,
    name: str,
    description: str = "",
) -> str:
    node_id = stable_id(node_type, name)

    if node_id not in graph:
        graph.add_node(
            node_id,
            node_type=node_type,
            label=name,
            name=name,
            description=description or "",
        )

    return node_id


def contains_term(text: str, term: str) -> bool:
    # Phrase-aware matching avoids matching short acronyms inside other words.
    return bool(re.search(
        r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
        text,
        flags=re.IGNORECASE,
    ))


def extract_methods_and_concepts(
    graph: nx.MultiDiGraph,
    paper_id: str,
    claim_id: str,
    claim_payload: dict,
    claim_text: str,
) -> None:
    text = " ".join([
        claim_text or "",
        str(claim_payload.get("subject") or ""),
        str(claim_payload.get("object") or ""),
    ])

    relation_verb = str(claim_payload.get("relation") or "").lower()
    introduces = any(verb in relation_verb for verb in (
        "introduc", "propos", "develop", "present", "design"
    ))

    # Methods/techniques are created only when explicitly named in a claim.
    for method in METHOD_TERMS:
        if contains_term(text, method):
            display = method.upper() if method in {
                "dpo", "rlhf", "rag", "lora", "cnn", "rnn", "lstm", "gru", "svm"
            } else method.title()
            method_id = add_named_node(graph, "method", display)
            add_edge(graph, claim_id, method_id, "USES_METHOD")
            add_edge(graph, paper_id, method_id, "USES_METHOD")
            if introduces:
                add_edge(graph, paper_id, method_id, "INTRODUCES")

    # Model architectures and named model families are kept distinct from methods.
    for model in MODEL_TERMS:
        if contains_term(text, model):
            display = model.upper() if model in {"llm", "gpt", "bert", "t5", "bart"} else model.title()
            model_id = add_named_node(graph, "model", display)
            add_edge(graph, claim_id, model_id, "USES_MODEL")
            add_edge(graph, paper_id, model_id, "USES_MODEL")
            if introduces:
                add_edge(graph, paper_id, model_id, "INTRODUCES")

    # Algorithms are separate nodes, even if some also appear as techniques.
    for algorithm in ALGORITHM_TERMS:
        if contains_term(text, algorithm):
            display = algorithm.upper() if algorithm in {"sgd"} else algorithm.title()
            algorithm_id = add_named_node(graph, "algorithm", display)
            add_edge(graph, claim_id, algorithm_id, "USES_ALGORITHM")
            add_edge(graph, paper_id, algorithm_id, "USES_ALGORITHM")
            if introduces:
                add_edge(graph, paper_id, algorithm_id, "INTRODUCES")

    # Scientific concepts are vocabulary matches, not LLM-generated guesses.
    for concept in CONCEPT_TERMS:
        if contains_term(text, concept):
            concept_id = add_named_node(graph, "concept", concept.title())
            add_edge(graph, claim_id, concept_id, "ABOUT")
            add_edge(graph, paper_id, concept_id, "DISCUSSES")

    # Dataset names are recognized only when the extracted object explicitly
    # contains a dataset/benchmark/corpus phrase.
    object_text = str(claim_payload.get("object") or "")
    for cue in DATASET_CUES:
        pattern = re.compile(
            r"\b([A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,5}\s+"
            + re.escape(cue) + r")\b",
            re.IGNORECASE,
        )
        for match in pattern.finditer(object_text):
            dataset_name = match.group(1).strip()
            dataset_id = add_named_node(graph, "dataset", dataset_name)
            add_edge(graph, paper_id, dataset_id, "EVALUATES_ON")
            add_edge(graph, claim_id, dataset_id, "ABOUT")

    # Subject/object are preserved as extracted entities.
    for field, edge_type in (("subject", "HAS_SUBJECT"), ("object", "ABOUT")):
        value = clean_text(claim_payload.get(field))
        if value and len(value) >= 3:
            entity_id = add_named_node(graph, "entity", value)
            add_edge(graph, claim_id, entity_id, edge_type)


# ---------------------------------------------------------------------------
# CROSS-PAPER CLAIM COMPARISON
# ---------------------------------------------------------------------------

def claim_evidence_summary(
    graph: nx.MultiDiGraph,
    claim_id: str,
) -> list[str]:
    sentences = []
    for source, target, _, attrs in graph.in_edges(
        claim_id, keys=True, data=True
    ):
        if graph.nodes[source].get("node_type") == "evidence":
            sentences.append(graph.nodes[source].get("sentence", ""))
    return sentences[:5]


def classify_claim_pair_with_ollama(
    graph: nx.MultiDiGraph,
    claim_a: str,
    claim_b: str,
) -> dict | None:
    """
    Optional conservative cross-paper classification.
    Returns a suggestion, not a verified scientific conclusion.
    """
    try:
        import ollama
    except ImportError:
        logger.warning(
            "Ollama Python package is unavailable; skipping LLM comparison."
        )
        return None

    node_a = graph.nodes[claim_a]
    node_b = graph.nodes[claim_b]

    evidence_a = claim_evidence_summary(graph, claim_a)
    evidence_b = claim_evidence_summary(graph, claim_b)

    prompt = {
        "claim_a": node_a.get("normalized_claim"),
        "paper_a": node_a.get("source_paper_id"),
        "evidence_a": evidence_a,
        "claim_b": node_b.get("normalized_claim"),
        "paper_b": node_b.get("source_paper_id"),
        "evidence_b": evidence_b,
    }

    system = """
You compare scientific claims from different research papers.

Be conservative. Different wording is not a contradiction.
A contradiction requires incompatible findings about sufficiently
comparable outcomes, with attention to methods, datasets, populations,
metrics, and experimental conditions.

Return JSON only:
{
  "relationship": "supports | contradicts | extends | similar |
                  same_problem | uses_similar_method | uncertain",
  "confidence": 0.0,
  "reason": "short explanation",
  "contextual_difference": "important differences or empty string"
}

If the evidence is not enough to compare the claims, use uncertain.
Do not invent experimental details.
"""

    try:
        response = ollama.chat(
            model=OLLAMA_CROSS_PAPER_MODEL,
            format="json",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
            options={"temperature": 0.0},
        )
        result = json.loads(response["message"]["content"])
        if not isinstance(result, dict):
            return None
        return result
    except Exception as exc:
        logger.warning("Cross-paper LLM comparison failed: %s", exc)
        return None


def compare_cross_paper_claims(graph: nx.MultiDiGraph) -> list[dict]:
    claim_ids = [
        node_id for node_id, attrs in graph.nodes(data=True)
        if attrs.get("node_type") == "claim"
    ]

    if len(claim_ids) < 2:
        return []

    texts = [
        graph.nodes[claim_id].get("normalized_claim", "")
        for claim_id in claim_ids
    ]

    if not SKLEARN_AVAILABLE:
        logger.warning(
            "scikit-learn unavailable; skipping TF-IDF cross-paper matching."
        )
        return []

    try:
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        matrix = vectorizer.fit_transform(texts)
        similarity_matrix = cosine_similarity(matrix)
    except ValueError:
        logger.warning("Not enough usable claim text for similarity analysis.")
        return []

    candidates = []

    for i, j in combinations(range(len(claim_ids)), 2):
        claim_a = claim_ids[i]
        claim_b = claim_ids[j]

        paper_a = graph.nodes[claim_a].get("source_paper_id")
        paper_b = graph.nodes[claim_b].get("source_paper_id")

        if paper_a == paper_b:
            continue

        score = float(similarity_matrix[i, j])
        if score < SIMILARITY_THRESHOLD:
            continue

        candidates.append((score, claim_a, claim_b))

    candidates.sort(reverse=True, key=lambda item: item[0])

    comparison_records = []
    record_by_pair = {}

    for score, claim_a, claim_b in candidates:
        add_edge(
            graph,
            claim_a,
            claim_b,
            "SIMILAR_TO",
            similarity=score,
            provenance="tfidf_candidate_matching",
            confidence=score,
        )
        add_edge(
            graph,
            claim_b,
            claim_a,
            "SIMILAR_TO",
            similarity=score,
            provenance="tfidf_candidate_matching",
            confidence=score,
        )

        record = {
            "claim_a": claim_a,
            "claim_b": claim_b,
            "paper_a": graph.nodes[claim_a].get("source_paper_id"),
            "paper_b": graph.nodes[claim_b].get("source_paper_id"),
            "similarity": score,
            "relationship": "similarity_candidate",
            "reason": (
                "TF-IDF text similarity identifies these claims as "
                "candidates for further scientific comparison. This is "
                "not evidence of support or contradiction."
            ),
        }

        comparison_records.append(record)
        record_by_pair[(claim_a, claim_b)] = record

    if ENABLE_LLM_CROSS_PAPER:
        for score, claim_a, claim_b in candidates[:MAX_LLM_PAIRS]:
            result = classify_claim_pair_with_ollama(
                graph, claim_a, claim_b
            )
            if not result:
                continue

            relationship = str(
                result.get("relationship", "uncertain")
            ).lower()
            confidence = safe_float(result.get("confidence")) or 0.0
            reason = clean_text(result.get("reason")) or ""
            contextual_difference = clean_text(
                result.get("contextual_difference")
            ) or ""

            edge_map = {
                "supports": "POTENTIAL_SUPPORT",
                "contradicts": "POTENTIAL_CONTRADICTION",
                "extends": "EXTENDS",
                "similar": "SIMILAR_TO",
                "same_problem": "INVESTIGATES_SAME_PROBLEM",
                "uses_similar_method": "USES_SIMILAR_METHOD",
                "uncertain": "UNCERTAIN_RELATION",
            }
            edge_type = edge_map.get(
                relationship, "UNCERTAIN_RELATION"
            )

            attrs = {
                "similarity": score,
                "confidence": confidence,
                "reason": reason,
                "contextual_difference": contextual_difference,
                "provenance": "ollama_cross_paper_suggestion",
                "status": "AI_SUGGESTED_NOT_VERIFIED",
                "source_paper_a": graph.nodes[claim_a].get(
                    "source_paper_id"
                ),
                "source_paper_b": graph.nodes[claim_b].get(
                    "source_paper_id"
                ),
            }

            add_edge(graph, claim_a, claim_b, edge_type, **attrs)
            add_edge(graph, claim_b, claim_a, edge_type, **attrs)

            # Update the matching record (the original loop variable
            # `record` only ever pointed at the last candidate).
            record_by_pair[(claim_a, claim_b)].update({
                "relationship": edge_type,
                "confidence": confidence,
                "reason": reason,
                "contextual_difference": contextual_difference,
                "status": "AI_SUGGESTED_NOT_VERIFIED",
            })

    return comparison_records


# ---------------------------------------------------------------------------
# BUILD GRAPH FROM INPUT FILES
# ---------------------------------------------------------------------------

def build_graph() -> tuple[nx.MultiDiGraph, dict]:
    matched_data = normalize_article_container(
        load_json(MATCHED_EVIDENCE_PATH, required=False)
    )

    # Prefer the claim-level analysis file when present. If it is absent,
    # accept the user's flattened final_evidences.json format:
    # article_id -> [{sentence, similarity, relationship, strength, reason}]
    if ANALYZED_EVIDENCE_PATH.exists():
        analyzed_source_path = ANALYZED_EVIDENCE_PATH
    else:
        analyzed_source_path = FINAL_EVIDENCE_PATH

    analyzed_data = normalize_article_container(
        load_json(analyzed_source_path, required=False)
    )
    metadata_data = normalize_article_container(
        load_json(PAPER_METADATA_PATH, required=False)
    )

    graph = nx.MultiDiGraph(
        name="Alethia Scientific Knowledge Graph",
        version="1.0",
    )

    report = {
        "articles_seen": 0,
        "papers_created": 0,
        "claims_created": 0,
        "evidence_created": 0,
        "methods_created": 0,
        "concepts_created": 0,
        "entities_created": 0,
        "datasets_created": 0,
        "warnings": [],
        "input_files": {
            "matched_evidence": str(MATCHED_EVIDENCE_PATH),
            "analyzed_evidence": str(analyzed_source_path),
            "paper_metadata": (
                str(PAPER_METADATA_PATH)
                if PAPER_METADATA_PATH.exists() else None
            ),
        },
    }

    article_ids = set(matched_data) | set(analyzed_data)

    for article_id in sorted(article_ids):
        report["articles_seen"] += 1

        matched_record = matched_data.get(article_id, {})
        analyzed_record = analyzed_data.get(article_id, [])

        metadata = extract_metadata(
            article_id,
            matched_record,
            metadata_data,
        )

        paper_id = add_paper_node(graph, article_id, metadata)

        matched_claims = []
        if isinstance(matched_record, dict):
            matched_claims = as_list(
                matched_record.get("claims_analyzed")
            )

        analyzed_claims = get_analyzed_records(analyzed_record)

        # FLAT EVIDENCE MODE: the supplied final_evidences.json format has
        # article_id -> list[ evidence passage ], with no claim field. In this
        # case, create evidence nodes and preserve their paper provenance, but
        # do NOT invent a claim-to-evidence association.
        flat_evidence_records = (
            isinstance(analyzed_record, list)
            and bool(analyzed_record)
            and all(
                isinstance(item, dict)
                and first_value(item, "sentence", "text", "passage")
                and not first_value(item, "claim", "claim_text")
                and not isinstance(item.get("evidence_analysis"), list)
                for item in analyzed_record
            )
        )

        if flat_evidence_records and not matched_claims:
            for evidence in analyzed_record:
                evidence_id = add_standalone_evidence_node(
                    graph, paper_id, evidence
                )
                if evidence_id:
                    add_edge(graph, paper_id, evidence_id, "CONTAINS_EVIDENCE")
            continue

        # Index analyzed evidence by its parsed claim text.
        analyzed_index = {}
        for analysis in analyzed_claims:
            parsed = parse_claim_payload(analysis.get("claim"))
            key = claim_identity(parsed, analysis.get("claim"))
            if key:
                analyzed_index[key] = analysis

        # Also accept an analyzed-only input when matched_evidence is absent.
        if not matched_claims:
            matched_claims = [
                {"claim": item.get("claim")}
                for item in analyzed_claims
            ]

        seen_claims_for_article = set()

        for matched_claim in matched_claims:
            if not isinstance(matched_claim, dict):
                report["warnings"].append(
                    f"{article_id}: skipped non-object claim record"
                )
                continue

            parsed_claim = parse_claim_payload(
                matched_claim.get("claim", matched_claim)
            )

            key = claim_identity(
                parsed_claim,
                matched_claim.get("claim"),
            )

            analysis = analyzed_index.get(key, {})

            # Some earlier files stored a normalized claim as plain text.
            if not analysis and len(analyzed_claims) == len(matched_claims):
                candidate_index = matched_claims.index(matched_claim)
                if candidate_index < len(analyzed_claims):
                    analysis = analyzed_claims[candidate_index]

            analyzed_claim_payload = parse_claim_payload(
                analysis.get("claim")
            ) if analysis else {}

            # Merge extracted SVO fields and normalized LLM fields.
            merged_claim = {
                **parsed_claim,
                **analyzed_claim_payload,
            }

            normalized = first_value(
                merged_claim, "normalized_claim", "text", "original_text"
            )
            if normalized:
                merged_claim["normalized_claim"] = normalized

            claim_id = add_claim_node(
                graph,
                paper_id,
                merged_claim,
                fallback_claim=matched_claim.get("claim"),
            )

            if not claim_id:
                report["warnings"].append(
                    f"{article_id}: skipped claim with empty text"
                )
                continue

            if claim_id in seen_claims_for_article:
                continue
            seen_claims_for_article.add(claim_id)

            # Attach overall evidence assessment to the claim node.
            if analysis:
                graph.nodes[claim_id]["overall_relationship"] = (
                    clean_text(analysis.get("overall_relationship")) or ""
                )
                overall_strength = safe_float(
                    analysis.get("overall_strength")
                )
                graph.nodes[claim_id]["overall_strength"] = (
                    overall_strength if overall_strength is not None else ""
                )
                graph.nodes[claim_id]["best_evidence"] = (
                    clean_text(analysis.get("best_evidence")) or ""
                )

            # The analyzed evidence list is authoritative when available.
            evidence_items = []
            if analysis and isinstance(
                analysis.get("evidence_analysis"), list
            ):
                evidence_items = analysis["evidence_analysis"]
            elif isinstance(matched_claim.get("evidence_candidates"), list):
                # Preserve retrieved candidates even before LLM analysis.
                evidence_items = [
                    {
                        **candidate,
                        "relationship": "insufficient",
                        "strength": 0.0,
                        "reason": "Retrieved candidate; not yet analyzed.",
                    }
                    for candidate in matched_claim["evidence_candidates"]
                    if isinstance(candidate, dict)
                ]

            for evidence in evidence_items:
                if not isinstance(evidence, dict):
                    continue
                add_evidence_node(
                    graph, paper_id, claim_id, evidence
                )

            claim_text = (
                clean_text(merged_claim.get("normalized_claim"))
                or clean_text(matched_claim.get("claim"))
                or ""
            )

            extract_methods_and_concepts(
                graph,
                paper_id,
                claim_id,
                merged_claim,
                claim_text,
            )

            # A hypothesis extracted by the claim classifier becomes a
            # separate hypothesis node, linked to its source claim.
            if str(merged_claim.get("claim_type", "")).lower() == "hypothesis":
                hypothesis_id = add_named_node(
                    graph, "hypothesis", claim_text,
                    description="Extracted hypothesis; not independently verified."
                )
                graph.nodes[hypothesis_id]["status"] = "EXTRACTED_FROM_PAPER"
                add_edge(graph, claim_id, hypothesis_id, "EXPRESSES_HYPOTHESIS")
                add_edge(graph, paper_id, hypothesis_id, "CONTAINS_HYPOTHESIS")

    # Counts are computed from actual graph nodes after deduplication.
    type_counts = Counter(
        attrs.get("node_type")
        for _, attrs in graph.nodes(data=True)
    )
    report["papers_created"] = type_counts["paper"]
    report["claims_created"] = type_counts["claim"]
    report["evidence_created"] = type_counts["evidence"]
    report["methods_created"] = type_counts["method"]
    report["concepts_created"] = type_counts["concept"]
    report["entities_created"] = type_counts["entity"]
    report["datasets_created"] = type_counts["dataset"]
    report["models_created"] = type_counts["model"]
    report["algorithms_created"] = type_counts["algorithm"]

    return graph, report


# ---------------------------------------------------------------------------
# EXPORT: JSON, GRAPHML, RESEARCH INSIGHTS
# ---------------------------------------------------------------------------

def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def export_graph_json(graph: nx.MultiDiGraph) -> None:
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        nodes.append({
            "id": node_id,
            **{key: json_safe(value) for key, value in attrs.items()},
        })

    edges = []
    for source, target, key, attrs in graph.edges(
        keys=True, data=True
    ):
        edges.append({
            "id": key,
            "source": source,
            "target": target,
            **{name: json_safe(value) for name, value in attrs.items()},
        })

    payload = {
        "graph": {
            "name": "Alethia Scientific Knowledge Graph",
            "directed": True,
            "multigraph": True,
        },
        "nodes": nodes,
        "edges": edges,
    }

    with GRAPH_JSON_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def export_graphml(graph: nx.MultiDiGraph) -> None:
    """
    GraphML attributes are converted to strings to avoid mixed-type
    serialization errors and to preserve nested values as JSON strings.
    """
    export_graph = nx.MultiDiGraph()

    for node_id, attrs in graph.nodes(data=True):
        export_graph.add_node(
            node_id,
            **{
                str(key): (
                    value if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list, tuple))
                    else str(value)
                )
                for key, value in attrs.items()
                if value is not None
            },
        )

    for source, target, key, attrs in graph.edges(
        keys=True, data=True
    ):
        export_graph.add_edge(
            source,
            target,
            key=key,
            **{
                str(name): (
                    value if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list, tuple))
                    else str(value)
                )
                for name, value in attrs.items()
                if value is not None
            },
        )

    nx.write_graphml(export_graph, GRAPHML_PATH)


def build_research_insights(
    graph: nx.MultiDiGraph,
    comparisons: list[dict],
) -> dict:
    method_papers = defaultdict(set)
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("node_type") != "method":
            continue
        for source, target, _, edge in graph.in_edges(
            node_id, keys=True, data=True
        ):
            if graph.nodes[source].get("node_type") == "paper":
                method_papers[node_id].add(source)
            elif graph.nodes[source].get("node_type") == "claim":
                paper_id = graph.nodes[source].get("source_paper_id")
                if paper_id:
                    method_papers[node_id].add(paper_id)

    repeated_methods = []
    for method_id, papers in method_papers.items():
        if len(papers) > 1:
            repeated_methods.append({
                "method_id": method_id,
                "method": graph.nodes[method_id].get("name"),
                "paper_ids": sorted(papers),
                "paper_count": len(papers),
            })

    potential_contradictions = []
    for source, target, _, attrs in graph.edges(
        keys=True, data=True
    ):
        if attrs.get("relationship") == "POTENTIAL_CONTRADICTION":
            potential_contradictions.append({
                "claim_a": source,
                "claim_b": target,
                "reason": attrs.get("reason", ""),
                "confidence": attrs.get("confidence", ""),
                "status": "AI_SUGGESTED_NOT_VERIFIED",
            })

    return {
        "repeated_methods": repeated_methods,
        "similar_cross_paper_claims": comparisons,
        "potential_contradictions": potential_contradictions,
        "research_gaps": [],
        "ai_generated_hypotheses": [],
        "suggested_experiments": [],
        "notice": (
            "Research gaps, generated hypotheses and suggested experiments "
            "are left empty until a dedicated evidence-grounded discovery "
            "stage is implemented. The graph builder does not invent them."
        ),
    }


# ---------------------------------------------------------------------------
# PREMIUM ANIMATED HTML VIEWER
# ---------------------------------------------------------------------------

_VIEWER_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Alethia · Knowledge Graph</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
:root{
  --bg:#070b14; --bg2:#0d1424; --glass:rgba(16,24,42,.62); --line:rgba(160,185,255,.14);
  --text:#e8edf8; --muted:#8a97b4; --accent:#7c9cff;
  --ease:cubic-bezier(.22,1,.36,1);
}
*{box-sizing:border-box;margin:0}
html,body{height:100%;background:var(--bg);color:var(--text);
  font:14px/1.5 Manrope,system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}
#stage{position:fixed;inset:0;
  background:radial-gradient(1200px 800px at 70% 20%,#12204a 0%,transparent 60%),
             radial-gradient(900px 700px at 10% 90%,#1a1140 0%,transparent 55%),var(--bg)}
#graph{position:absolute;inset:0;opacity:0;transition:opacity 1.2s var(--ease)}
body.ready #graph{opacity:1}
.glass{background:var(--glass);backdrop-filter:blur(18px) saturate(1.4);
  -webkit-backdrop-filter:blur(18px) saturate(1.4);border:1px solid var(--line);
  border-radius:16px;box-shadow:0 20px 60px -20px rgba(0,0,0,.6)}

/* top bar */
#top{position:fixed;top:16px;left:16px;right:16px;display:flex;gap:12px;align-items:center;z-index:10;pointer-events:none}
#top>*{pointer-events:auto}
#brand{display:flex;align-items:center;gap:10px;padding:10px 16px;font-weight:800;letter-spacing:.2px}
#brand i{width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg,#7c9cff,#c084fc);
  box-shadow:0 0 18px #7c9cffaa}
#brand small{font-weight:500;color:var(--muted)}
#searchbox{position:relative;flex:1;max-width:520px}
#search{width:100%;padding:12px 16px 12px 42px;border-radius:14px;border:1px solid var(--line);
  background:var(--glass);backdrop-filter:blur(18px);color:var(--text);font:inherit;outline:none;
  transition:border-color .3s,box-shadow .3s}
#search:focus{border-color:var(--accent);box-shadow:0 0 0 4px rgba(124,156,255,.18)}
#searchbox svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);opacity:.6}
#results{position:absolute;top:calc(100% + 8px);left:0;right:0;padding:6px;display:none;max-height:340px;overflow:auto}
#results.open{display:block;animation:pop .28s var(--ease)}
.res{display:flex;gap:10px;align-items:center;padding:9px 10px;border-radius:10px;cursor:pointer}
.res:hover,.res.active{background:rgba(124,156,255,.14)}
.res span.t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
#stats{margin-left:auto;padding:10px 16px;color:var(--muted);display:flex;gap:16px;font-weight:600}
#stats b{color:var(--text);font-weight:700}

/* filters */
#filters{position:fixed;left:16px;bottom:16px;z-index:10;padding:8px;display:flex;gap:6px;flex-wrap:wrap;max-width:calc(100vw - 32px)}
.chip{display:flex;align-items:center;gap:8px;padding:7px 12px;border-radius:999px;border:1px solid transparent;
  background:transparent;color:var(--text);font:inherit;font-weight:600;cursor:pointer;
  transition:background .25s,opacity .25s,transform .25s var(--ease)}
.chip:hover{background:rgba(255,255,255,.07);transform:translateY(-1px)}
.chip.off{opacity:.38}
.chip em{font-style:normal;color:var(--muted);font-weight:500}

/* controls */
#ctrl{position:fixed;right:16px;bottom:16px;z-index:10;display:flex;flex-direction:column;gap:6px;padding:6px;transition:right .5s var(--ease)}
#ctrl button{width:38px;height:38px;border-radius:10px;border:0;background:transparent;color:var(--text);
  font-size:18px;cursor:pointer;transition:background .2s}
#ctrl button:hover{background:rgba(255,255,255,.09)}
body.open #ctrl{right:416px}

/* details drawer */
#drawer{position:fixed;top:16px;right:16px;bottom:16px;width:384px;z-index:11;padding:22px;overflow:auto;
  transform:translateX(calc(100% + 32px));opacity:0;transition:transform .6s var(--ease),opacity .4s}
body.open #drawer{transform:none;opacity:1}
#drawer .pill{display:inline-flex;align-items:center;gap:8px;padding:5px 11px;border-radius:999px;
  background:rgba(255,255,255,.07);font-weight:700;font-size:12px}
#drawer h2{font-size:19px;line-height:1.35;margin:14px 0 6px;font-weight:700}
#drawer .quote{margin:10px 0;padding:12px 14px;border-radius:12px;background:rgba(255,255,255,.05);
  border-left:3px solid var(--c,var(--accent));color:#cfd8ee}
#drawer dl{display:grid;grid-template-columns:110px 1fr;gap:10px 14px;margin:16px 0}
#drawer dt{color:var(--muted);font-weight:600}
#drawer dd{overflow-wrap:anywhere}
#drawer h4{margin:22px 0 8px;font-size:13px;color:var(--muted);font-weight:700}
.bar{height:6px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;width:0;border-radius:6px;background:var(--c,var(--accent));transition:width 1s var(--ease)}
.link{display:flex;gap:10px;align-items:flex-start;padding:9px 10px;margin:0 -10px;border-radius:10px;cursor:pointer;
  transition:background .2s,transform .3s var(--ease)}
.link:hover{background:rgba(124,156,255,.13);transform:translateX(3px)}
.link small{display:block;color:var(--muted);font-weight:600;font-size:11px}
.link .t{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#close{position:absolute;top:16px;right:16px;width:32px;height:32px;border-radius:50%;border:0;
  background:rgba(255,255,255,.08);color:var(--text);cursor:pointer;transition:transform .3s var(--ease),background .2s}
#close:hover{background:rgba(255,255,255,.16);transform:rotate(90deg)}

/* loader */
#loader{position:fixed;inset:0;z-index:50;display:grid;place-items:center;background:var(--bg);
  transition:opacity .9s var(--ease),visibility .9s}
body.ready #loader{opacity:0;visibility:hidden}
#loader .box{text-align:center}
#loader .orb{width:64px;height:64px;margin:0 auto 22px;border-radius:50%;
  background:conic-gradient(from 0deg,#7c9cff,#c084fc,#34d399,#7c9cff);
  -webkit-mask:radial-gradient(circle 24px,transparent 98%,#000 100%);mask:radial-gradient(circle 24px,transparent 98%,#000 100%);
  animation:spin 1.6s linear infinite}
#loader p{color:var(--muted);font-weight:600}
#loader .track{width:220px;height:3px;border-radius:3px;background:rgba(255,255,255,.08);margin:14px auto 0;overflow:hidden}
#loader .track i{display:block;height:100%;width:0;background:linear-gradient(90deg,#7c9cff,#c084fc);transition:width .2s}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pop{from{opacity:0;transform:translateY(-6px) scale(.98)}}
.vis-tooltip{background:#111a2e!important;color:var(--text)!important;border:1px solid var(--line)!important;
  border-radius:10px!important;font:13px Manrope,sans-serif!important;padding:8px 10px!important;max-width:320px;white-space:normal!important}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:760px){#drawer{left:16px;width:auto;top:auto;height:55vh}body.open #ctrl{right:16px}#stats,#brand small{display:none}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<div id="stage"><div id="graph"></div></div>

<div id="loader"><div class="box"><div class="orb"></div><p>Mapping the research graph</p>
<div class="track"><i id="prog"></i></div></div></div>

<div id="top">
  <div id="brand" class="glass"><i></i>Alethia <small>Knowledge graph</small></div>
  <div id="searchbox">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    <input id="search" placeholder="Search papers, claims, methods…  ( / )" autocomplete="off" aria-label="Search the graph">
    <div id="results" class="glass"></div>
  </div>
  <div id="stats" class="glass"><span><b id="sn">0</b> nodes</span><span><b id="se">0</b> links</span></div>
</div>

<div id="filters" class="glass"></div>
<div id="ctrl" class="glass">
  <button id="zin" title="Zoom in" aria-label="Zoom in">+</button>
  <button id="zout" title="Zoom out" aria-label="Zoom out">−</button>
  <button id="fit" title="Fit to screen" aria-label="Fit to screen">⤢</button>
  <button id="phys" title="Pause or resume motion" aria-label="Toggle motion">❚❚</button>
</div>

<aside id="drawer" class="glass" aria-live="polite"></aside>

<script>
const DATA = __DATA__;
const COLORS = {paper:"#6d8dff",claim:"#34d399",evidence:"#fbbf24",method:"#a78bfa",concept:"#22d3ee",
  entity:"#94a3b8",dataset:"#f472b6",model:"#fb923c",algorithm:"#facc15",hypothesis:"#e879f9"};
const TYPE_NAMES = {paper:"Papers",claim:"Claims",evidence:"Evidence",method:"Methods",concept:"Concepts",
  entity:"Entities",dataset:"Datasets",model:"Models",algorithm:"Algorithms",hypothesis:"Hypotheses"};
const EDGE_COLORS = {SUPPORTS:"#34d399",POTENTIAL_SUPPORT:"#34d399",INSUFFICIENT:"#fbbf24"};
const edgeColor = r => EDGE_COLORS[r] || (/CONTRADICT/.test(r) ? "#f87171" : "#8aa0cf");
const col = t => COLORS[t] || "#94a3b8";
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const byId = new Map(DATA.nodes.map(n => [n.id, n]));
const adj = new Map(DATA.nodes.map(n => [n.id, []]));
DATA.edges.forEach(e => { adj.get(e.from).push(e); adj.get(e.to).push(e); });

const ALWAYS_LABEL = new Set(["paper","method","model","algorithm","dataset","hypothesis","concept"]);
let zoomedIn = false, focusId = null, hidden = new Set();

const nodes = new vis.DataSet(DATA.nodes.map(n => {
  const c = col(n.type), deg = adj.get(n.id).length;
  return {id:n.id, label:"", shape:"dot",
    size: n.type==="paper" ? 30 : Math.min(8 + Math.sqrt(deg)*3, 24),
    color:{background:c, border:c, highlight:{background:"#fff",border:c}, hover:{background:"#fff",border:c}},
    borderWidth:1.5, shadow:{enabled:true,color:c+"99",size:n.type==="paper"?32:16,x:0,y:0},
    font:{color:"#dfe6f5",size:n.type==="paper"?17:13,face:"Manrope",strokeWidth:5,strokeColor:"#070b14"},
    title:n.tip, opacity:1};
}));
const edges = new vis.DataSet(DATA.edges.map((e,i) => ({
  id:i, from:e.from, to:e.to, title:e.reason || e.rel.replaceAll("_"," ").toLowerCase(),
  color:{color:edgeColor(e.rel),opacity:.28}, width:.9,
  arrows:{to:{enabled:true,scaleFactor:.35}}, smooth:{type:"continuous"}, font:{size:0}
})));

const network = new vis.Network($("graph"), {nodes, edges}, {
  interaction:{hover:true,tooltipDelay:200,hideEdgesOnDrag:true,zoomSpeed:.7},
  physics:{solver:"forceAtlas2Based",
    forceAtlas2Based:{gravitationalConstant:-60,centralGravity:.008,springLength:130,springConstant:.06,damping:.5,avoidOverlap:.4},
    stabilization:{iterations:280,updateInterval:20}},
  nodes:{scaling:{label:false}}, edges:{selectionWidth:2}
});

$("sn").textContent = DATA.nodes.length; $("se").textContent = DATA.edges.length;

/* ---------- labels ---------- */
function labelFor(n, force){
  const show = force || ALWAYS_LABEL.has(n.type) || (n.type==="claim" && zoomedIn);
  return show ? n.short : "";
}
function refreshLabels(){
  const near = focusId ? new Set([focusId, ...adj.get(focusId).flatMap(e => [e.from,e.to])]) : null;
  nodes.update(DATA.nodes.map(n => ({id:n.id, label:labelFor(n, near && near.has(n.id))})));
}

/* ---------- load sequence ---------- */
network.on("stabilizationProgress", p => { $("prog").style.width = (p.iterations/p.total*100)+"%"; });
network.once("stabilizationIterationsDone", () => {
  $("prog").style.width = "100%";
  refreshLabels();
  setTimeout(() => {
    document.body.classList.add("ready");
    network.fit({animation: REDUCED ? false : {duration:1400, easingFunction:"easeInOutCubic"}});
    if (DATA.nodes.length > 500) { network.setOptions({physics:false}); $("phys").textContent="▶"; }
  }, 250);
});
let zt; network.on("zoom", () => { clearTimeout(zt); zt = setTimeout(() => {
  const z = network.getScale() > .75; if (z !== zoomedIn){ zoomedIn = z; refreshLabels(); } }, 120); });

/* ---------- focus & highlight ---------- */
function highlight(id){
  focusId = id;
  const keep = id ? new Set([id, ...adj.get(id).flatMap(e => [e.from,e.to])]) : null;
  nodes.update(DATA.nodes.map(n => ({id:n.id, opacity: !keep || keep.has(n.id) ? 1 : .08})));
  edges.update(DATA.edges.map((e,i) => {
    const on = id && (e.from===id || e.to===id);
    return {id:i, width:on?2.2:.9, color:{color:edgeColor(e.rel),opacity: !id ? .28 : on ? .95 : .04},
            font: on ? {size:11,color:"#cdd7ee",strokeWidth:4,strokeColor:"#070b14",align:"middle"} : {size:0},
            label: on ? e.rel.replaceAll("_"," ").toLowerCase() : ""};
  }));
  refreshLabels();
}
function flyTo(id){
  network.selectNodes([id]); select(id);
  network.focus(id, {scale:Math.max(network.getScale(),1), animation: REDUCED ? false : {duration:900,easingFunction:"easeInOutCubic"}});
}

/* ---------- drawer ---------- */
const SKIP = new Set(["id","label","node_type","source_paper_id","claim_link_status","article_key"]);
const LONG = ["sentence","normalized_claim","original_text","abstract","description","reason"];
function select(id){
  const n = byId.get(id); if (!n) return;
  const c = col(n.type), d = n.details;
  const head = d.title || d.name || d.normalized_claim || d.sentence || n.short;
  let h = `<button id="close" aria-label="Close">✕</button>
    <span class="pill"><span class="dot" style="background:${c}"></span>${esc(TYPE_NAMES[n.type]||n.type).replace(/s$/,"")}</span>
    <h2>${esc(head.length>160?head.slice(0,160)+"…":head)}</h2>`;
  const shown = new Set(["title","name"]);
  LONG.forEach(k => { if (d[k] && d[k]!==head){ h += `<div class="quote" style="--c:${c}"><small style="color:var(--muted);font-weight:700">${esc(k.replaceAll("_"," "))}</small><br>${esc(d[k])}</div>`; }
    shown.add(k); });
  let rows = "";
  Object.entries(d).forEach(([k,v]) => {
    if (SKIP.has(k) || shown.has(k) || v==="" || v==null) return;
    let val = esc(typeof v==="object" ? JSON.stringify(v) : v);
    if ((k==="strength"||k==="similarity"||k.endsWith("confidence")) && !isNaN(parseFloat(v)))
      val = `${(parseFloat(v)*100).toFixed(0)}%<div class="bar"><i data-w="${parseFloat(v)*100}" style="--c:${c}"></i></div>`;
    rows += `<dt>${esc(k.replaceAll("_"," "))}</dt><dd>${val}</dd>`;
  });
  if (rows) h += `<dl>${rows}</dl>`;
  if (d.source_paper_id && byId.has(d.source_paper_id)){
    const p = byId.get(d.source_paper_id);
    h += `<h4>Source paper</h4><div class="link" data-id="${esc(p.id)}"><span class="dot" style="background:${col("paper")};margin-top:7px"></span><span class="t">${esc(p.short)}</span></div>`;
  }
  const links = adj.get(id);
  if (links.length){
    h += `<h4>Connections (${links.length})</h4>`;
    links.slice(0,60).forEach(e => {
      const o = byId.get(e.from===id ? e.to : e.from);
      h += `<div class="link" data-id="${esc(o.id)}"><span class="dot" style="background:${col(o.type)};margin-top:7px"></span>
        <span><small>${esc(e.rel.replaceAll("_"," ").toLowerCase())}${e.from===id?" →":" ←"}</small><span class="t">${esc(o.short)}</span></span></div>`;
    });
    if (links.length>60) h += `<small style="color:var(--muted)">+ ${links.length-60} more</small>`;
  }
  const dr = $("drawer"); dr.innerHTML = h; dr.scrollTop = 0;
  document.body.classList.add("open");
  requestAnimationFrame(() => dr.querySelectorAll(".bar i").forEach(b => b.style.width = b.dataset.w+"%"));
  highlight(id);
}
function deselect(){ document.body.classList.remove("open"); network.unselectAll(); highlight(null); }
$("drawer").addEventListener("click", e => {
  if (e.target.closest("#close")) return deselect();
  const l = e.target.closest(".link"); if (l) flyTo(l.dataset.id);
});
network.on("click", p => p.nodes.length ? select(p.nodes[0]) : deselect());
network.on("hoverNode", () => $("graph").style.cursor = "pointer");
network.on("blurNode", () => $("graph").style.cursor = "default");

/* ---------- search ---------- */
const hay = DATA.nodes.map(n => ({n, s:(n.short+" "+Object.values(n.details).join(" ")).toLowerCase()}));
let act = -1, found = [];
function runSearch(){
  const q = $("search").value.trim().toLowerCase(), box = $("results");
  if (q.length < 2){ box.classList.remove("open"); return; }
  found = hay.filter(h => h.s.includes(q)).sort((a,b) =>
      (b.n.short.toLowerCase().includes(q)) - (a.n.short.toLowerCase().includes(q))).slice(0,8).map(h => h.n);
  act = found.length ? 0 : -1;
  box.innerHTML = found.length ? found.map((n,i) => `<div class="res ${i?"":"active"}" data-id="${esc(n.id)}">
    <span class="dot" style="background:${col(n.type)}"></span><span class="t">${esc(n.short)}</span></div>`).join("")
    : `<div class="res" style="color:var(--muted)">No matches. Try a method, claim or paper title.</div>`;
  box.classList.add("open");
}
$("search").addEventListener("input", runSearch);
$("search").addEventListener("keydown", e => {
  const items = [...$("results").querySelectorAll(".res[data-id]")];
  if (e.key==="ArrowDown"||e.key==="ArrowUp"){ e.preventDefault();
    act = (act + (e.key==="ArrowDown"?1:-1) + items.length) % (items.length||1);
    items.forEach((x,i) => x.classList.toggle("active", i===act)); }
  if (e.key==="Enter" && found[act]){ flyTo(found[act].id); $("results").classList.remove("open"); $("search").blur(); }
  if (e.key==="Escape"){ $("results").classList.remove("open"); $("search").blur(); }
});
$("results").addEventListener("click", e => { const r = e.target.closest(".res[data-id]");
  if (r){ flyTo(r.dataset.id); $("results").classList.remove("open"); } });
addEventListener("keydown", e => {
  if (e.key==="/" && document.activeElement!==$("search")){ e.preventDefault(); $("search").focus(); }
  else if (e.key==="Escape") deselect();
});

/* ---------- filters ---------- */
const counts = {}; DATA.nodes.forEach(n => counts[n.type] = (counts[n.type]||0)+1);
Object.keys(counts).sort((a,b) => counts[b]-counts[a]).forEach(t => {
  const b = document.createElement("button"); b.className = "chip";
  b.innerHTML = `<span class="dot" style="background:${col(t)}"></span>${esc(TYPE_NAMES[t]||t)} <em>${counts[t]}</em>`;
  b.onclick = () => { hidden.has(t) ? hidden.delete(t) : hidden.add(t); b.classList.toggle("off", hidden.has(t));
    nodes.update(DATA.nodes.filter(n => n.type===t).map(n => ({id:n.id, hidden:hidden.has(t)}))); };
  $("filters").appendChild(b);
});

/* ---------- controls ---------- */
const anim = {duration:500,easingFunction:"easeInOutCubic"};
$("zin").onclick  = () => network.moveTo({scale:network.getScale()*1.4, animation:anim});
$("zout").onclick = () => network.moveTo({scale:network.getScale()/1.4, animation:anim});
$("fit").onclick  = () => network.fit({animation:{duration:900,easingFunction:"easeInOutCubic"}});
let moving = true;
$("phys").onclick = () => { moving = !moving; network.setOptions({physics:{enabled:moving}}); $("phys").textContent = moving ? "❚❚" : "▶"; };
</script>
</body>
</html>
"""


def export_interactive_html(graph: nx.MultiDiGraph) -> None:
    """Premium, self-contained interactive viewer (vis-network, glass UI)."""
    selected_nodes = list(graph.nodes())
    if len(selected_nodes) > MAX_HTML_NODES:
        priority = {
            "paper": 0, "claim": 1, "method": 2, "dataset": 2, "model": 2,
            "algorithm": 2, "concept": 2, "entity": 3, "hypothesis": 3,
            "evidence": 4,
        }
        selected_nodes.sort(key=lambda n: (
            priority.get(graph.nodes[n].get("node_type"), 9),
            -graph.degree(n), n))
        selected_nodes = selected_nodes[:MAX_HTML_NODES]
        logger.warning(
            "HTML view capped at %s nodes; full graph remains in JSON/GraphML.",
            MAX_HTML_NODES,
        )
    selected = set(selected_nodes)

    def short(text: str, limit: int = 60) -> str:
        text = " ".join(str(text).split())
        return text if len(text) <= limit else text[:limit].rstrip() + "…"

    node_rows = []
    for node_id in selected_nodes:
        attrs = graph.nodes[node_id]
        node_type = attrs.get("node_type", "unknown")
        details = {
            k: json_safe(v) for k, v in attrs.items()
            if v not in (None, "", [], {})
        }
        # authors are stored as a JSON string; make them readable
        if "authors" in details:
            try:
                details["authors"] = ", ".join(json.loads(details["authors"]))
            except (TypeError, ValueError):
                pass
        label = attrs.get("label") or node_id
        node_rows.append({
            "id": node_id,
            "type": node_type,
            "short": short(label),
            "tip": short(attrs.get("normalized_claim") or attrs.get("sentence")
                         or attrs.get("title") or label, 220),
            "details": details,
        })

    edge_rows = []
    for source, target, _, attrs in graph.edges(keys=True, data=True):
        if source in selected and target in selected:
            edge_rows.append({
                "from": source,
                "to": target,
                "rel": str(attrs.get("relationship", "RELATED_TO")),
                "reason": short(attrs.get("reason") or "", 240),
            })

    payload = json.dumps(
        {"nodes": node_rows, "edges": edge_rows}, ensure_ascii=False
    ).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    HTML_PATH.write_text(
        _VIEWER_TEMPLATE.replace("__DATA__", payload), encoding="utf-8"
    )
    logger.info("Premium interactive viewer written to %s", HTML_PATH)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> nx.MultiDiGraph:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Building Alethia knowledge graph...")

    graph, report = build_graph()

    logger.info(
        "Created %s nodes and %s edges.",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )

    comparisons = compare_cross_paper_claims(graph)

    export_graph_json(graph)
    export_graphml(graph)
    export_interactive_html(graph)

    insights = build_research_insights(graph, comparisons)
    with INSIGHTS_PATH.open("w", encoding="utf-8") as file:
        json.dump(insights, file, indent=2, ensure_ascii=False)

    report.update({
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "cross_paper_similarity_candidates": len(comparisons),
        "llm_cross_paper_enabled": ENABLE_LLM_CROSS_PAPER,
        "outputs": {
            "graphml": str(GRAPHML_PATH),
            "json": str(GRAPH_JSON_PATH),
            "html": str(HTML_PATH),
            "insights": str(INSIGHTS_PATH),
        },
    })

    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    logger.info("Knowledge graph construction completed.")
    logger.info("Output directory: %s", OUTPUT_DIR)

    return graph


if __name__ == "__main__":
    main()
