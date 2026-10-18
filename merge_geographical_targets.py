"""
merge_geographical_targets.py
---------------------------------
Merges OSHA target variables into the geographical/environmental dataset.
Separate from your main merge_targets.py because this file's company key
column is called `ticker`, not `symbol` like your other 4 files -- this
script renames it before merging so nothing silently comes back all-NaN.

Usage:
    python3 merge_geographical_targets.py \\
        --osha_targets data/registry/osha_targets.csv \\
        --geo geographical_dataset.csv
"""
import argparse
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--osha_targets", required=True)
ap.add_argument("--geo", default="geographical_dataset.csv")
args = ap.parse_args()

targets = pd.read_csv(args.osha_targets)[
    ["symbol", "target_class", "target_reg", "n_inspections", "n_violations", "total_current_penalty"]
]

df = pd.read_csv(args.geo)
before = len(df)

if "ticker" in df.columns and "symbol" not in df.columns:
    df = df.rename(columns={"ticker": "symbol"})

df = df.drop(columns=["target_class", "target_reg", "n_inspections", "n_violations", "total_current_penalty"],
             errors="ignore")
df = df.merge(targets, on="symbol", how="left")

assert len(df) == before, f"Row count changed during merge ({before} -> {len(df)}) -- stop and check."

df.to_csv(args.geo, index=False)

print(f"Updated {args.geo}: target_class distribution -> {df['target_class'].value_counts(dropna=False).to_dict()}")
n_missing = df["target_class"].isna().sum()
if n_missing:
    print(f"WARNING: {n_missing} companies got no target match -- check symbol overlap with osha_targets.csv")