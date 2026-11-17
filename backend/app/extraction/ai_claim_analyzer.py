import json
from .claim_normalizer import main_function
import os
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next(
    (parent for parent in CURRENT_FILE.parents
     if (parent / "backend").is_dir() and (parent / "frontend").is_dir()),
    None,
)
if ROOT_DIR is None:
    raise RuntimeError("Could not locate the Alethia project root.")
SAVE_DIR = ROOT_DIR / "arXiv papers"
CLAIMS_OUTPUT_PATH = SAVE_DIR / "ai_claims.json"


def _save_claims(data: dict) -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = CLAIMS_OUTPUT_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary_path.replace(CLAIMS_OUTPUT_PATH)

def call_openrouter_reasoning(
    claim_input: dict | str, 
    api_key: str | None = None,
    model: str = "baidu/ernie-5.5-flash-preview:free"
) -> dict:
    """
    Analyzes scientific claims using OpenRouter reasoning models,
    returning a structured JSON payload.
    """
    # Fallback to environment variable if api_key is not explicitly passed
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("Missing OpenRouter API key. Pass it as an argument or set OPENROUTER_API_KEY.")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/aletheia-research", # Optional for OpenRouter stats
        "X-Title": "Aletheia Claim Analyzer"
    }

    system_instruction = """You are the Claim Analysis module of Aletheia, an AI system for analyzing scientific research papers.
Analyze the candidate claim and output a single, valid JSON object matching this schema:

{
    "normalized_claim": "Clear concise scientific statement",
    "subject": "Entity performing relation",
    "relation": "Central canonical active verb",
    "object": "Target entity or benchmark",
    "claim_type": "One of: ['method', 'result', 'comparison', 'finding', 'hypothesis', 'theoretical', 'dataset', 'limitation', 'conclusion', 'other']",
    "requires_evidence": true | false,
    "confidence": 0.0 to 1.0
}
Output ONLY valid JSON. No conversational fluff or markdown formatting outside the JSON."""

    prompt = f"Analyze and normalize this extracted claim input:\n{json.dumps(claim_input, indent=2)}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ],
        "reasoning": {"enabled": True},
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        data=json.dumps(payload),
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(f"OpenRouter API Error [{response.status_code}]: {response.text}")

    res_data = response.json()
    raw_content = res_data["choices"][0]["message"]["content"]

    # Parse and return JSON object
    return json.loads(raw_content)

def analyzer(progress=None):
    """Analyze normalized claims and persist partial results for the live UI."""
    json_claims = main_function()
    ai_claims = {}
    total_claims = sum(len(items) for items in json_claims.values())
    completed = 0
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    # Publish locally extracted claims before any remote model request. If
    # model quota is exhausted, the Claims page still shows extracted claims.
    for article_id, claims_list in json_claims.items():
        ai_claims[article_id] = [
            {
                **single_claim,
                "original_text": single_claim.get("text", ""),
                "normalized_claim": single_claim.get("text", ""),
                "source_paper_id": article_id,
                "article_key": article_id,
                "analysis_status": "pending",
            }
            for single_claim in claims_list
        ]
    _save_claims(ai_claims)

    if progress:
        progress("claims", 25, f"Extracted {total_claims} candidate claims. Starting claim analysis.")

    for article_id, claims_list in json_claims.items():
        print(f"Article {article_id} Claims Count:", len(claims_list))
        for index, single_claim in enumerate(claims_list):
            analyzed_claim = call_openrouter_reasoning(single_claim, api_key=openrouter_key)
            enriched_claim = {
                **single_claim,
                **analyzed_claim,
                "original_text": single_claim.get("text", ""),
                "source_paper_id": article_id,
                "article_key": article_id,
                "analysis_status": "complete",
            }
            ai_claims[article_id][index] = enriched_claim
            completed += 1
            _save_claims(ai_claims)
            if progress:
                percent = 25 + round(22 * completed / max(total_claims, 1))
                progress("claims", min(percent, 47), f"Analyzed {completed} of {total_claims} claims.")
            print(enriched_claim)

    if progress and total_claims == 0:
        progress("claims", 47, "No candidate claims were found in the downloaded papers.")
    return ai_claims