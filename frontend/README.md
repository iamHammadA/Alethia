# Alethia Web

React + TypeScript + Vite interface for the Alethia scientific literature analysis pipeline.

## Development

Start the API from the repository root first:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
ollama pull llama3.2
uvicorn backend.app.main:app --reload
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Vite proxies API calls to http://127.0.0.1:8000. To use another API host, copy `.env.example` to `.env` and set `VITE_API_URL`.

## Production build

```bash
npm run build
npm run preview
```

The frontend includes the overview, interactive knowledge graph, papers library, claims/evidence explorer, and research-run form. The graph and library screens read live API data; they do not use hard-coded sample research records.
