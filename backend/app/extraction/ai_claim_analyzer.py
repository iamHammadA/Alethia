from google import genai
import json
from claim_normalizer import main_function
import os
import requests
from dotenv import load_dotenv

load_dotenv()

client = genai.Client()
def call_openrouter_reasoning(
    claim_input: dict | str, 
    api_key: str | None = None,
    model: str = "nvidia/nemotron-3-super-120b-a12b:free"
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

def analyzer():
    ai_claims = {}
    json_claims = main_function()
    
    # Store key in environment or variable
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    
    for article_id, claims_list in json_claims.items():
        inter_claim = []
        print(f"Article {article_id} Claims Count:", len(claims_list))
        
        for single_claim in claims_list:
            analyzed_claim = call_openrouter_reasoning(single_claim, api_key=openrouter_key)
            inter_claim.append(analyzed_claim)
            print(analyzed_claim)
            
        ai_claims[article_id] = inter_claim
     
    return ai_claims