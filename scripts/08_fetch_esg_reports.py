#!/usr/bin/env python3
"""
fetch_esg_reports.py – reliable 10-K (and optional sustainability) fetcher
"""

import os
import json
import time
import logging
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
USER_AGENT = "shriya.ise@vit.edu.in"   # ← CHANGE THIS
SEC_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}
SEC_WWW_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
}

TICKERS_FILE = "tickers.txt"          # one ticker per line
OUT_DIR = Path("esg_reports")
SLEEP = 0.15                          # SEC asks for ≤10 req/s; be polite
MAX_WORKERS = 4                       # parallel downloads of actual filings
RESUME = True                         # skip tickers that already have a 10-K

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def load_tickers() -> List[str]:
    with open(TICKERS_FILE) as f:
        return [t.strip().upper() for t in f if t.strip()]

def get_cik_map() -> Dict[str, str]:
    """Download the official SEC ticker → CIK mapping once."""
    url = "https://www.sec.gov/files/company_tickers.json"
    r = requests.get(url, headers=SEC_WWW_HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    mapping = {}
    for item in data.values():
        ticker = item["ticker"].upper()
        cik = str(item["cik_str"]).zfill(10)
        mapping[ticker] = cik
    return mapping

def fetch_submissions(cik: str) -> Optional[dict]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"submissions failed for CIK {cik}: {e}")
        return None

def find_latest_10k(submissions: dict) -> Optional[dict]:
    """Return the most recent 10-K (or 10-K/A) filing metadata."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    for i, form in enumerate(forms):
        if form in ("10-K", "10-K/A"):
            return {
                "form": form,
                "accession": accessions[i].replace("-", ""),
                "primary_doc": primary_docs[i],
                "filing_date": filing_dates[i],
                "report_date": report_dates[i] if i < len(report_dates) else None,
            }
    return None

def download_filing(cik: str, accession: str, primary_doc: str, dest: Path) -> bool:
    """Download the primary document (usually HTML) of a filing."""
    # SEC path: /Archives/edgar/data/{cik_no_zeros}/{accession}/{primary_doc}
    cik_int = str(int(cik))          # no leading zeros for the path
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{primary_doc}"
    try:
        r = requests.get(url, headers=SEC_WWW_HEADERS, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        log.warning(f"download failed {url}: {e}")
        return False

def process_ticker(ticker: str, cik_map: Dict[str, str]) -> str:
    out_ticker = OUT_DIR / ticker
    out_ticker.mkdir(parents=True, exist_ok=True)

    # Resume check
    existing_10k = list(out_ticker.glob("*10-K*.htm*")) + list(out_ticker.glob("*10-K*.html"))
    if RESUME and existing_10k:
        return f"SKIP (already have 10-K)"

    cik = cik_map.get(ticker)
    if not cik:
        return "NO_CIK"

    time.sleep(SLEEP)
    subs = fetch_submissions(cik)
    if not subs:
        return "NO_SUBMISSIONS"

    filing = find_latest_10k(subs)
    if not filing:
        return "NO_10K"

    # Build a clean filename
    fname = f"{ticker}_{filing['filing_date']}_{filing['form'].replace('/', '-')}_{filing['primary_doc']}"
    dest = out_ticker / fname

    ok = download_filing(cik, filing["accession"], filing["primary_doc"], dest)
    if ok:
        # Also write a small metadata sidecar
        meta = {
            "ticker": ticker,
            "cik": cik,
            "form": filing["form"],
            "filing_date": filing["filing_date"],
            "report_date": filing["report_date"],
            "accession": filing["accession"],
            "primary_doc": filing["primary_doc"],
            "local_path": str(dest),
        }
        (out_ticker / f"{ticker}_10k_meta.json").write_text(json.dumps(meta, indent=2))
        return f"OK 10-K {filing['filing_date']}"
    return "DOWNLOAD_FAILED"

# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────
def main():
    OUT_DIR.mkdir(exist_ok=True)
    tickers = load_tickers()
    log.info(f"Loaded {len(tickers)} tickers")

    log.info("Fetching official CIK mapping …")
    cik_map = get_cik_map()
    log.info(f"CIK map ready ({len(cik_map)} entries)")

    results = {"OK": 0, "SKIP": 0, "NO_CIK": 0, "NO_SUBMISSIONS": 0,
               "NO_10K": 0, "DOWNLOAD_FAILED": 0}

    for i, ticker in enumerate(tickers, 1):
        status = process_ticker(ticker, cik_map)
        key = status.split()[0]
        results[key] = results.get(key, 0) + 1
        log.info(f"[{i}/{len(tickers)}] {ticker:6s} → {status}")

    log.info("─" * 40)
    log.info("Summary:")
    for k, v in results.items():
        log.info(f"  {k:18s}: {v}")

if __name__ == "__main__":
    main()