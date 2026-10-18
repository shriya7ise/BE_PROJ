"""
AI chat for the Vigilance dashboard.

The server builds the context itself, so any client gets the same quality:
  * the focused company's full dossier (company record, model reasoning, ESG study,
    financial study, signals, open alerts)
  * the whole risk register (tier counts, leaderboard, sector table, named companies)
  * open alerts across the portfolio
  * the recent conversation

POST /api/chat  {message, symbol?, history?: [{role, text}], role?, style?}
             -> {reply, symbol, also_named}
"""
import json
import math
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app import alerts_engine
from app import analysis as A
from app.routers import dashboard as D

router = APIRouter()  # main.py adds the /api prefix

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


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ROLES = {
    "Risk analyst": "a risk analyst who wants evidence, drivers and the reasoning behind each score",
    "Executive": "a senior executive who wants the bottom line, business impact and the decisions to make",
    "Safety / EHS manager": "a workplace-safety (EHS) manager who wants OSHA-related causes and concrete corrective actions",
    "Investor": "an investor who wants financial materiality, downside risk and how peers compare",
}
STYLES = {
    "Concise": "Keep answers short: under 150 words, with tight bullets.",
    "Detailed": "Give a thorough answer with clear sections: Answer, Reasoning, Evidence, Recommendations.",
}

SYSTEM_PROMPT = """You are "Vigilance Analyst", the assistant inside an ESG-risk and financial-health dashboard.

HOW TO USE THE DATA
- The DATA sections in each request are your primary source. Quote real figures: scores, tiers, penalties, violation counts, ranks, margins, open alerts.
- Never say a company is missing if it appears in the DATA. If a figure truly is not in the DATA, say so plainly instead of guessing.
- composite_score is a transparent heuristic estimate built from OSHA penalties and violation counts, not a model prediction. model_probability is the XGBoost model's output (it can be in-sample for training companies). Say which one you are citing, and mention when a score is estimated.

HOW TO ANSWER
- Reasoning questions (why, how, explain): walk through the drivers step by step: composite score, corroboration (OSHA, news tone, market volatility, 10-K safety language), OSHA citations and penalties, model drivers, financial materiality. Tie each point to a fact.
- Recommendation questions: give measurable actions in priority order. For each action: what to do, the KPI/metric, a target value, a timeframe, an owner, and the evidence it addresses.
- Alert questions: use the open alerts in the DATA (severity, rule, since when) and say what to do next.
- General questions (ESG concepts, OSHA, finance, how the scores work): answer from general knowledge and label that part as general knowledge.
- This is analysis for information, not investment or legal advice.
"""

_MAX_CHARS = {"company": 2500, "model_reasoning": 4000, "esg_study": 7000, "financial_study": 7000, "signals": 5000, "open_alerts": 3000}
_SKIP = {"series", "drawdown", "rolling_vol", "embedding", "embeddings"}


class Turn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    symbol: Optional[str] = None
    history: list[Turn] = Field(default_factory=list)
    role: Optional[str] = None
    style: Optional[str] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _compact(v, depth=0):
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        try:
            v = v.item()
        except Exception:
            pass
    if v is None or isinstance(v, bool):
        return v
    if depth > 7:
        return "…"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 3) if abs(v) < 1000 else round(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return v if len(v) <= 400 else v[:400] + "…"
    if isinstance(v, (list, tuple)):
        lim = 14 if depth <= 1 else 6
        out = [_compact(x, depth + 1) for x in v[:lim]]
        if len(v) > lim:
            out.append(f"…(+{len(v) - lim} more)")
        return out
    if isinstance(v, dict):
        return {str(k): _compact(x, depth + 1) for k, x in v.items() if k not in _SKIP}
    return str(v)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…[truncated]"


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:
        return None


def _section(name: str, value) -> str | None:
    if value is None:
        return None
    return f"### {name.upper()}\n" + _clip(json.dumps(_compact(value), default=str), _MAX_CHARS.get(name, 4000))


def company_dossier(symbol: str, deep: bool = True) -> str:
    parts = {
        "company": _safe(D.get_company, symbol),
        "model_reasoning": _safe(D.company_reasoning, symbol),
        "open_alerts": alerts_engine.open_alerts_brief(symbol=symbol),
    }
    if deep:
        parts["esg_study"] = _safe(lambda: A.clean(A.esg_dossier(symbol)))
        parts["financial_study"] = _safe(lambda: A.financial_study(symbol, allow_live=False))
        parts["signals"] = _safe(A.signals_for, symbol)
    return "\n\n".join(s for s in (_section(k, v) for k, v in parts.items()) if s)


# --- company detection -----------------------------------------------------
_TRAILING = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
             "holdings", "holding", "group", "com", "llc", "lp", "sa", "nv", "ag", "class", "cl", "a", "b", "and", "the"}
_NOT_TICKERS = {"ESG", "OSHA", "AI", "API", "CEO", "CFO", "USA", "US", "UK", "EU", "GDP", "ETF", "IPO",
                "PE", "ROE", "ROI", "FAQ", "PDF", "AND", "THE", "FOR", "ARE", "WHAT", "WHY", "HOW"}
_COMMON = {"all", "now", "are", "can", "has", "was", "one", "any", "new", "see", "key", "low", "run",
           "big", "well", "real", "good", "best", "top", "for", "the", "and"}
_CUES = {"company", "details", "detail", "stock", "ticker", "about", "risk", "esg", "score"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower().replace("&", " and ")).strip()


def _core(name: str) -> str:
    t = _norm(name).split()
    if len(t) > 1 and t[0] == "the":
        t = t[1:]
    while len(t) > 1 and t[-1] in _TRAILING:
        t.pop()
    return " ".join(t)


def detect_symbols(message: str, df) -> list[str]:
    padded = f" {_norm(message)} "
    words = _norm(message).split()
    found: dict[str, tuple[int, int]] = {}

    def add(sym, score, pos):
        if sym not in found or score > found[sym][0]:
            found[sym] = (score, pos)

    symbols = {s.upper(): s for s in df["symbol"]}
    for sym, name in zip(df["symbol"], df["canonical_name"]):
        core = _core(name)
        if len(core) < 3 and not re.search(r"\d", core):
            continue
        pos = padded.find(f" {core} ")
        if pos >= 0:
            add(sym, len(core), pos)
    for m in re.finditer(r"\$([A-Za-z]{1,5}(?:[.-][A-Za-z])?)\b|\b([A-Z]{2,5}(?:[.-][A-Z])?)\b", message):
        tk = (m.group(1) or m.group(2)).upper()
        if m.group(2) and tk in _NOT_TICKERS:
            continue
        if tk in symbols:
            add(symbols[tk], 100, m.start())
    for i, w in enumerate(words):
        if len(w) < 3 or w in _COMMON or w.upper() not in symbols:
            continue
        if (i > 0 and words[i - 1] in _CUES) or (i + 1 < len(words) and words[i + 1] in _CUES):
            add(symbols[w.upper()], 90, i)
    return [s for s, _ in sorted(found.items(), key=lambda kv: (-kv[1][0], kv[1][1]))]


# --- register ---------------------------------------------------------------
def register_context(df, named: list[str]) -> str:
    d = df.sort_values(["composite_score", "symbol"], ascending=[False, True])
    line = lambda r, i=None: (  # noqa: E731
        f"{(str(i + 1) + '. ') if i is not None else '- '}{r['symbol']} ({r['canonical_name']}), sector {r['gics_sector']}, "
        f"score {r['composite_score']}, tier {r['risk_tier']}, status {r['status']}, "
        f"violations {int(r['n_violations'])}, penalties ${float(r['total_current_penalty']):,.0f}"
    )
    tiers = d["risk_tier"].value_counts().to_dict()
    status = d["status"].value_counts().to_dict()
    sec = (
        d.groupby("gics_sector")
        .agg(n=("symbol", "count"), avg=("composite_score", "mean"), crit=("risk_tier", lambda s: int((s == "Critical").sum())),
             pen=("total_current_penalty", "sum"))
        .sort_values("avg", ascending=False)
    )
    parts = [
        f"Companies covered: {len(d)}. By tier: {tiers}. By status: {status}. All composite scores are heuristic estimates.",
        "Top 15 by composite risk score:\n" + "\n".join(line(r, i) for i, (_, r) in enumerate(d.head(15).iterrows())),
        "Lowest 5:\n" + "\n".join(line(r) for _, r in d.tail(5).iloc[::-1].iterrows()),
        "Sectors by average score:\n" + "\n".join(
            f"- {k}: avg {v['avg']:.1f} ({int(v['n'])} companies, {int(v['crit'])} critical, penalties ${v['pen']:,.0f})" for k, v in sec.iterrows()
        ),
    ]
    if named:
        ranks = {s: i + 1 for i, s in enumerate(d["symbol"])}
        rows = d[d["symbol"].isin(named)]
        parts.append("Companies named in the question:\n" + "\n".join(f"{line(r)} (rank {ranks[r['symbol']]} of {len(d)})" for _, r in rows.iterrows()))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
@router.post("/chat")
def chat(req: ChatRequest):
    df = _safe(D._load)
    named: list[str] = []
    if df is not None:
        named = detect_symbols(req.message, df)
    focus = (req.symbol or (named[0] if named else None))
    focus = focus.upper() if focus else None
    if focus and df is not None and focus not in set(df["symbol"].str.upper()):
        focus = None
    others = [s for s in named if s != focus][:3]

    sections = []
    if focus:
        sections.append(f"FOCUSED COMPANY: {focus}\n\n" + company_dossier(focus, deep=True))
    for s in others:
        sections.append(f"ALSO NAMED: {s}\n\n" + company_dossier(s, deep=False))
    if df is not None:
        sections.append("RISK REGISTER\n" + register_context(df, ([focus] if focus else []) + others))
    if not focus:
        brief = alerts_engine.open_alerts_brief(limit=10)
        if brief:
            sections.append("OPEN ALERTS (portfolio)\n" + _clip(json.dumps(_compact(brief), default=str), 3000))

    history = "\n".join(
        f"{'User' if t.role == 'user' else 'Assistant'}: {_clip(t.text, 800)}" for t in req.history[-8:]
    )
    persona = ROLES.get(req.role or "", ROLES["Risk analyst"])
    style = STYLES.get(req.style or "", STYLES["Concise"])
    prompt = (
        "\n\n".join(sections)
        + (f"\n\nCONVERSATION SO FAR\n{history}" if history else "")
        + f"\n\nREADER: {persona}.\n{style}\n\nUSER QUESTION:\n{req.message}"
    )

    try:
        resp = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.3),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return {"reply": resp.text or "I couldn't generate an answer.", "symbol": focus, "also_named": others}