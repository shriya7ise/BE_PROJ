#!/usr/bin/env python3
"""
refetch_missing_10k.py
Refetches the ORIGINAL 10-K (not 10-K/A, not amendments) for a specific
list of tickers, using SEC EDGAR's submissions API to find the correct
filing and its primary document, then downloading it into
esg_reports/{TICKER}/.

Targets: XOM (missing entirely), and ALB/DVN/LUV/MO/MOS/TSLA (currently
only have 10-K/A amendments on disk).

Uses the same folder/file naming convention as the original fetch script
so build_evidence.py and esg_features.py pick it up with no changes.
"""
import json
import time
from pathlib import Path

import requests

# SEC requires a descriptive User-Agent with contact info -- update the email
HEADERS = {"User-Agent": "BE_PROJ research shriya@example.com"}

ESG_DIR = Path("esg_reports")

# ticker -> CIK (10-digit, zero-padded). Fill in/verify before running.
TICKER_CIK = {
    "XOM": "0000034088",
    "ALB": "0000915913",
    "DVN": "0001090012",
    "LUV": "0000092380",
    "MO":  "0000764180",
    "MOS": "0001285785",
    "TSLA": "0001318605",
}


def get_primary_10k_filing(cik: str):
    """Query SEC submissions API, return the most recent NON-amendment
    10-K's accession number, primary document filename, and filing date."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    recent = data["filings"]["recent"]
    forms = recent["form"]
    accessions = recent["accessionNumber"]
    primary_docs = recent["primaryDocument"]
    filing_dates = recent["filingDate"]

    for i, form in enumerate(forms):
        if form == "10-K":  # exact match only -- excludes 10-K/A, 10-K405 etc.
            return {
                "accession": accessions[i],
                "primary_doc": primary_docs[i],
                "filing_date": filing_dates[i],
            }
    return None


def download_filing(cik: str, accession: str, primary_doc: str, out_path: Path):
    accession_nodash = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{primary_doc}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return url


def main():
    for ticker, cik in TICKER_CIK.items():
        print(f"\n[{ticker}] CIK={cik}")
        try:
            filing = get_primary_10k_filing(cik)
        except Exception as e:
            print(f"  ERROR fetching submissions: {e}")
            continue

        if not filing:
            print("  No exact-match 10-K found in recent filings -- check manually.")
            continue

        ticker_dir = ESG_DIR / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        fname = f"{ticker}_{filing['filing_date']}_10-K_{filing['primary_doc']}"
        out_path = ticker_dir / fname

        try:
            url = download_filing(cik, filing["accession"], filing["primary_doc"], out_path)
            print(f"  Downloaded: {url}")
            print(f"  Saved to:   {out_path}  ({out_path.stat().st_size // 1024} KB)")
        except Exception as e:
            print(f"  ERROR downloading: {e}")

        time.sleep(0.3)  # stay well under SEC's rate limit (10 req/sec)


if __name__ == "__main__":
    main()
