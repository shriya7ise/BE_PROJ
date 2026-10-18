"""
Analytics layer for the Vigilance dashboard.

Everything returned here is computed from the files already in BE_PROJ:

  output/esg_dataset.csv, news_dataset.csv, geographical_dataset.csv, financials_dataset.csv
  financials/fundamentals.csv                       (+ optional prices/ and statements/)
  data/raw/osha_api/violation_by_company_verified.csv   (citation-level OSHA records)
  data/registry/company_registry_verified.csv
  news/raw/<SYMBOL>.parquet                         (headline-level news)
  esg_reports/<SYMBOL>/*.htm                        (10-K filings -> evidence passages)

Nothing is typed in per company. The only static tables are reference data
(OSHA standard titles, human-readable metric labels).
"""
from __future__ import annotations

import glob
import json
import math
import re
import warnings
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd

from app.routers import dashboard as dash

ROOT = dash.ROOT
OUT = dash.OUT


# --------------------------------------------------------------------------- utils
def clean(o):
    """Recursively make an object JSON-safe (NaN/inf -> None, numpy -> python)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    if o is pd.NaT:
        return None
    return o


def pct_rank(series: pd.Series, value) -> float | None:
    """Percentile (0-100) of `value` within `series` (mid-rank for ties)."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if value is None or pd.isna(value) or s.empty:
        return None
    return float(((s < value).sum() + 0.5 * (s == value).sum()) / len(s) * 100)


def num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def money(v) -> str:
    v = num(v)
    if v is None:
        return "n/a"
    a = abs(v)
    sign = "-" if v < 0 else ""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:.2f}{suf}"
    return f"{sign}${a:,.0f}"


def ordinal(n: float) -> str:
    n = int(round(n))
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# --------------------------------------------------------------------------- loaders
@lru_cache(maxsize=1)
def fin_table() -> pd.DataFrame:
    f = pd.read_csv(ROOT / "financials" / "fundamentals.csv")
    ds = pd.read_csv(OUT / "financials_dataset.csv")
    keep = [c for c in ("symbol", "ann_volatility", "one_year_return", "max_drawdown", "price_history_days") if c in ds.columns]
    f = f.merge(ds[keep], on="symbol", how="left")
    f["sector"] = f["sector_yf"].fillna("Unknown")
    f["net_debt"] = f["total_debt"] - f["total_cash"]
    rev = f["total_revenue"].replace(0, np.nan)
    f["fcf_margin"] = f["free_cashflow"] / rev
    f["ocf_margin"] = f["operating_cashflow"] / rev
    f["fcf_conversion"] = f["free_cashflow"] / f["operating_cashflow"].replace(0, np.nan)
    f["fcf_yield"] = f["free_cashflow"] / f["market_cap"].replace(0, np.nan)
    ebitda = f["ebitda_margins"] * f["total_revenue"]
    f["net_debt_to_ebitda"] = f["net_debt"] / ebitda.where(ebitda > 0)
    f["cash_to_debt"] = f["total_cash"] / f["total_debt"].replace(0, np.nan)
    f["revenue_per_employee"] = f["total_revenue"] / f["employees"].replace(0, np.nan)
    f["range_position_52w"] = np.nan  # needs a live price; filled when price history exists
    f = f.replace([np.inf, -np.inf], np.nan)
    return f.set_index("symbol", drop=False)


@lru_cache(maxsize=1)
def geo_table() -> pd.DataFrame:
    g = pd.read_csv(OUT / "geographical_dataset.csv")
    return g.set_index("symbol", drop=False)


@lru_cache(maxsize=1)
def viol_table() -> pd.DataFrame:
    reg = pd.read_csv(ROOT / "data" / "registry" / "company_registry_verified.csv")
    reg = reg.dropna(subset=["ticker"]).drop_duplicates("company_id")[["company_id", "ticker"]]
    v = pd.read_csv(
        ROOT / "data" / "raw" / "osha_api" / "violation_by_company_verified.csv",
        usecols=[
            "activity_nr", "citation_id", "standard", "viol_type", "issuance_date", "abate_complete",
            "current_penalty", "initial_penalty", "contest_date", "nr_instances", "nr_exposed",
            "gravity", "_matched_company_id",
        ],
    )
    v = v.merge(reg, left_on="_matched_company_id", right_on="company_id", how="inner")
    v["date"] = pd.to_datetime(v["issuance_date"], errors="coerce")
    v["year"] = v["date"].dt.year
    v["std"] = v["standard"].astype(str).str.split().str[0]
    v["penalty"] = v["current_penalty"].fillna(0.0)
    v["initial"] = v["initial_penalty"].fillna(0.0)
    v["viol_type"] = v["viol_type"].fillna("U")
    return v


@lru_cache(maxsize=1)
def viol_by_symbol() -> dict:
    return {k: g for k, g in viol_table().groupby("ticker")}


@lru_cache(maxsize=512)
def news_for(symbol: str) -> pd.DataFrame:
    p = ROOT / "news" / "raw" / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["title", "url", "domain", "date", "source"])
    try:
        d = pd.read_parquet(p)
    except Exception as e:  # pyarrow missing etc.
        print(f"[news] cannot read {p.name}: {e!r}")
        return pd.DataFrame(columns=["title", "url", "domain", "date", "source"])
    d = d.drop_duplicates(subset=["title"]).copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    return d.sort_values("date", ascending=False)


# --------------------------------------------------------------------------- reference tables
OSHA_STD = {
    "19100147": "Lockout / tagout (control of hazardous energy)",
    "19100037": "Exit routes - maintenance, safeguards, operational features",
    "19101200": "Hazard communication",
    "19100303": "Electrical - general requirements",
    "19100305": "Electrical - wiring methods and equipment",
    "19100304": "Electrical - wiring design and protection",
    "19100178": "Powered industrial trucks (forklifts)",
    "19100212": "Machine guarding - general requirements",
    "19100022": "Walking-working surfaces (slips, trips, falls)",
    "19100176": "Handling materials - general",
    "19100157": "Portable fire extinguishers",
    "19100119": "Process safety management of highly hazardous chemicals",
    "19100134": "Respiratory protection",
    "19100132": "Personal protective equipment - general",
    "19100133": "Eye and face protection",
    "19100036": "Exit routes - design and construction",
    "19100028": "Duty to have fall protection",
    "19100029": "Fall protection systems - criteria",
    "5A0001": "General Duty Clause - Section 5(a)(1)",
    "19100146": "Permit-required confined spaces",
    "19100141": "Sanitation",
    "19100151": "Medical services and first aid",
    "19101030": "Bloodborne pathogens",
    "19040039": "Reporting fatalities / hospitalizations (Part 1904)",
    "19040040": "Providing records to government representatives",
    "19040029": "Recordkeeping forms (Part 1904)",
    "19100219": "Mechanical power-transmission apparatus",
    "19100215": "Abrasive wheel machinery",
    "19100023": "Guarding floor and wall openings",
    "19100269": "Electric power generation, transmission, distribution",
    "19100095": "Occupational noise exposure",
    "19100101": "Compressed gases - general requirements",
    "19260501": "Construction fall protection - scope",
    "3203(A)": "Cal/OSHA - Injury and Illness Prevention Program",
    "3395(I)": "Cal/OSHA - Heat illness prevention",
}
VIOL_TYPES = {
    "S": ("Serious", "Substantial probability of death or serious physical harm"),
    "W": ("Willful", "Intentional disregard of the law or plain indifference to safety"),
    "R": ("Repeat", "Substantially similar to a prior citation within 5 years"),
    "O": ("Other-than-serious", "Directly related to safety but unlikely to cause death / serious harm"),
    "U": ("Unclassified", "Type not recorded"),
}
PILLARS = [
    ("environment", "Environmental", "environment_kw_per_1k",
     "How much of the 10-K is devoted to emissions, climate, hazardous materials, water and energy."),
    ("social", "Social", "social_kw_per_1k",
     "Disclosure on workforce, human capital, labour relations, diversity and community."),
    ("governance", "Governance", "governance_kw_per_1k",
     "Disclosure on board oversight, audit, ethics, compliance and internal control."),
    ("safety", "Health & safety", "safety_kw_per_1k",
     "Mentions of workplace safety, injuries, OSHA and incident prevention."),
]
PASSAGE_RE = {
    "safety": re.compile(r"\b(OSHA|workplace safety|worker safety|health and safety|safety first|injur\w*|fatalit\w*|workplace violence|safety incident|occupational)\b", re.I),
    "environment": re.compile(r"\b(greenhouse|emission\w*|climate|environmental|hazardous (?:material|waste|substance)\w*|carbon|sustainab\w*|pollut\w*|energy efficien\w*|recycl\w*)\b", re.I),
    "social": re.compile(r"\b(human capital|diversity|inclusion|collective bargaining|union\w*|wage\w*|associate engagement|training and development|labor)\b", re.I),
    "governance": re.compile(r"\b(board of directors|audit committee|whistleblow\w*|code of (?:business )?(?:conduct|ethics)|internal control|independent director\w*|compliance program)\b", re.I),
}


# --------------------------------------------------------------------------- 10-K evidence
@lru_cache(maxsize=96)
def tenk_passages(symbol: str, per_pillar: int = 3) -> dict:
    """Pull the most informative sentences per pillar out of the company's 10-K."""
    files = sorted(glob.glob(str(ROOT / "esg_reports" / symbol / "*.htm")))
    meta_files = glob.glob(str(ROOT / "esg_reports" / symbol / "*_meta.json"))
    meta = {}
    if meta_files:
        try:
            meta = json.loads(open(meta_files[0]).read())
        except Exception:
            meta = {}
    out = {"meta": meta, "passages": {k: [] for k in PASSAGE_RE}, "available": False}
    if not files:
        return out
    try:
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(open(files[0], "rb").read(), "lxml")
        for s in soup(["script", "style"]):
            s.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" "))
    except Exception as e:
        print(f"[10k] parse failed for {symbol}: {e!r}")
        return out
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z\u201c\"])", text)
    seen = set()
    for pillar, rx in PASSAGE_RE.items():
        scored = []
        for s in sents:
            if not (90 <= len(s) <= 380) or s.count("•") > 2 or s.lower().count("may ") > 3:
                continue
            hits = {m.group(0).lower() for m in rx.finditer(s)}
            if not hits:
                continue
            key = s[:60]
            if key in seen:
                continue
            scored.append((len(hits), -abs(len(s) - 220), s.replace("•", "").strip()))
        scored.sort(reverse=True)
        for _, _, s in scored[:per_pillar]:
            seen.add(s[:60])
            out["passages"][pillar].append(s)
    out["available"] = True
    return out


# --------------------------------------------------------------------------- helpers
def _universe():
    return dash._load()


def _row(symbol: str):
    df = _universe()
    m = df[df["symbol"].str.upper() == symbol.upper()]
    if m.empty:
        return None, df
    return m.iloc[0], df


def _level(p: float | None) -> str:
    if p is None:
        return "n/a"
    if p >= 90:
        return "very high"
    if p >= 70:
        return "high"
    if p >= 40:
        return "moderate"
    if p >= 15:
        return "low"
    return "very low"


# --------------------------------------------------------------------------- OSHA block
def osha_block(symbol: str, df: pd.DataFrame, r: pd.Series) -> dict:
    v = viol_by_symbol().get(symbol)
    n_insp = int(r.get("n_inspections", 0) or 0)
    if v is None or v.empty:
        return {"has_records": False, "n_inspections": n_insp, "n_violations": 0, "total_penalty": 0.0}

    total_pen = float(v["penalty"].sum())
    by_year = (
        v.dropna(subset=["year"]).groupby("year")
        .agg(violations=("penalty", "size"), penalty=("penalty", "sum"),
             serious=("viol_type", lambda s: int(s.isin(["S", "W", "R"]).sum())))
        .reset_index()
    )
    by_year["year"] = by_year["year"].astype(int)
    if not by_year.empty:  # include zero years so the chart has no gaps
        full = pd.DataFrame({"year": range(by_year.year.min(), by_year.year.max() + 1)})
        by_year = full.merge(by_year, on="year", how="left").fillna(0)

    by_type = []
    for t, g in v.groupby("viol_type"):
        label, desc = VIOL_TYPES.get(t, (t, ""))
        by_type.append({"code": t, "label": label, "description": desc,
                        "count": int(len(g)), "penalty": float(g["penalty"].sum())})
    by_type.sort(key=lambda x: -x["count"])

    stds = (
        v.groupby("std").agg(count=("penalty", "size"), penalty=("penalty", "sum"))
        .sort_values(["penalty", "count"], ascending=False).head(8).reset_index()
    )
    top_standards = [
        {"code": s.std, "title": OSHA_STD.get(s.std, f"OSHA standard {s.std}"),
         "count": int(s.count), "penalty": float(s.penalty)}
        for s in stds.itertuples()
    ]

    def cit(g):
        return [{
            "date": d.date.strftime("%Y-%m-%d") if pd.notna(d.date) else None,
            "standard": str(d.std), "title": OSHA_STD.get(d.std, f"OSHA standard {d.std}"),
            "type": VIOL_TYPES.get(d.viol_type, (d.viol_type,))[0],
            "penalty": float(d.penalty), "exposed": num(d.nr_exposed),
            "activity": str(int(d.activity_nr)) if pd.notna(d.activity_nr) else None,
        } for d in g.itertuples()]

    largest = cit(v.sort_values("penalty", ascending=False).head(8))
    recent = cit(v.sort_values("date", ascending=False).head(10))

    # trend: last 3 full years vs the 3 before
    last_year = int(v["year"].max()) if v["year"].notna().any() else None
    trend = {"label": "insufficient history", "recent": None, "prior": None, "change_pct": None}
    if last_year and not by_year.empty:
        yr = by_year.set_index("year")["penalty"]
        rec = float(yr.reindex(range(last_year - 2, last_year + 1)).fillna(0).sum())
        pri = float(yr.reindex(range(last_year - 5, last_year - 2)).fillna(0).sum())
        chg = (rec - pri) / pri * 100 if pri > 0 else None
        label = "rising" if (chg is not None and chg > 25) else "falling" if (chg is not None and chg < -25) else "broadly stable"
        if pri == 0 and rec > 0:
            label = "newly emerging"
        trend = {"label": label, "recent": rec, "prior": pri, "change_pct": chg,
                 "recent_window": f"{last_year - 2}-{last_year}", "prior_window": f"{last_year - 5}-{last_year - 3}"}

    pen_all = df["total_current_penalty"]
    rank = int((pen_all > total_pen).sum() + 1)
    n_exposed = num(v["nr_exposed"].sum())
    sev = int(v["viol_type"].isin(["S", "W", "R"]).sum())
    return {
        "has_records": True,
        "n_inspections": n_insp,
        "n_violations": int(len(v)),
        "total_penalty": total_pen,
        "initial_penalty": float(v["initial"].sum()),
        "median_penalty": float(v["penalty"].median()),
        "max_penalty": float(v["penalty"].max()),
        "avg_per_inspection": total_pen / n_insp if n_insp else None,
        "violations_per_inspection": len(v) / n_insp if n_insp else None,
        "serious_or_worse": sev,
        "serious_share": sev / len(v),
        "willful": int((v["viol_type"] == "W").sum()),
        "repeat": int((v["viol_type"] == "R").sum()),
        "contested": int(v["contest_date"].notna().sum()),
        "contested_share": float(v["contest_date"].notna().mean()),
        "workers_exposed": n_exposed,
        "first_date": v["date"].min().strftime("%Y-%m-%d") if v["date"].notna().any() else None,
        "last_date": v["date"].max().strftime("%Y-%m-%d") if v["date"].notna().any() else None,
        "rank": rank, "universe": int(len(df)),
        "penalty_percentile": pct_rank(pen_all, total_pen),
        "by_year": by_year.to_dict("records"),
        "by_type": by_type,
        "top_standards": top_standards,
        "largest_citations": largest,
        "recent_citations": recent,
        "trend": trend,
    }


# --------------------------------------------------------------------------- news / geo
def news_block(symbol: str, r: pd.Series) -> dict:
    d = news_for(symbol)
    base = {"available": False, "total_articles": int(r.get("total_articles", 0) or 0) if "total_articles" in r else 0}
    if d.empty:
        return base
    dd = d.dropna(subset=["date"])
    monthly = dd.groupby(dd["date"].dt.to_period("M")).size()
    monthly = [{"month": str(k), "count": int(c)} for k, c in monthly.items()]
    sources = dd["domain"].fillna("unknown").value_counts().head(6)
    latest = [{"title": x.title, "domain": x.domain, "date": x.date.strftime("%Y-%m-%d") if pd.notna(x.date) else None,
               "url": x.url} for x in dd.head(10).itertuples()]
    last30 = int((dd["date"] >= dd["date"].max() - pd.Timedelta(days=30)).sum())
    avg_month = len(dd) / max(1, len(monthly))
    tone = num(r.get("avg_mean_tone"))
    all_news = _universe()
    return {
        "available": True,
        "total_articles": int(len(dd)),
        "first_date": dd["date"].min().strftime("%Y-%m-%d"),
        "last_date": dd["date"].max().strftime("%Y-%m-%d"),
        "monthly": monthly,
        "sources": [{"domain": k, "count": int(v)} for k, v in sources.items()],
        "latest": latest,
        "last_30d": last30,
        "avg_per_month": avg_month,
        "tone": tone,
        "tone_available": tone is not None,
    }


GEO_FIELDS = [
    ("Mean_NDVI", "Vegetation index (NDVI)", "Greenness around the facility. Higher = more vegetation.", ""),
    ("Vegetation_pct", "Vegetation cover", "Share of the surrounding area covered by vegetation.", "%"),
    ("BuiltUp_pct", "Built-up area", "Share of impervious / built-up surface.", "%"),
    ("Urban_pct", "Urban land use", "Share of urban land-use classes.", "%"),
    ("Forest_pct", "Forest cover", "Share of forest land-use classes.", "%"),
    ("Agriculture_pct", "Agricultural land", "Share of agricultural land-use classes.", "%"),
    ("Water_pct", "Surface water", "Share classified as open water (NDWI).", "%"),
    ("LST_Celsius", "Land-surface temperature", "Satellite-derived surface heat; a proxy for heat-island / heat-stress exposure.", "°C"),
]


def geo_block(symbol: str) -> dict:
    g = geo_table()
    if symbol not in g.index:
        return {"available": False}
    row = g.loc[symbol]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    if not int(row.get("has_imagery", 0) or 0):
        return {"available": False, "note": "No usable satellite imagery for this location."}
    metrics = []
    for col, label, desc, unit in GEO_FIELDS:
        if col in g.columns and pd.notna(row[col]):
            p = pct_rank(g[col], row[col])
            metrics.append({"key": col, "label": label, "description": desc, "unit": unit,
                            "value": float(row[col]), "percentile": p, "median": float(g[col].median()),
                            "level": _level(p)})
    return {
        "available": True,
        "address": row.get("matched_address"),
        "lat": num(row.get("lat")), "lon": num(row.get("lon")),
        "metrics": metrics,
        "caveat": "Location comes from geocoding the company name. Verify it points at an operating site before relying on these figures.",
    }


# --------------------------------------------------------------------------- ESG dossier
def esg_dossier(symbol: str) -> dict | None:
    r, df = _row(symbol)
    if r is None:
        return None
    sym = r["symbol"]
    sector = r["gics_sector"]
    peers = df[df["gics_sector"] == sector]

    probs, drivers, splits = dash._model_bundle()
    prob = probs.get(sym) if probs else None
    split = splits.get(sym) if splits else None

    # ---- pillars
    pillars = []
    for key, label, col, desc in PILLARS:
        val = num(r.get(col))
        pu = pct_rank(df[col], val)
        ps = pct_rank(peers[col], val) if len(peers) >= 5 else None
        pillars.append({
            "key": key, "label": label, "column": col, "description": desc,
            "value": val, "universe_percentile": pu, "sector_percentile": ps,
            "universe_median": float(df[col].median()),
            "sector_median": float(peers[col].median()) if len(peers) else None,
            "level": _level(pu),
        })
    tenk = tenk_passages(sym)
    for p in pillars:
        p["passages"] = tenk["passages"].get(p["key"], [])

    osha = osha_block(sym, df, r)
    news = news_block(sym, r)
    geo = geo_block(sym)

    # ---- corroboration flags (same logic as the score in dashboard.py)
    tone = df["avg_mean_tone"]
    vol = r.get("ann_volatility")
    flags = [
        {"key": "osha", "label": "OSHA enforcement history", "triggered": bool(r["n_violations"] > 0),
         "detail": f"{int(r['n_violations'])} citations, {money(r['total_current_penalty'])} in penalties" if r["n_violations"] > 0 else "No citations on record"},
        {"key": "news", "label": "Negative news tone", "triggered": bool(pd.notna(r.get("avg_mean_tone")) and r["avg_mean_tone"] <= tone.quantile(0.25)),
         "detail": ("Tone score not available for this company" if pd.isna(r.get("avg_mean_tone")) else f"Average tone {r['avg_mean_tone']:.2f}")},
        {"key": "market", "label": "High market volatility", "triggered": bool(pd.notna(vol) and "ann_volatility" in df and vol >= df["ann_volatility"].quantile(0.75)),
         "detail": ("Volatility not available" if pd.isna(vol) else f"Annualised volatility {vol:.1%} (top-quartile cut-off {df['ann_volatility'].quantile(0.75):.1%})")},
        {"key": "esg_text", "label": "Safety-heavy 10-K disclosure", "triggered": bool(r["safety_kw_per_1k"] >= df["safety_kw_per_1k"].quantile(0.75)),
         "detail": f"{r['safety_kw_per_1k']:.3f} safety terms per 1k words (top-quartile cut-off {df['safety_kw_per_1k'].quantile(0.75):.3f})"},
    ]

    rank = int((df["composite_score"] > r["composite_score"]).sum() + 1)

    # ---- narrative
    narrative = _esg_narrative(r, df, peers, pillars, osha, news, geo, prob, split, flags, rank)

    return {
        "symbol": sym,
        "canonical_name": r["canonical_name"],
        "gics_sector": sector,
        "industry": _industry(sym),
        "business_summary": _summary(sym),
        "composite_score": float(r["composite_score"]),
        "risk_tier": r["risk_tier"],
        "status": r["status"],
        "rank": rank, "universe": int(len(df)),
        "model_probability": prob,
        "model_split": split,
        "top_drivers": drivers,
        "corroboration_count": int(r["corroboration_count"]),
        "flags": flags,
        "pillars": pillars,
        "osha": osha,
        "news": news,
        "geo": geo,
        "filing": {
            "available": tenk["available"],
            "form": tenk["meta"].get("form"), "filing_date": tenk["meta"].get("filing_date"),
            "report_date": tenk["meta"].get("report_date"), "accession": tenk["meta"].get("accession"),
            "cik": tenk["meta"].get("cik"),
            "word_count": num(r.get("word_count")),
            "data_quality": r.get("data_quality_flag"),
        },
        "narrative": narrative,
        "recommendation": dash._RECOMMENDATION[r["risk_tier"]],
        "methodology": [
            "Composite score is a transparent heuristic, not a model output: companies with OSHA violations score 20-100 by percentile of penalty size and violation count; companies with none score 0-19 by stock volatility.",
            "Pillar values are keyword intensities (terms per 1,000 words) in the latest 10-K. They measure how much management discusses a topic, not how well it performs on it.",
            "Model probability comes from the four-way XGBoost classifier. Driver importances are global, identical for every company.",
            "Percentiles compare this company with all tracked entities and with its GICS sector peers.",
        ],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _industry(sym):
    f = fin_table()
    return f.loc[sym, "industry_yf"] if sym in f.index and pd.notna(f.loc[sym, "industry_yf"]) else None


def _summary(sym):
    f = fin_table()
    return f.loc[sym, "long_business_summary"] if sym in f.index and pd.notna(f.loc[sym, "long_business_summary"]) else None


def _esg_narrative(r, df, peers, pillars, osha, news, geo, prob, split, flags, rank) -> list[dict]:
    name, sym, n = r["canonical_name"], r["symbol"], len(df)
    secs = []

    # 1. Executive assessment
    trig = [f["label"] for f in flags if f["triggered"]]
    t = (f"{name} ({sym}) is rated {r['risk_tier']} with a composite score of {r['composite_score']:.1f}/100, "
         f"ranking {ordinal(rank)} highest of {n} tracked companies. ")
    t += (f"{len(trig)} of 4 independent evidence streams are flagged ({', '.join(trig)}). " if trig
          else "None of the four independent evidence streams is flagged. ")
    if prob is not None:
        t += f"The four-way model puts the probability of material workplace-safety risk at {prob:.0%}"
        t += (", but this company was in the training set so the figure is in-sample and likely overstated. " if split == "train"
              else (f" (held out in the {split} split, so this is a genuine out-of-sample estimate). " if split else ". "))
    secs.append({"title": "Executive assessment", "text": t.strip()})

    # 2. Regulatory
    if osha.get("has_records"):
        tr = osha["trend"]
        t = (f"OSHA records show {osha['n_inspections']:,} inspections producing {osha['n_violations']:,} citations and "
             f"{money(osha['total_penalty'])} in current penalties between {osha['first_date'][:4]} and {osha['last_date'][:4]}. "
             f"That puts {sym} at rank {osha['rank']} of {osha['universe']} for total penalties. "
             f"{osha['serious_share']:.0%} of citations are Serious, Willful or Repeat"
             + (f", including {osha['willful']} willful and {osha['repeat']} repeat" if (osha['willful'] or osha['repeat']) else "")
             + ". ")
        if osha["top_standards"]:
            ts = osha["top_standards"][0]
            t += f"The costliest standard is {ts['code']} ({ts['title']}) with {ts['count']} citations totalling {money(ts['penalty'])}. "
        if tr["change_pct"] is not None:
            t += f"Penalties in {tr['recent_window']} were {money(tr['recent'])} versus {money(tr['prior'])} in {tr['prior_window']}: the trend is {tr['label']} ({tr['change_pct']:+.0f}%). "
        elif tr["label"] == "newly emerging":
            t += f"All penalties are recent ({tr['recent_window']}); there is no earlier baseline, so the pattern is newly emerging. "
        if osha["contested_share"] > 0.1:
            t += f"{osha['contested_share']:.0%} of citations were contested, which can delay final penalties. "
    else:
        t = (f"No OSHA citations are on record for {sym} across {osha['n_inspections']} inspections. "
             "A clean record lowers regulatory risk but does not rule out unreported incidents.")
    secs.append({"title": "Regulatory & enforcement record", "text": t.strip()})

    # 3. Disclosure pillars
    parts = []
    for p in pillars:
        if p["universe_percentile"] is None:
            continue
        s = f"{p['label']}: {p['value']:.3f} per 1k words ({ordinal(p['universe_percentile'])} percentile overall"
        s += f", {ordinal(p['sector_percentile'])} in sector" if p["sector_percentile"] is not None else ""
        s += f", {p['level']} emphasis)"
        parts.append(s)
    top = max((p for p in pillars if p["universe_percentile"] is not None), key=lambda p: p["universe_percentile"], default=None)
    t = "10-K language analysis. " + "; ".join(parts) + ". "
    if top:
        t += f"{top['label']} is the topic the filing emphasises most relative to peers. "
    t += "Higher emphasis signals management attention or exposure; it is not a performance score."
    secs.append({"title": "Disclosure analysis (10-K)", "text": t})

    # 4. News
    if news.get("available"):
        t = (f"{news['total_articles']} unique articles were collected between {news['first_date']} and {news['last_date']} "
             f"({news['avg_per_month']:.0f} per month on average, {news['last_30d']} in the final 30 days). ")
        if news["last_30d"] > 2 * news["avg_per_month"]:
            t += "Recent coverage is running well above the monthly average, which deserves a headline review. "
        if not news["tone_available"]:
            t += "Sentiment tone scores are not available, so only volume is analysed."
        secs.append({"title": "Media attention", "text": t.strip()})

    # 5. Satellite
    if geo.get("available"):
        ms = {m["key"]: m for m in geo["metrics"]}
        bits = []
        if "LST_Celsius" in ms:
            bits.append(f"land-surface temperature {ms['LST_Celsius']['value']:.1f}°C ({ordinal(ms['LST_Celsius']['percentile'])} percentile)")
        if "Mean_NDVI" in ms:
            bits.append(f"NDVI {ms['Mean_NDVI']['value']:.2f} ({ms['Mean_NDVI']['level']} greenness)")
        if "BuiltUp_pct" in ms:
            bits.append(f"{ms['BuiltUp_pct']['value']:.0f}% built-up surface")
        secs.append({"title": "Geospatial footprint",
                     "text": f"Satellite analysis around the geocoded location: {', '.join(bits)}. {geo['caveat']}"})
    return secs


# --------------------------------------------------------------------------- Financial study
FIN_GROUPS = [
    ("valuation", "Valuation", [
        ("trailing_pe", "P/E (trailing)", "x", False, "Price per $1 of last-twelve-month earnings."),
        ("forward_pe", "P/E (forward)", "x", False, "Price per $1 of expected earnings."),
        ("peg_ratio", "PEG ratio", "x", False, "P/E relative to earnings growth. Around 1 is often read as fair."),
        ("price_to_book", "Price / book", "x", False, "Market value relative to accounting equity."),
        ("price_to_sales", "Price / sales", "x", False, "Market value per $1 of revenue."),
        ("ev_to_ebitda", "EV / EBITDA", "x", False, "Enterprise value relative to operating earnings."),
    ]),
    ("profitability", "Profitability", [
        ("gross_margins", "Gross margin", "pct", True, "Revenue left after direct costs."),
        ("operating_margins", "Operating margin", "pct", True, "Profit from operations per $1 of revenue."),
        ("ebitda_margins", "EBITDA margin", "pct", True, "Cash-like operating profitability."),
        ("profit_margins", "Net margin", "pct", True, "Bottom-line profit per $1 of revenue."),
        ("return_on_assets", "Return on assets", "pct", True, "Profit generated per $1 of assets."),
        ("return_on_equity", "Return on equity", "pct", True, "Profit generated per $1 of shareholder equity."),
    ]),
    ("growth", "Growth", [
        ("revenue_growth", "Revenue growth (YoY)", "pct", True, "Latest year-over-year revenue growth."),
        ("earnings_growth", "Earnings growth (YoY)", "pct", True, "Latest year-over-year earnings growth."),
    ]),
    ("leverage", "Leverage & liquidity", [
        ("debt_to_equity", "Debt / equity", "pp", False, "Debt as a percentage of equity (yfinance convention, 100 = 1.0x)."),
        ("net_debt_to_ebitda", "Net debt / EBITDA", "x", False, "Years of operating earnings needed to repay net debt."),
        ("current_ratio", "Current ratio", "x", True, "Short-term assets per $1 of short-term liabilities."),
        ("quick_ratio", "Quick ratio", "x", True, "Liquidity excluding inventory."),
        ("cash_to_debt", "Cash / debt", "x", True, "Share of debt that cash could repay today."),
    ]),
    ("cashflow", "Cash generation", [
        ("fcf_margin", "Free-cash-flow margin", "pct", True, "Free cash flow per $1 of revenue."),
        ("fcf_conversion", "FCF conversion", "pct", True, "Free cash flow as a share of operating cash flow."),
        ("fcf_yield", "FCF yield", "pct", True, "Free cash flow relative to market value."),
    ]),
    ("market", "Market risk", [
        ("beta", "Beta", "x", False, "Sensitivity to the overall market. Above 1 amplifies market moves."),
        ("ann_volatility", "Annualised volatility", "pct", False, "Standard deviation of daily returns, annualised."),
        ("max_drawdown", "Maximum drawdown", "pct", True, "Worst peak-to-trough fall over the price history (less negative is better)."),
        ("one_year_return", "1-year return", "pct", True, "Total price return over the last year."),
    ]),
]
SCORE_DIMS = {
    "Profitability": ["operating_margins", "profit_margins", "return_on_equity"],
    "Growth": ["revenue_growth", "earnings_growth"],
    "Balance sheet": ["debt_to_equity", "net_debt_to_ebitda", "cash_to_debt"],
    "Liquidity": ["current_ratio", "quick_ratio"],
    "Cash generation": ["fcf_margin", "fcf_conversion"],
    "Market stability": ["beta", "ann_volatility", "max_drawdown"],
}
_HIGHER = {k: hb for _, _, items in FIN_GROUPS for k, _, _, hb, _ in items}


def _good_pct(series: pd.Series, val, key) -> float | None:
    """Percentile where higher = healthier."""
    p = pct_rank(series, val)
    if p is None:
        return None
    return p if _HIGHER.get(key, True) else 100 - p


def _fmt(v, kind):
    v = num(v)
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v:.1%}"
    return f"{v:.0f}%" if kind == "pp" else f"{v:.2f}x"


# ---- optional history (prices + statements) ---------------------------------
def _norm_statement(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame indexed by period-end date (rows) with line items as columns."""
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        pd.to_datetime(df.columns[:2])
        df = df.T  # items were rows
    except Exception:
        pass
    df = df.copy()
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[df.index.notna()].sort_index()
    return df.apply(pd.to_numeric, errors="coerce")


def _read_parquet(p):
    try:
        return pd.read_parquet(p)
    except Exception as e:
        print(f"[history] cannot read {p}: {e!r}")
        return None


def _live_fetch(symbol: str) -> None:
    """Download prices + statements with yfinance (the same source as scripts/06_fetch_financials.py)
    and cache them under financials/ so it only happens once per company."""
    try:
        import yfinance as yf
    except Exception:
        return
    fdir = ROOT / "financials"
    (fdir / "prices").mkdir(parents=True, exist_ok=True)
    (fdir / "statements").mkdir(parents=True, exist_ok=True)
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="10y", auto_adjust=False)
        if h is not None and not h.empty:
            h.index = h.index.tz_localize(None) if getattr(h.index, "tz", None) else h.index
            h.to_parquet(fdir / "prices" / f"{symbol}.parquet")
        for name, frame in (("income", t.financials), ("balance", t.balance_sheet), ("cashflow", t.cashflow),
                            ("income_q", t.quarterly_financials)):
            if frame is not None and not frame.empty:
                f2 = frame.copy()
                f2.columns = [str(c)[:10] for c in f2.columns]
                f2.to_parquet(fdir / "statements" / f"{symbol}_{name}.parquet")
    except Exception as e:
        print(f"[history] live fetch failed for {symbol}: {e!r}")


def history_block(symbol: str, allow_live: bool = True) -> dict:
    fdir = ROOT / "financials"
    ppath = fdir / "prices" / f"{symbol}.parquet"
    if allow_live and not ppath.exists():
        _live_fetch(symbol)
    out = {"prices": {"available": False}, "statements": {"available": False}}

    # ---- prices
    if ppath.exists():
        px = _read_parquet(ppath)
        if px is not None and not px.empty:
            px = px.copy()
            if "Date" in px.columns:
                px = px.set_index("Date")
            px.index = pd.to_datetime(px.index).tz_localize(None) if getattr(pd.to_datetime(px.index), "tz", None) else pd.to_datetime(px.index)
            px = px.sort_index()
            col = "Adj Close" if "Adj Close" in px.columns else "Close"
            c = px[col].dropna()
            if len(c) > 60:
                ret = c.pct_change().dropna()
                dd = c / c.cummax() - 1
                weekly = c.resample("W").last().dropna()
                step = max(1, len(weekly) // 260)
                cal = c.resample("YE").last().pct_change().dropna()
                first_year = c.index[0].year
                if len(c.resample("YE").last()) > 0:  # first partial year return
                    cal.loc[c.resample("YE").last().index[0]] = c.resample("YE").last().iloc[0] / c.iloc[0] - 1
                    cal = cal.sort_index()
                roll = (ret.rolling(63).std() * np.sqrt(252)).dropna()
                roll_w = roll.resample("W").last().dropna()
                spy_like = None
                hi, lo = float(c.tail(252).max()), float(c.tail(252).min())
                last = float(c.iloc[-1])
                out["prices"] = {
                    "available": True,
                    "start": c.index[0].strftime("%Y-%m-%d"), "end": c.index[-1].strftime("%Y-%m-%d"),
                    "last_price": last, "high_52w": hi, "low_52w": lo,
                    "range_position": (last - lo) / (hi - lo) if hi > lo else None,
                    "series": [{"d": d.strftime("%Y-%m-%d"), "c": float(v)} for d, v in weekly.iloc[::step].items()],
                    "drawdown": [{"d": d.strftime("%Y-%m-%d"), "v": float(v)} for d, v in dd.resample("W").min().dropna().iloc[::step].items()],
                    "rolling_vol": [{"d": d.strftime("%Y-%m-%d"), "v": float(v)} for d, v in roll_w.iloc[::max(1, len(roll_w) // 260)].items()],
                    "calendar_returns": [{"year": int(d.year), "ret": float(v)} for d, v in cal.items()],
                    "cagr": float((c.iloc[-1] / c.iloc[0]) ** (365.25 / max(1, (c.index[-1] - c.index[0]).days)) - 1),
                    "best_day": float(ret.max()), "worst_day": float(ret.min()),
                    "pct_up_days": float((ret > 0).mean()),
                    "max_drawdown": float(dd.min()),
                    "max_drawdown_date": dd.idxmin().strftime("%Y-%m-%d"),
                    "avg_volume": num(px["Volume"].tail(63).mean()) if "Volume" in px.columns else None,
                }

    # ---- statements (annual)
    def load(name):
        p = fdir / "statements" / f"{symbol}_{name}.parquet"
        return _norm_statement(_read_parquet(p)) if p.exists() else pd.DataFrame()

    inc, bal, cfs = load("income"), load("balance"), load("cashflow")
    if not (inc.empty and bal.empty and cfs.empty):
        def pick(df, *names):
            for n in names:
                if n in df.columns:
                    return df[n]
            return pd.Series(dtype=float)
        idx = sorted(set(inc.index) | set(bal.index) | set(cfs.index))
        t = pd.DataFrame(index=idx)
        t["revenue"] = pick(inc, "Total Revenue", "Operating Revenue")
        t["gross_profit"] = pick(inc, "Gross Profit")
        t["operating_income"] = pick(inc, "Operating Income", "Total Operating Income As Reported")
        t["ebitda"] = pick(inc, "EBITDA", "Normalized EBITDA")
        t["net_income"] = pick(inc, "Net Income", "Net Income Common Stockholders")
        t["eps"] = pick(inc, "Diluted EPS", "Basic EPS")
        t["total_assets"] = pick(bal, "Total Assets")
        t["total_debt"] = pick(bal, "Total Debt")
        t["cash"] = pick(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
        t["equity"] = pick(bal, "Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity")
        t["operating_cf"] = pick(cfs, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
        t["capex"] = pick(cfs, "Capital Expenditure")
        t["free_cf"] = pick(cfs, "Free Cash Flow")
        t = t.dropna(how="all")
        if not t.empty:
            t["gross_margin"] = t["gross_profit"] / t["revenue"]
            t["operating_margin"] = t["operating_income"] / t["revenue"]
            t["net_margin"] = t["net_income"] / t["revenue"]
            t["revenue_growth"] = t["revenue"].pct_change()
            t["net_debt"] = t["total_debt"] - t["cash"]
            t["roe"] = t["net_income"] / t["equity"]
            rows = []
            for d, rw in t.iterrows():
                rr = {"period": d.strftime("%Y-%m-%d"), "year": int(d.year)}
                rr.update({k: num(v) for k, v in rw.items()})
                rows.append(rr)
            rev = t["revenue"].dropna()
            cagr = None
            if len(rev) >= 3 and rev.iloc[0] > 0 and rev.iloc[-1] > 0:
                yrs = (rev.index[-1] - rev.index[0]).days / 365.25
                cagr = float((rev.iloc[-1] / rev.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else None
            out["statements"] = {"available": True, "annual": rows, "revenue_cagr": cagr, "years": len(t)}
    return out


def _price_flags(h: dict) -> dict:
    return h


def financial_study(symbol: str, allow_live: bool = True) -> dict | None:
    f = fin_table()
    sym = symbol.upper()
    if sym not in f.index:
        return None
    r = f.loc[sym]
    sector = r["sector"]
    peers = f[f["sector"] == sector]
    uni = dash._load()
    u = uni[uni["symbol"] == sym]
    esg_row = u.iloc[0] if not u.empty else None

    groups = []
    for gkey, glabel, items in FIN_GROUPS:
        rows = []
        for key, label, kind, higher, desc in items:
            val = num(r.get(key))
            rows.append({
                "key": key, "label": label, "kind": kind, "description": desc, "higher_is_better": higher,
                "value": val,
                "sector_median": num(peers[key].median()) if key in peers else None,
                "universe_median": num(f[key].median()) if key in f else None,
                "universe_percentile": pct_rank(f[key], val) if key in f else None,
                "sector_percentile": pct_rank(peers[key], val) if (key in peers and len(peers) >= 5) else None,
                "health_percentile": _good_pct(f[key], val, key) if key in f else None,
            })
        groups.append({"key": gkey, "label": glabel, "items": rows})

    # scorecard
    flat = {i["key"]: i for g in groups for i in g["items"]}
    score = []
    for dim, keys in SCORE_DIMS.items():
        co = [flat[k]["health_percentile"] for k in keys if k in flat and flat[k]["health_percentile"] is not None]
        sm = []
        for k in keys:
            if k in peers and pd.notna(peers[k].median()):
                sm.append(_good_pct(f[k], peers[k].median(), k))
        sm = [x for x in sm if x is not None]
        score.append({"dimension": dim, "score": float(np.mean(co)) if co else None,
                      "sector_score": float(np.mean(sm)) if sm else None})
    valid = [s["score"] for s in score if s["score"] is not None]
    overall = float(np.mean(valid)) if valid else None

    # size / snapshot
    snapshot = {
        "market_cap": num(r.get("market_cap")), "enterprise_value": num(r.get("enterprise_value")),
        "total_revenue": num(r.get("total_revenue")), "total_cash": num(r.get("total_cash")),
        "total_debt": num(r.get("total_debt")), "net_debt": num(r.get("net_debt")),
        "total_assets": num(r.get("total_assets")),
        "free_cashflow": num(r.get("free_cashflow")), "operating_cashflow": num(r.get("operating_cashflow")),
        "employees": num(r.get("employees")), "revenue_per_employee": num(r.get("revenue_per_employee")),
        "shares_outstanding": num(r.get("shares_outstanding")), "float_shares": num(r.get("float_shares")),
        "average_volume": num(r.get("average_volume")),
        "fifty_two_week_high": num(r.get("fifty_two_week_high")), "fifty_two_week_low": num(r.get("fifty_two_week_low")),
        "currency": r.get("currency"),
        "market_cap_rank": int((f["market_cap"] > r["market_cap"]).sum() + 1) if pd.notna(r["market_cap"]) else None,
        "sector_cap_rank": int((peers["market_cap"] > r["market_cap"]).sum() + 1) if pd.notna(r["market_cap"]) else None,
        "sector_size": int(len(peers)), "universe": int(len(f)),
    }

    # peers table (same sector, closest by market cap)
    pf = peers.copy()
    if pd.notna(r["market_cap"]):
        pf["_d"] = (np.log(pf["market_cap"].clip(lower=1)) - np.log(max(r["market_cap"], 1))).abs()
        pf = pf.sort_values("_d")
    cols = ["symbol", "security_name", "market_cap", "profit_margins", "operating_margins", "revenue_growth",
            "debt_to_equity", "current_ratio", "trailing_pe", "beta"]
    peer_rows = [{c: (num(x[c]) if c not in ("symbol", "security_name") else x[c]) for c in cols}
                 for _, x in pf.head(9).iterrows()]

    # ESG x financial materiality bridge
    bridge = None
    if esg_row is not None:
        pen = float(esg_row["total_current_penalty"])
        viol = int(esg_row["n_violations"])
        emp = num(r.get("employees"))
        bridge = {
            "penalties": pen, "violations": viol, "inspections": int(esg_row.get("n_inspections", 0) or 0),
            "pct_of_revenue": pen / r["total_revenue"] if pd.notna(r["total_revenue"]) and r["total_revenue"] else None,
            "pct_of_free_cashflow": pen / r["free_cashflow"] if pd.notna(r["free_cashflow"]) and r["free_cashflow"] > 0 else None,
            "pct_of_net_income": (pen / (r["profit_margins"] * r["total_revenue"]) if pd.notna(r["profit_margins"]) and pd.notna(r["total_revenue"]) and r["profit_margins"] * r["total_revenue"] > 0 else None),
            "violations_per_1000_employees": viol / emp * 1000 if emp else None,
            "risk_tier": esg_row["risk_tier"], "composite_score": float(esg_row["composite_score"]),
        }

    hist = history_block(sym, allow_live=allow_live)
    if hist["prices"]["available"]:
        snapshot["last_price"] = hist["prices"]["last_price"]

    out = {
        "symbol": sym, "name": r["security_name"], "sector": sector, "industry": r.get("industry_yf"),
        "business_summary": r.get("long_business_summary") if pd.notna(r.get("long_business_summary")) else None,
        "snapshot": snapshot, "groups": groups, "scorecard": score, "overall_score": overall,
        "peers": peer_rows, "esg_bridge": bridge, "history": hist,
        "risk_tier": esg_row["risk_tier"] if esg_row is not None else None,
        "composite_score": float(esg_row["composite_score"]) if esg_row is not None else None,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    out["narrative"] = _fin_narrative(out, flat, peers, f)
    out["highlights"] = _fin_highlights(out, flat)
    return clean(out)


def _fin_highlights(o, flat) -> dict:
    strengths, concerns = [], []
    for k, i in flat.items():
        p = i["health_percentile"]
        if p is None or i["value"] is None:
            continue
        line = f"{i['label']} {_fmt(i['value'], i['kind'])} (healthier than {p:.0f}% of the universe)"
        if p >= 80:
            strengths.append((p, line))
        elif p <= 20:
            concerns.append((100 - p, line.replace("healthier than", "weaker than") .replace(f"{p:.0f}%", f"{100 - p:.0f}%")))
    strengths.sort(reverse=True); concerns.sort(reverse=True)
    return {"strengths": [s for _, s in strengths[:5]], "concerns": [c for _, c in concerns[:5]]}


def _fin_narrative(o, flat, peers, f) -> list[dict]:
    s, name = o["snapshot"], o["name"]
    v = lambda k: flat[k]["value"] if k in flat else None
    secs = []
    t = (f"{name} ({o['symbol']}) is a {o['sector']} company"
         + (f" in {o['industry']}" if o.get("industry") else "")
         + f", ranked #{s['market_cap_rank']} by market capitalisation of {s['universe']} tracked companies"
         + (f" and #{s['sector_cap_rank']} of {s['sector_size']} in its sector" if s.get("sector_cap_rank") else "")
         + f". Market value is {money(s['market_cap'])} against {money(s['total_revenue'])} of revenue and {money(s['total_cash'])} of cash. ")
    if o["overall_score"] is not None:
        t += f"The composite financial-health score is {o['overall_score']:.0f}/100 (50 = universe median)."
    secs.append({"title": "Company profile & standing", "text": t})

    t = ""
    if v("operating_margins") is not None:
        pm = flat["operating_margins"]
        t += (f"Operating margin is {pm['value']:.1%} versus a sector median of {pm['sector_median']:.1%}. " if pm["sector_median"] is not None else f"Operating margin is {pm['value']:.1%}. ")
    if v("profit_margins") is not None:
        t += f"Net margin is {v('profit_margins'):.1%}"
        if v("return_on_equity") is not None:
            t += f" and return on equity {v('return_on_equity'):.1%}"
        t += ". "
    if v("revenue_growth") is not None:
        t += f"Revenue is growing {v('revenue_growth'):.1%} year-over-year"
        t += (f" while earnings are {'up' if v('earnings_growth') >= 0 else 'down'} {abs(v('earnings_growth')):.1%}. " if v("earnings_growth") is not None else ". ")
    if t:
        secs.append({"title": "Profitability & growth", "text": t.strip()})

    t = ""
    if v("debt_to_equity") is not None:
        t += f"Debt-to-equity is {v('debt_to_equity'):.0f}% (sector median {flat['debt_to_equity']['sector_median']:.0f}%). " if flat["debt_to_equity"]["sector_median"] is not None else f"Debt-to-equity is {v('debt_to_equity'):.0f}%. "
    if s["net_debt"] is not None:
        t += (f"The company holds net debt of {money(s['net_debt'])}" if s["net_debt"] > 0 else f"The company holds net cash of {money(-s['net_debt'])}")
        if v("net_debt_to_ebitda") is not None:
            t += f", equal to {v('net_debt_to_ebitda'):.1f}x EBITDA"
        t += ". "
    if v("current_ratio") is not None:
        cr = v("current_ratio")
        t += f"The current ratio of {cr:.2f} " + ("indicates comfortable short-term liquidity. " if cr >= 1.5 else "is adequate. " if cr >= 1 else "is below 1, meaning short-term obligations exceed liquid assets. ")
    if t:
        secs.append({"title": "Balance sheet & liquidity", "text": t.strip()})

    t = ""
    if s["free_cashflow"] is not None:
        t += f"Free cash flow is {money(s['free_cashflow'])}"
        if v("fcf_margin") is not None:
            t += f" ({v('fcf_margin'):.1%} of revenue"
            t += f", {v('fcf_yield'):.1%} yield on market cap)" if v("fcf_yield") is not None else ")"
        t += ". "
    if v("fcf_conversion") is not None:
        t += f"{v('fcf_conversion'):.0%} of operating cash flow converts to free cash flow after capital spending. "
    if t:
        secs.append({"title": "Cash generation", "text": t.strip()})

    t = ""
    if v("beta") is not None:
        t += f"Beta of {v('beta'):.2f} means the stock has historically moved {'more' if v('beta') > 1 else 'less'} than the market. "
    if v("ann_volatility") is not None:
        t += f"Annualised volatility is {v('ann_volatility'):.1%} ({ordinal(flat['ann_volatility']['universe_percentile'])} percentile). "
    if v("max_drawdown") is not None:
        t += f"The worst peak-to-trough decline was {v('max_drawdown'):.1%}. "
    if t:
        secs.append({"title": "Market risk", "text": t.strip()})

    b = o.get("esg_bridge")
    if b:
        t = f"OSHA penalties of {money(b['penalties'])} across {b['violations']:,} citations "
        if b["pct_of_revenue"] is not None:
            t += f"equal {b['pct_of_revenue']:.4%} of annual revenue"
            t += f" and {b['pct_of_free_cashflow']:.2%} of free cash flow" if b["pct_of_free_cashflow"] is not None else ""
            t += ". "
        if b["violations_per_1000_employees"] is not None:
            t += f"That is {b['violations_per_1000_employees']:.1f} citations per 1,000 employees. "
        t += ("Direct penalties are small relative to earnings; the larger financial exposure is reputational and operational (disruption, insurance, remediation)."
              if (b["pct_of_free_cashflow"] or 0) < 0.02 else
              "Penalties are a meaningful share of free cash flow, so enforcement outcomes are financially material.")
        secs.append({"title": "ESG ↔ financial materiality", "text": t})

    h = o["history"]["prices"]
    if h.get("available"):
        secs.append({"title": "Price history", "text": (
            f"Between {h['start']} and {h['end']} the stock compounded at {h['cagr']:.1%} per year. "
            f"Its deepest decline was {h['max_drawdown']:.1%} (trough {h['max_drawdown_date']}). "
            f"It closed up on {h['pct_up_days']:.0%} of trading days; the best day was {h['best_day']:+.1%} and the worst {h['worst_day']:+.1%}.")})
    return secs


# --------------------------------------------------------------------------- Financial list (page-level)
def financial_list(limit: int = 500) -> dict:
    f = fin_table()
    uni = dash._load()[["symbol", "canonical_name", "gics_sector", "risk_tier", "composite_score"]]
    d = f.reset_index(drop=True).merge(uni, on="symbol", how="left")
    d["canonical_name"] = d["canonical_name"].fillna(d["security_name"])
    d["gics_sector"] = d["gics_sector"].fillna(d["sector"])
    total_cap = d["market_cap"].sum()
    d["cap_share"] = d["market_cap"] / total_cap
    d = d.sort_values("market_cap", ascending=False)
    cols = ["symbol", "canonical_name", "gics_sector", "market_cap", "cap_share", "profit_margins", "operating_margins",
            "debt_to_equity", "current_ratio", "revenue_growth", "trailing_pe", "beta", "risk_tier", "composite_score"]
    rows = d.head(limit)[cols].to_dict("records")
    b = d["beta"].dropna()
    edges = [(-9, 0.6, "<0.6"), (0.6, 0.9, "0.6-0.9"), (0.9, 1.1, "0.9-1.1"), (1.1, 1.4, "1.1-1.4"), (1.4, 99, ">1.4")]
    return clean({
        "results": rows, "n": int(len(d)), "aggregate_market_cap": float(total_cap),
        "mean_profit_margin": float(d["profit_margins"].mean()),
        "negative_margin_count": int((d["profit_margins"] < 0).sum()),
        "high_leverage_count": int((d["debt_to_equity"] > 150).sum()),
        "beta_buckets": [{"label": l, "count": int(((b >= lo) & (b < hi)).sum())} for lo, hi, l in edges],
    })


# --------------------------------------------------------------------------- Signals engine
SEV_LABEL = [(9, "Critical"), (7, "High"), (5, "Medium"), (0, "Low")]


def _sev_label(s):
    return next(l for t, l in SEV_LABEL if s >= t)


def _age(d):
    if d is None or pd.isna(d):
        return "ongoing"
    days = (pd.Timestamp("today").normalize() - pd.Timestamp(d)).days
    if days < 0:
        days = 0
    if days < 45:
        return f"{days}d ago"
    if days < 700:
        return f"{round(days / 30)}mo ago"
    return f"{days / 365.25:.1f}y ago"


@lru_cache(maxsize=1)
def signals_table() -> list[dict]:
    uni = dash._load()
    fin = fin_table()
    geo = geo_table()
    q = lambda c, p: uni[c].quantile(p)
    safety_hi, env_hi = q("safety_kw_per_1k", 0.85), q("environment_kw_per_1k", 0.85)
    gov_lo = q("governance_kw_per_1k", 0.10)
    vol_hi = q("ann_volatility", 0.85) if "ann_volatility" in uni else None
    v = viol_table()
    pen_p90 = v["penalty"].quantile(0.97)
    sigs: list[dict] = []

    def add(sym, name, code, cat, sev, headline, tiers, date=None, detail=None):
        sigs.append({
            "id": f"{sym}-{code}-{len(sigs)}", "symbol": sym, "entity_symbol": sym, "entity_name": name,
            "signal_code": code, "category": cat, "severity": float(sev), "severity_label": _sev_label(sev),
            "headline": headline, "tiers": tiers, "date": pd.Timestamp(date).strftime("%Y-%m-%d") if date is not None and pd.notna(date) else None,
            "age": _age(date), "detail": detail,
        })

    name_of = dict(zip(uni["symbol"], uni["canonical_name"]))
    corro = dict(zip(uni["symbol"], uni["corroboration_count"]))

    # ---- OSHA: individual willful / repeat / very large citations
    big = v[(v["viol_type"].isin(["W", "R"])) | (v["penalty"] >= pen_p90)]
    for x in big.itertuples():
        sym = x.ticker
        if sym not in name_of:
            continue
        t = VIOL_TYPES.get(x.viol_type, (x.viol_type,))[0]
        std = OSHA_STD.get(x.std, f"standard {x.std}")
        sev = {"W": 10, "R": 8}.get(x.viol_type, 6) + (1 if x.penalty >= 100_000 else 0)
        sev = min(10, sev + (1 if x.viol_type == "R" and x.penalty >= 50_000 else 0))
        cat = "labor" if x.viol_type in ("W", "R", "S") else "regulatory"
        add(sym, name_of[sym], f"OSHA_{x.viol_type}_CITATION", cat, sev,
            f"{t} citation: {std}" + (f" ({money(x.penalty)} penalty)" if x.penalty > 0 else ""),
            ["OSHA"], x.date, f"Standard {x.std}; workers exposed: {int(x.nr_exposed) if pd.notna(x.nr_exposed) else 'n/a'}")

    # ---- OSHA: penalty-year spikes (company-years in the top decile)
    cy = v.dropna(subset=["year"]).groupby(["ticker", "year"]).agg(n=("penalty", "size"), pen=("penalty", "sum")).reset_index()
    cut = cy["pen"].quantile(0.92)
    for x in cy[cy["pen"] >= cut].itertuples():
        if x.ticker not in name_of:
            continue
        rank = (cy["pen"] < x.pen).mean()
        add(x.ticker, name_of[x.ticker], "OSHA_PENALTY_SPIKE", "regulatory", round(5 + 4 * rank, 1),
            f"{int(x.year)}: {x.n} citations and {money(x.pen)} in penalties (top {100 - rank * 100:.0f}% of company-years)",
            ["OSHA"], pd.Timestamp(int(x.year), 12, 31), None)

    # ---- 10-K text signals, market, geo
    for u in uni.itertuples():
        sym = u.symbol
        if u.safety_kw_per_1k >= safety_hi:
            p = pct_rank(uni["safety_kw_per_1k"], u.safety_kw_per_1k)
            add(sym, u.canonical_name, "TENK_SAFETY_DENSITY", "labor", 4 + 4 * (p - 85) / 15,
                f"10-K discusses workplace safety at {u.safety_kw_per_1k:.3f} terms/1k words ({ordinal(p)} percentile)", ["10-K"])
        if u.environment_kw_per_1k >= env_hi:
            p = pct_rank(uni["environment_kw_per_1k"], u.environment_kw_per_1k)
            add(sym, u.canonical_name, "TENK_ENV_DENSITY", "environmental", 3.5 + 4 * (p - 85) / 15,
                f"Heavy environmental disclosure: {u.environment_kw_per_1k:.2f} terms/1k words ({ordinal(p)} percentile)", ["10-K"])
        if u.governance_kw_per_1k <= gov_lo:
            add(sym, u.canonical_name, "TENK_GOV_THIN", "governance", 4.5,
                f"Thin governance disclosure: {u.governance_kw_per_1k:.2f} terms/1k words (bottom decile)", ["10-K"])
        vol = getattr(u, "ann_volatility", np.nan)
        if vol_hi is not None and pd.notna(vol) and vol >= vol_hi:
            p = pct_rank(uni["ann_volatility"], vol)
            add(sym, u.canonical_name, "MKT_VOLATILITY", "market", 4 + 4 * (p - 85) / 15,
                f"Annualised volatility {vol:.0%} is in the {ordinal(p)} percentile", ["MARKET"])
        if sym in fin.index:
            dd = fin.loc[sym, "max_drawdown"]
            if pd.notna(dd) and dd <= fin["max_drawdown"].quantile(0.07):
                add(sym, u.canonical_name, "MKT_DRAWDOWN", "market", 6, f"Maximum drawdown of {dd:.0%} is among the deepest tracked", ["MARKET"])
            de = fin.loc[sym, "debt_to_equity"]
            if pd.notna(de) and de >= fin["debt_to_equity"].quantile(0.95):
                add(sym, u.canonical_name, "FIN_LEVERAGE", "market", 5.5, f"Debt-to-equity of {de:.0f}% is in the top 5% of the universe", ["FINANCIAL"])
        if sym in geo.index and int(geo.loc[sym, "has_imagery"] or 0):
            lst = geo.loc[sym, "LST_Celsius"]
            if pd.notna(lst) and lst >= geo["LST_Celsius"].quantile(0.93):
                add(sym, u.canonical_name, "GEO_HEAT", "environmental", 5,
                    f"Facility area surface temperature {lst:.1f}°C is in the hottest 7% (heat-stress exposure)", ["SATELLITE"])

    # ---- news surge
    for sym in uni["symbol"]:
        d = news_for(sym)
        if d.empty or d["date"].isna().all():
            continue
        last = d["date"].max()
        n30 = int((d["date"] >= last - pd.Timedelta(days=30)).sum())
        span_m = max(1.0, (last - d["date"].min()).days / 30)
        avg = len(d) / span_m
        if n30 >= max(8, 2.2 * avg):
            add(sym, name_of[sym], "NEWS_SURGE", "media", min(8, 4 + n30 / max(avg, 1)),
                f"News volume surge: {n30} articles in 30 days vs {avg:.0f}/month average", ["NEWS"], last)

    for s in sigs:
        s["corroboration"] = int(corro.get(s["symbol"], 0))
    sigs.sort(key=lambda s: (-s["severity"], -(pd.Timestamp(s["date"]).value if s["date"] else 0)))
    return sigs


def signals_for(symbol: str) -> dict | None:
    r, df = _row(symbol)
    if r is None:
        return None
    sigs = [s for s in signals_table() if s["symbol"] == r["symbol"]]
    by_cat, by_sev = {}, {}
    for s in sigs:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1
        by_sev[s["severity_label"]] = by_sev.get(s["severity_label"], 0) + 1
    # timeline by year
    by_year = {}
    for s in sigs:
        if s["date"]:
            y = s["date"][:4]
            by_year.setdefault(y, {"year": int(y), "count": 0, "max_severity": 0})
            by_year[y]["count"] += 1
            by_year[y]["max_severity"] = max(by_year[y]["max_severity"], s["severity"])
    # universe context
    allc = pd.Series([s["symbol"] for s in signals_table()]).value_counts()
    mine = len(sigs)
    return clean({
        "symbol": r["symbol"], "canonical_name": r["canonical_name"], "gics_sector": r["gics_sector"],
        "risk_tier": r["risk_tier"], "composite_score": float(r["composite_score"]),
        "corroboration_count": int(r["corroboration_count"]), "status": r["status"],
        "total": mine,
        "universe_percentile": pct_rank(allc.reindex(df["symbol"]).fillna(0), mine),
        "universe_median": float(allc.reindex(df["symbol"]).fillna(0).median()),
        "by_category": [{"category": k, "count": v} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
        "by_severity": [{"label": l, "count": by_sev.get(l, 0)} for _, l in SEV_LABEL],
        "by_year": sorted(by_year.values(), key=lambda x: x["year"]),
        "signals": sigs,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


def signals_list(page=1, page_size=25, category=None, min_severity=None, q=None, symbol=None) -> dict:
    s = signals_table()
    if category:
        s = [x for x in s if x["category"] == category]
    if min_severity is not None:
        s = [x for x in s if x["severity"] >= min_severity]
    if symbol:
        s = [x for x in s if x["symbol"].upper() == symbol.upper()]
    if q:
        n = q.strip().lower()
        s = [x for x in s if n in x["headline"].lower() or n in x["entity_name"].lower() or n in x["symbol"].lower()]
    total = len(s)
    a = (page - 1) * page_size
    return clean({"results": s[a:a + page_size], "total": total, "page": page, "page_size": page_size,
                  "categories": sorted({x["category"] for x in signals_table()})})
