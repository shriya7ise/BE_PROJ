import os
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from google import genai
from google.genai import types

router = APIRouter()          # main.py adds the /api prefix

_client = None


def get_client():
    """Create the Gemini client on first use so the server starts even without a key."""
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set on the server")
        _client = genai.Client(api_key=key)
    return _client


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # confirm the current name in Google AI Studio

SYSTEM_PROMPT = (
    "You are an ESG and workplace-risk analyst assistant for the BE_PROJ dashboard. "
    "Answer using ONLY the company data provided in the context. "
    "If the data does not contain the answer, say so instead of guessing. "
    "Note that composite_score is a transparent heuristic estimate, not a model prediction. "
    "Keep answers concise and mention the specific scores, drivers or signals you rely on."
)


class ChatRequest(BaseModel):
    message: str
    symbol: Optional[str] = None


def call_existing_route(request: Request, path: str, symbol: str):
    """Find an existing GET route by its URL path and call its function with the symbol."""
    for r in request.app.routes:
        if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set()):
            try:
                return r.endpoint(symbol)
            except Exception:
                return None
    return None


@router.post("/chat")
def chat(req: ChatRequest, request: Request):
    context = "No company is focused. Answer general questions about the platform only."

    if req.symbol:
        company = call_existing_route(request, "/api/companies/{symbol}", req.symbol)
        esg = call_existing_route(request, "/api/companies/{symbol}/esg", req.symbol)
        signals = call_existing_route(request, "/api/companies/{symbol}/signals", req.symbol)
        context = json.dumps(
            {"company": company, "esg": esg, "signals": signals},
            default=str,
        )[:15000]

    try:
        resp = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Company data:\n{context}\n\nQuestion: {req.message}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return {"reply": resp.text or "I couldn't generate an answer."}