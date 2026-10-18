"""
build_esg_fulltext.py
Extracts full cleaned text from each company's 10-K (esg_reports/<TICKER>/*.htm)
into a single parquet file -- one row per company -- ready for tokenization /
embedding / classifier training.

Output: output/esg_fulltext.parquet
Columns:
    symbol          str
    word_count      int
    full_text       str   (cleaned, tags/scripts/styles stripped, entities decoded)
    data_quality_flag  str  (same flags as esg_dataset.csv: ok / 10K_A_amendment_only_not_full_filing / no_10k_found)
    target_class    float (empty placeholder, filled by merge_targets.py)
    target_reg      float (empty placeholder, filled by merge_targets.py)

NOTE on scale: full text pushes this file to several hundred MB even with
parquet compression, because 10-Ks run up to ~350k words each. This is
expected and fine for parquet -- just don't try to open it in Excel.

NOTE for training: full text exceeds every transformer's context window.
Chunk (sliding window / section-based / truncate) at training time, not here --
keeping full text in storage keeps your options open (e.g. switching chunking
strategy later without re-scraping).
"""
import re
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path("/Users/shriya/Documents/esg fresh/newwork")
fundamentals = pd.read_csv(BASE / "financials/fundamentals.csv")
symbols = fundamentals[["symbol"]].drop_duplicates()

NO_FILING = {"XOM", "FDXF", "HONA"}
AMENDMENT_ONLY = {"MO", "ALB", "MOS", "LUV"}

TAG_RE = re.compile(rb"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
ANY_TAG_RE = re.compile(rb"<[^>]+>")
WORD_RE = re.compile(r"\w+")
WHITESPACE_RE = re.compile(r"[ \t]+")
BLANKLINES_RE = re.compile(r"\n{3,}")

ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&rsquo;": "'", "&lsquo;": "'",
    "&rdquo;": '"', "&ldquo;": '"', "&mdash;": "-", "&ndash;": "-",
}

def clean_text(path: Path) -> str:
    raw = path.read_bytes()
    raw = TAG_RE.sub(b" ", raw)
    raw = ANY_TAG_RE.sub(b" ", raw)
    text = raw.decode("utf-8", errors="ignore")
    for ent, repl in ENTITY_MAP.items():
        text = text.replace(ent, repl)
    text = re.sub(r"&#?\w+;", " ", text)  # any remaining entities
    text = WHITESPACE_RE.sub(" ", text)
    text = BLANKLINES_RE.sub("\n\n", text)
    return text.strip()

def flag(sym: str) -> str:
    if sym in NO_FILING:
        return "no_10k_found"
    if sym in AMENDMENT_ONLY:
        return "10K_A_amendment_only_not_full_filing"
    return "ok"

rows = []
for sym in symbols["symbol"]:
    company_dir = BASE / "esg_reports" / sym
    htm_files = list(company_dir.glob("*.htm")) if company_dir.exists() else []
    if not htm_files:
        rows.append({"symbol": sym, "word_count": 0, "full_text": "",
                     "data_quality_flag": flag(sym)})
        continue
    fp = max(htm_files, key=lambda p: p.stat().st_size)
    text = clean_text(fp)
    word_count = len(WORD_RE.findall(text))
    rows.append({"symbol": sym, "word_count": word_count, "full_text": text,
                 "data_quality_flag": flag(sym)})

out = pd.DataFrame(rows)
out["target_class"] = np.nan
out["target_reg"] = np.nan

out_path = BASE / "output" / "esg_fulltext.parquet"
out.to_parquet(out_path, index=False, compression="zstd")
print(f"Wrote {out_path} shape={out.shape}")
print(f"File size: {out_path.stat().st_size / 1e6:.1f} MB")
print(out[["symbol", "word_count", "data_quality_flag"]].head(5))