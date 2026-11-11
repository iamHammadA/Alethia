
# Alethia — Architecture Decision Records

This document records the major technical and architectural decisions made during the development of Alethia.

It explains the reasoning behind the technologies, processing strategies, data representations, and design choices used in the project.

The purpose is to preserve the reasoning behind the current implementation and provide context for future architectural changes.

**Project:** Alethia  
**Author:** Hammad A.  
**Version:** 1.0  
**Status:** Version 1 decisions

---

## Decision 001 — Python as the Primary Programming Language

**Status:** Accepted

### Context

Alethia requires scientific document processing, natural language processing, machine learning utilities, LLM integration, and graph construction.

These tasks require a flexible ecosystem of libraries and tools.

### Decision

Python was selected as the primary programming language for the project.

### Rationale

Python provides access to established libraries for:

- Natural Language Processing
- Machine learning
- Scientific computing
- PDF processing
- Graph construction
- API integration
- LLM inference

It also allows different components to be developed independently while remaining part of a unified system.

### Consequences

- The core processing pipeline uses Python.
- Components share data through structured JSON representations.
- The project can integrate with a broad range of AI and scientific computing libraries.

---

## Decision 002 — arXiv as the Initial Research Paper Source

**Status:** Accepted

### Context

Alethia requires scientific research papers as its primary input.

A consistent source of research material was necessary to develop and test the initial pipeline.

### Decision

The arXiv API was selected as the initial paper retrieval source.

### Rationale

arXiv provides programmatic access to scientific papers and their metadata, making it suitable for automated research retrieval.

### Consequences

- The initial retrieval component is built around arXiv.
- Paper metadata and downloadable PDFs become inputs to the extraction pipeline.
- Supporting additional research repositories remains a possible future extension.

---

## Decision 003 — PDF-to-Markdown Extraction

**Status:** Accepted

### Context

Scientific papers are commonly distributed as PDF documents.

Directly processing PDF files throughout the pipeline would make subsequent NLP operations more difficult.

### Decision

PyMuPDF4LLM was selected to extract PDF content into Markdown-oriented text.

### Rationale

A text representation makes scientific documents easier to process using NLP and LLM-based components.

Markdown-oriented extraction also provides a more structured representation than treating the entire document as undifferentiated text.

### Consequences

- PDF extraction is separated from claim analysis.
- Downstream components operate on extracted textual content.
- Extraction quality remains dependent on the structure and quality of the original PDF.

---

## Decision 004 — Hybrid NLP and LLM-Based Claim Processing

**Status:** Accepted

### Context

Scientific claims are expressed using varied sentence structures, terminology, and writing styles.

Traditional NLP techniques can help identify and process sentences, but interpreting their scientific meaning can require contextual reasoning.

### Decision

Alethia combines traditional NLP with LLM-based claim analysis.

The implementation uses spaCy and NLTK for text processing and an LLM accessed through OpenRouter for semantic analysis.

### Rationale

The two approaches serve different purposes:

- Traditional NLP supports sentence processing and linguistic analysis.
- LLM-based analysis helps interpret scientific statements.
- Structured outputs make claims easier to process in later stages.

### Consequences

- Claim extraction and claim interpretation are separate operations.
- Claims can be represented using structured fields such as subject, relation, object, claim type, and evidence requirements.
- LLM output requires structured parsing and validation.

---

## Decision 005 — Explicit Claim Normalization

**Status:** Accepted

### Context

Different research papers may express similar scientific findings using different terminology or sentence structures.

Without normalization, comparing claims across papers becomes more difficult.

### Decision

A separate claim normalization component was introduced.

### Rationale

Separating normalization from extraction allows the system to standardize claims without coupling every operation to the initial extraction process.

### Consequences

- Normalized claims provide a more consistent representation for downstream processing.
- Cross-paper comparisons can operate on standardized claim information.
- Normalization quality influences subsequent retrieval and graph relationships.

---

## Decision 006 — TF-IDF and Cosine Similarity for Evidence Retrieval

**Status:** Accepted

### Context

Every extracted claim may have multiple potentially relevant passages within its source paper.

The system needs a retrieval mechanism to identify candidate evidence before semantic classification.

### Decision

TF-IDF vectorization and cosine similarity were selected for the initial evidence retrieval implementation.

The retriever selects a limited number of candidate passages using similarity rankings.

### Rationale

This approach provides a computationally straightforward method for identifying textually relevant passages.

It also avoids requiring a separate embedding model for the initial retrieval pipeline.

### Consequences

- Evidence retrieval is based on textual similarity.
- Candidate passages are ranked before AI-based evidence analysis.
- Semantically relevant passages with different wording may be missed.
- Similarity alone is not treated as proof that evidence supports a claim.

More advanced semantic retrieval methods may be evaluated in future versions.

---

## Decision 007 — Local LLM Inference for Evidence Analysis

**Status:** Accepted

### Context

Evidence analysis requires examining the semantic relationship between a scientific claim and a retrieved passage.

This operation involves contextual interpretation rather than simple text similarity.

### Decision

Ollama was selected as the local inference interface for evidence analysis.

The initial implementation uses a locally available model, with `llama3.2` as its configured default.

### Rationale

Local inference provides an alternative to sending every evidence-analysis request to a remote API.

It also allows the model to be changed independently of the evidence retrieval component.

### Consequences

- Evidence analysis can run locally.
- Model availability and hardware resources affect execution.
- Different local models may produce different classifications.
- Model outputs should not be interpreted as independently verified scientific judgments.

---

## Decision 008 — Four-Way Evidence Relationship Classification

**Status:** Accepted

### Context

A retrieved passage is not necessarily supportive of the claim for which it was retrieved.

The system therefore requires a way to distinguish different relationships between claims and candidate evidence.

### Decision

Alethia uses four evidence relationship categories:

| Classification | Meaning |
|---|---|
| `supports` | The passage supports the claim. |
| `contradicts` | The passage conflicts with the claim. |
| `insufficient` | The passage does not provide enough information to establish the relationship. |
| `irrelevant` | The passage is not meaningfully related to the claim. |

The evidence analyzer also records similarity, strength, and a textual explanation.

### Rationale

A multi-category classification provides more information than a binary relevant/irrelevant decision.

In particular, distinguishing contradictory evidence from irrelevant evidence is important when representing scientific findings.

### Consequences

- Evidence relationships can be represented explicitly in the knowledge graph.
- The system can preserve distinctions between supporting, conflicting, and inconclusive evidence.
- Classification quality depends on the model and the quality of the input passages.

---

## Decision 009 — Filtering Evidence Before Graph Construction

**Status:** Accepted — Initial thresholds are provisional

### Context

The evidence analyzer may return passages with different relevance scores, relationship classifications, and evidence strengths.

Not every analyzed passage should automatically become a supporting relationship in the knowledge graph.

### Decision

A separate claim-evidence linking stage filters analyzed evidence before linking it to claims.

The current supporting-evidence selection criteria are:

- Similarity score greater than or equal to `0.1`.
- Relationship classified as `supports`.
- Evidence strength greater than or equal to `0.3`.

### Rationale

Filtering separates evidence analysis from graph construction.

It also prevents every retrieved candidate from being treated as an accepted supporting relationship.

### Consequences

- The graph receives filtered supporting-evidence relationships.
- The thresholds influence graph density and the amount of evidence retained.
- These values are implementation parameters, not scientifically validated universal thresholds.
- Changing them may affect the resulting graph and its insights.

Future versions should evaluate these thresholds against manually assessed evidence.

---

## Decision 010 — NetworkX Directed Multigraph for Knowledge Representation

**Status:** Accepted

### Context

Scientific knowledge involves multiple types of entities and relationships.

A simple list of extracted claims cannot adequately represent connections between papers, claims, evidence, methodologies, datasets, and other scientific concepts.

### Decision

NetworkX was selected to construct a directed multigraph.

### Rationale

A directed multigraph supports:

- Multiple node categories.
- Typed relationships.
- Directed connections.
- Multiple relationships between the same pair of nodes.
- Flexible graph traversal and analysis.

This representation is suitable for modeling interconnected scientific information.

### Consequences

- Scientific information is represented as nodes and edges.
- Relationships retain their types and directions.
- The graph can be exported into external graph formats.
- Graph construction and analysis can evolve independently of PDF extraction.

---

## Decision 011 — Typed Scientific Nodes and Relationships

**Status:** Accepted

### Context

Representing every extracted item as a generic node would make the graph less informative.

Scientific papers contain different kinds of information that have distinct meanings and relationships.

### Decision

Alethia uses specialized node categories, including:

- Paper
- Claim
- Evidence
- Method
- Algorithm
- Model
- Dataset
- Concept
- Entity
- Hypothesis

It also uses typed relationships such as `SUPPORTS`, `CONTRADICTS`, `USES_METHOD`, `EVALUATES_ON`, and `INTRODUCES`.

### Rationale

Typed nodes and edges preserve semantic distinctions within the graph.

They also make it possible to explore specific kinds of scientific relationships instead of treating every connection identically.

### Consequences

- Graph traversal can distinguish between different relationship types.
- The visualization can present more meaningful connections.
- New node and relationship categories can be introduced as the system expands.

---

## Decision 012 — Deterministic Identifiers Using SHA-256

**Status:** Accepted

### Context

Graph construction requires stable identifiers for nodes and relationships.

Uncontrolled identifier generation could create duplicate nodes or make it difficult to maintain consistent references.

### Decision

SHA-256-based deterministic identifiers are used for graph elements.

### Rationale

Deterministic identifiers allow the same underlying input to produce a reproducible identifier, provided the identifier-generation inputs and procedure remain unchanged.

### Consequences

- Graph elements can be referenced consistently.
- Repeated processing can reduce unnecessary duplication.
- Identifier generation depends on the consistency of the underlying input representation.

---

## Decision 013 — Evidence Deduplication with Provenance Preservation

**Status:** Accepted

### Context

The same evidence passage may be encountered more than once during graph construction.

Creating unnecessary duplicate evidence nodes would make the graph harder to interpret.

However, removing duplicates without preserving their origins could result in lost research context.

### Decision

Alethia implements evidence deduplication within individual papers while retaining provenance information.

### Rationale

Deduplication reduces redundant graph information, while provenance preserves the connection between evidence and its source.

### Consequences

- Repeated evidence within a paper can be consolidated.
- Source information remains available for traceability.
- Deduplication does not imply that different papers have identical scientific contexts.

---

## Decision 014 — Similarity-Based Cross-Paper Relationship Discovery

**Status:** Accepted

### Context

The knowledge graph should not be limited to relationships within individual papers.

Information from different papers may describe similar claims, methods, findings, or research problems.

### Decision

Alethia uses TF-IDF and cosine similarity to identify potentially related elements across research papers.

An optional LLM-based comparison stage can further classify potential relationships.

### Rationale

Similarity-based comparison provides an initial mechanism for discovering connections across papers.

LLM-based comparison can add semantic interpretation to candidate relationships.

### Consequences

- The graph can contain cross-paper similarity relationships.
- Optional LLM analysis can suggest more specific relationship categories.
- Suggested relationships are not automatically established scientific facts.
- The optional LLM comparison is disabled by default in the current implementation.

---

## Decision 015 — Multiple Graph Export Formats

**Status:** Accepted

### Context

A knowledge graph should not be restricted to a single visualization or processing environment.

Different users and tools may require different graph representations.

### Decision

Alethia exports graph data into JSON, GraphML, and interactive HTML formats.

### Rationale

Each format serves a different purpose:

- JSON provides a structured representation for programmatic processing.
- GraphML supports interoperability with graph-analysis tools.
- HTML provides a directly accessible interactive visualization.

### Consequences

- Graph data can be inspected outside the main application.
- External tools can consume the exported graph.
- Visualization is separated from graph construction.

---

## Decision 016 — Interactive Graph Visualization with vis-network

**Status:** Accepted

### Context

A large scientific knowledge graph is difficult to understand through raw JSON or GraphML alone.

Users need a way to explore graph elements and relationships visually.

### Decision

vis-network was selected for the browser-based graph visualization.

### Rationale

An interactive network visualization allows users to explore connections rather than relying exclusively on static diagrams.

### Consequences

The current visualization supports:

- Graph exploration
- Node selection
- Node details
- Relationship exploration
- Search
- Entity filtering
- Navigation
- Zooming
- Graph fitting
- Physics-based layout

---

## Decision 017 — JSON as the Intermediate Data Representation

**Status:** Accepted

### Context

The processing pipeline consists of multiple independent stages.

Passing complex Python objects directly between every component would create unnecessary coupling.

### Decision

Structured JSON files are used to store and transfer intermediate processing results.

### Rationale

JSON is readable, widely supported, and suitable for representing the structured outputs produced by NLP and LLM components.

It also allows individual stages to be inspected and rerun without necessarily repeating every previous operation.

### Consequences

- Intermediate results can be inspected independently.
- Components communicate through explicit data structures.
- Changes to JSON schemas must be coordinated across dependent components.
- Data validation is important to prevent malformed outputs from breaking downstream stages.

---

## 18. Decisions Deferred to Future Versions

The following areas have not been established as completed Version 1 capabilities. They remain potential architectural decisions for future development.

| Area | Future consideration |
|---|---|
| Semantic retrieval | Evaluate embedding-based retrieval and reranking. |
| Entity resolution | Improve identification of equivalent scientific entities. |
| Evidence evaluation | Benchmark classification against manually annotated examples. |
| Research discovery | Investigate automated research-gap identification. |
| Hypothesis generation | Explore methods for generating testable research hypotheses. |
| Experiment recommendation | Investigate possible experiment-generation workflows. |
| Scalability | Evaluate graph storage and processing approaches for larger datasets. |
| Evaluation | Establish quantitative metrics for extraction, retrieval, and classification quality. |

These are future possibilities, not implemented features of Version 1.

---

## 19. Closing Statement

Alethia's Version 1 architecture is built around a sequence of explicit technical decisions that combine traditional NLP, information retrieval, LLM-based semantic analysis, and graph-based knowledge representation.

Together, these decisions establish a foundation for processing scientific literature, connecting claims with evidence, and exploring relationships across research papers.

This document should evolve alongside the project. Whenever a significant architectural decision is introduced, changed, or replaced, its reasoning should be recorded here.

**End of Architecture Decision Records — Alethia Version 1.0**
</WritingBlock>