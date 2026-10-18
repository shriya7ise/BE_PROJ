"""
Dashboard endpoints backed by the real CSVs / model results in BE_PROJ.

  GET /api/overview
  GET /api/companies?page=1&page_size=50&tier=Critical&sector=...&q=...
  GET /api/companies/{symbol}

SCORING NOTE
------------
`composite_score` is a transparent heuristic, NOT a model prediction.
  * companies with OSHA violations  -> 20..100, by percentile of
    (60% log penalty, 40% violation count)
  * companies with none             -> 0..19, by percentile of stock volatility
Every row is returned with score_is_estimated = true.
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]          # BE_PROJ/
OUT = ROOT / "output"
TIERS = ["Critical", "Watchlist", "Neutral", "Stable"]


def _tier(score: float) -> str:
    if score >= 70:
        return "Critical"
    if score >= 40:
        return "Watchlist"
    if score >= 20:
        return "Neutral"
    return "Stable"


def _pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average")


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    esg = pd.read_csv(OUT / "esg_dataset.csv")
    news = pd.read_csv(OUT / "news_dataset.csv")[["symbol", "has_news_data", "avg_mean_tone"]]
    fin = pd.read_csv(ROOT / "financials" / "fundamentals.csv")
    fin = fin[["symbol", "sector_yf", "security_name"]]
    fin_ds = pd.read_csv(OUT / "financials_dataset.csv")
    vol_col = "ann_volatility" if "ann_volatility" in fin_ds.columns else None
    if vol_col:
        fin = fin.merge(fin_ds[["symbol", vol_col]], on="symbol", how="left")

    reg = pd.read_csv(ROOT / "data" / "registry" / "company_registry_verified.csv")
    reg = (
        reg.dropna(subset=["ticker"])
        .drop_duplicates("ticker")[["ticker", "canonical_name"]]
        .rename(columns={"ticker": "symbol"})
    )

    df = (
        esg.merge(news, on="symbol", how="left")
        .merge(fin, on="symbol", how="left")
        .merge(reg, on="symbol", how="left")
    )
    df["canonical_name"] = df["canonical_name"].fillna(df["security_name"]).fillna(df["symbol"])
    df["gics_sector"] = df["sector_yf"].fillna("Unknown")
    for c in ["n_violations", "total_current_penalty"]:
        df[c] = df[c].fillna(0)

    return _compute_scores(df, vol_col)


def _compute_scores(df: pd.DataFrame, vol_col) -> pd.DataFrame:
    viol = df["n_violations"] > 0

    osha = 0.6 * _pct(np.log1p(df["total_current_penalty"])) + 0.4 * _pct(df["n_violations"])
    score = pd.Series(0.0, index=df.index)
    v_rank = osha[viol].rank(pct=True)
    score[viol] = 20 + 80 * v_rank

    if vol_col and df[vol_col].notna().any():
        calm = _pct(df.loc[~viol, vol_col].fillna(df[vol_col].median())).fillna(0.5)
    else:
        calm = pd.Series(0.5, index=df.index[~viol])
    score[~viol] = 19 * calm

    flags = pd.DataFrame(index=df.index)
    flags["osha"] = viol
    tone = df["avg_mean_tone"]
    flags["news"] = tone.notna() & (tone <= tone.quantile(0.25))
    if vol_col:
        flags["market"] = df[vol_col] >= df[vol_col].quantile(0.75)
    flags["esg_text"] = df["safety_kw_per_1k"] >= df["safety_kw_per_1k"].quantile(0.75)
    corro = flags.sum(axis=1).astype(int)

    df = df.copy()
    df["composite_score"] = score.round(1)
    df["risk_tier"] = df["composite_score"].map(_tier)
    df["corroboration_count"] = corro
    df["status"] = np.where(corro >= 3, "Escalated", np.where(corro >= 2, "Flagged", np.where(corro == 1, "Monitoring", "Clear")))
    df["score_is_estimated"] = True
    return df


def _row(r: pd.Series) -> dict:
    return {
        "symbol": r["symbol"],
        "canonical_name": r["canonical_name"],
        "gics_sector": r["gics_sector"],
        "composite_score": float(r["composite_score"]),
        "corroboration_count": int(r["corroboration_count"]),
        "risk_tier": r["risk_tier"],
        "status": r["status"],
        "score_is_estimated": bool(r["score_is_estimated"]),
    }


@router.get("/companies")
def list_companies(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    tier: str | None = None,
    sector: str | None = None,
    q: str | None = None,
):
    df = _load()
    if tier:
        df = df[df["risk_tier"].str.lower() == tier.lower()]
    if sector:
        df = df[df["gics_sector"].str.lower() == sector.lower()]
    if q:
        n = q.strip().lower()
        df = df[
            df["canonical_name"].str.lower().str.contains(n, regex=False)
            | df["symbol"].str.lower().str.contains(n, regex=False)
            | df["gics_sector"].str.lower().str.contains(n, regex=False)
        ]
    df = df.sort_values(["composite_score", "symbol"], ascending=[False, True])
    total = len(df)
    start = (page - 1) * page_size
    chunk = df.iloc[start : start + page_size]
    return {
        "results": [_row(r) for _, r in chunk.iterrows()],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/companies/{symbol}")
def get_company(symbol: str):
    df = _load()
    m = df[df["symbol"].str.upper() == symbol.upper()]
    if m.empty:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    r = m.iloc[0]
    out = _row(r)
    out.update(
        n_inspections=float(r.get("n_inspections", 0) or 0),
        n_violations=float(r["n_violations"]),
        total_current_penalty=float(r["total_current_penalty"]),
    )
    return out


@lru_cache(maxsize=1)
def _model_rows() -> list[dict]:
    rows = []
    for group in ("singles", "pairs", "fourway"):
        p = OUT / "model_results" / group / f"{group}_results.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        for combo, res in data.items():
            for model, m in (res.get("classification") or {}).items():
                auc = m.get("roc_auc")
                if auc is not None:
                    rows.append(
                        {"combo_name": combo, "combo_group": group, "model_name": model, "auc": float(auc)}
                    )
    return rows


@router.get("/overview")
def overview():
    df = _load()
    models = _model_rows()
    aucs = [m["auc"] for m in models]
    dist = [{"tier": t, "count": int((df["risk_tier"] == t).sum())} for t in TIERS]
    return {
        "entities_tracked": int(len(df)),
        "critical_alerts_active": int((df["risk_tier"] == "Critical").sum()),
        "model_auc_mean": float(np.mean(aucs)) if aucs else None,
        "model_auc_std": float(np.std(aucs)) if aucs else None,
        "risk_distribution": dist,
        "top_models": sorted(models, key=lambda m: m["auc"], reverse=True)[:5],
    }


# ---------------------------------------------------------------------------
# /companies/{symbol}/reasoning  -- model probability + drivers + evidence text
# ---------------------------------------------------------------------------
import warnings

import joblib

MODEL_NAME = "financial_esg_news_geo__classification__XGBoost"
MODALITY_FILES = {
    "financial": "financials_dataset.csv",
    "esg": "esg_dataset.csv",
    "news": "news_dataset.csv",
    "geo": "geographical_dataset.csv",
}


@lru_cache(maxsize=1)
def _model_bundle():
    """Loads the four-way XGBoost pipeline, scores every company once, and
    returns (probabilities dict, global top drivers list, split dict).
    Returns (None, [], {}) if the model cannot be loaded (e.g. version mismatch)."""
    try:
        meta = json.loads((ROOT / "models" / "saved" / f"{MODEL_NAME}.meta.json").read_text())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pipe = joblib.load(ROOT / "models" / "saved" / f"{MODEL_NAME}.joblib")

        merged = None
        for mod, fname in MODALITY_FILES.items():
            d = pd.read_csv(OUT / fname)
            d = d.drop(columns=[c for c in ("target_class", "target_reg") if c in d.columns])
            d = d.rename(columns={c: f"{mod}__{c}" for c in d.columns if c != "symbol"})
            merged = d if merged is None else merged.merge(d, on="symbol", how="inner")

        cols = meta["numeric_cols"] + meta["categorical_cols"]
        proba = pipe.predict_proba(merged[cols])[:, 1]
        probs = dict(zip(merged["symbol"], map(float, proba)))

        names = pipe.named_steps["pre"].get_feature_names_out()
        imp = pipe.named_steps["clf"].feature_importances_
        order = np.argsort(imp)[::-1][:8]
        drivers = [
            {"feature": str(names[i]).split("__", 1)[1], "importance": float(imp[i])}
            for i in order
        ]

        splits = pd.read_csv(OUT / "company_splits.csv")
        return probs, drivers, dict(zip(splits["symbol"], splits["split"]))
    except Exception as e:  # keep the API alive even if the model can't load
        print(f"[reasoning] model unavailable: {e!r}")
        return None, [], {}


def _build_evidence(r: pd.Series, df: pd.DataFrame) -> list[str]:
    ev = []
    n_insp = int(r.get("n_inspections", 0) or 0)
    n_viol = int(r["n_violations"])
    pen = float(r["total_current_penalty"])
    if n_viol > 0:
        ev.append(
            f"OSHA records show {n_insp} inspections and {n_viol} violations "
            f"with ${pen:,.0f} in current penalties."
        )
    else:
        ev.append(f"OSHA records show no violations ({n_insp} inspections).")

    tone = r.get("avg_mean_tone")
    if pd.notna(tone):
        med = df["avg_mean_tone"].median()
        side = "below" if tone < med else "above"
        ev.append(f"Average news tone is {tone:.2f}, {side} the peer median of {med:.2f}.")

    vol = r.get("ann_volatility")
    if pd.notna(vol):
        pct = (df["ann_volatility"] < vol).mean() * 100
        ev.append(f"Annualised stock volatility is {vol:.2f}, higher than {pct:.0f}% of tracked companies.")

    kw = r.get("safety_kw_per_1k")
    if pd.notna(kw):
        pct = (df["safety_kw_per_1k"] < kw).mean() * 100
        ev.append(f"Safety-related keywords appear {kw:.3f} times per 1k words in the 10-K (higher than {pct:.0f}% of peers).")
    return ev


_RECOMMENDATION = {
    "Critical": "Escalate for analyst review now: request recent inspection details and monitor news for new incidents.",
    "Watchlist": "Add to the watchlist and re-check after the next inspection or filing cycle.",
    "Neutral": "No action needed beyond routine monitoring.",
    "Stable": "No concerns identified; keep in the routine review cycle.",
}


@router.get("/companies/{symbol}/reasoning")
def company_reasoning(symbol: str, refresh: int = 0):
    df = _load()
    m = df[df["symbol"].str.upper() == symbol.upper()]
    if m.empty:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    r = m.iloc[0]
    probs, drivers, splits = _model_bundle()

    evidence = _build_evidence(r, df)
    ids = [f"E{i + 1}" for i in range(len(evidence))]
    explanation = " ".join(f"{t} [{i}]" for t, i in zip(evidence, ids))

    if probs is not None and r["symbol"] in probs:
        prob = probs[r["symbol"]]
        split = splits.get(r["symbol"], "unknown")
        if split == "train":
            explanation += " Note: this company was in the model's training set, so its probability is in-sample."
    else:
        prob = float(r["composite_score"]) / 100.0
        explanation += " Note: the trained model could not be loaded, so P(risk) falls back to the heuristic score."

    return {
        "symbol": r["symbol"],
        "canonical_name": r["canonical_name"],
        "gics_sector": r["gics_sector"],
        "composite_score": float(r["composite_score"]),
        "risk_tier": r["risk_tier"],
        "model_probability": float(prob),
        "top_drivers": drivers,
        "explanation": explanation,
        "recommendation": _RECOMMENDATION[r["risk_tier"]],
        "corroboration_count": int(r["corroboration_count"]),
        "evidence_ids": ids,
    }
