#!/usr/bin/env python3
"""
diagnose_filing_types.py
For every company in esg_reports/, checks what kind of filing the .htm
file actually is (10-K, 10-K/A, or something else/ambiguous), and flags
anything that isn't a clean primary 10-K -- so we catch ALB/MO/MOS/LUV-
style issues across all 289 before wasting time refetching one at a time.
"""
import re
from pathlib import Path

from bs4 import BeautifulSoup

ESG_DIR = Path("esg_reports")

def detect_filing_type(html_path: Path) -> str:
    with open(html_path, "r", errors="ignore") as f:
        content = f.read(200_000)  # header/type info is always near the top
    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text)

    # SEC filings declare their type explicitly, usually near the top
    m = re.search(r"\b(10-K/A|10-K405|10-KSB|10-K)\b", text[:5000])
    if m:
        return m.group(1)
    # fallback: check filename itself
    if "10-K-A" in html_path.name or "10KA" in html_path.name:
        return "10-K/A (from filename)"
    if "10-K" in html_path.name or "10K" in html_path.name:
        return "10-K (from filename, unconfirmed in text)"
    return "UNKNOWN"


def main():
    rows = []
    for ticker_dir in sorted(ESG_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        symbol = ticker_dir.name
        htm_files = list(ticker_dir.glob("*.htm"))

        if not htm_files:
            rows.append((symbol, "NO FILE", 0, "-"))
            continue

        for f in htm_files:
            size_kb = f.stat().st_size // 1024
            ftype = detect_filing_type(f)
            rows.append((symbol, f.name, size_kb, ftype))

    print(f"{'SYMBOL':<8}{'SIZE(KB)':<10}{'TYPE':<30}FILENAME")
    flagged = []
    for symbol, fname, size_kb, ftype in rows:
        print(f"{symbol:<8}{size_kb:<10}{ftype:<30}{fname}")
        if ftype != "10-K" or size_kb < 40:  # flag amendments + suspiciously small files
            flagged.append((symbol, fname, size_kb, ftype))

    print(f"\n--- FLAGGED ({len(flagged)}) ---")
    for symbol, fname, size_kb, ftype in flagged:
        print(f"{symbol:<8}{size_kb:<10}{ftype:<30}{fname}")


if __name__ == "__main__":
    main()
