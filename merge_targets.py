"""
merge_targets.py
Run this AFTER build_osha_targets.py has produced osha_targets.csv.
Fills target_class / target_reg into ALL FIVE dataset files:
    - financials_dataset.csv   (1 row/company -- simple 1:1 merge)
    - news_dataset.csv         (1 row/company -- simple 1:1 merge)
    - esg_dataset.csv          (1 row/company -- simple 1:1 merge)
    - esg_training_set.parquet   (many rows/company -- label BROADCAST to every chunk)
    - news_training_set.parquet  (many rows/company -- label BROADCAST to every article)

The broadcast case is just a normal pandas merge on "symbol" -- since
osha_targets.csv has exactly one row per company and the training tables
have many rows per company, every row of a given company automatically
picks up that company's single label. This is standard weak/distant
supervision for long-document classification: no one hand-labeled
individual chunks/articles, so each inherits its parent company's label.

Usage:
    python3 merge_targets.py --osha_targets output/osha_targets.csv --outdir output
"""
import argparse
import pandas as pd
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--osha_targets", required=True)
ap.add_argument("--outdir", default="output")
args = ap.parse_args()

targets = pd.read_csv(args.osha_targets)[
    ["symbol", "target_class", "target_reg", "n_inspections", "n_violations", "total_current_penalty"]
]

outdir = Path(args.outdir)

# --- Company-level CSVs: simple 1:1 merge ---
for fname in ["financials_dataset.csv", "news_dataset.csv", "esg_dataset.csv"]:
    fp = outdir / fname
    if not fp.exists():
        print(f"Skipping {fname} (not found in {outdir})")
        continue
    df = pd.read_csv(fp)
    df = df.drop(columns=["target_class", "target_reg"], errors="ignore")
    df = df.merge(targets, on="symbol", how="left")
    df.to_csv(fp, index=False)
    print(f"Updated {fp}: target_class distribution -> {df['target_class'].value_counts(dropna=False).to_dict()}")

# --- Chunk/article-level parquets: same merge, but broadcasts to every row of a company ---
for fname in ["esg_training_set.parquet", "news_training_set.parquet"]:
    fp = outdir / fname
    if not fp.exists():
        print(f"Skipping {fname} (not found in {outdir})")
        continue
    df = pd.read_parquet(fp)
    df = df.drop(columns=["target_class", "target_reg"], errors="ignore")
    df = df.merge(targets, on="symbol", how="left")
    df.to_parquet(fp, index=False, compression="zstd")
    n_rows_labeled = df["target_class"].notna().sum()
    print(f"Updated {fp}: {n_rows_labeled}/{len(df)} rows now labeled "
          f"(broadcast from {df['symbol'].nunique()} companies)")