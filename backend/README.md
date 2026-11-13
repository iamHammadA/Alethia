# Alethia API

From the repository root:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
ollama pull llama3.2
uvicorn backend.app.main:app --reload
```

Set `OPENROUTER_API_KEY` in the environment before starting a new research run. Ollama must be running locally for evidence analysis.

The API serves the existing generated graph from `arXiv papers/knowledge_graph/` and exposes endpoints for the dashboard, graph, papers, claims, exports, and background research jobs.

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/graph`
- `GET /api/papers`
- `GET /api/claims`
- `POST /api/research`
- `GET /api/jobs/{job_id}`

The pipeline is CPU/network intensive and currently runs one investigation at a time. Do not expose this development API publicly without authentication, rate limits, and job persistence.
