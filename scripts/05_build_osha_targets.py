"""
scripts/05_build_osha_targets.py  (PATCHED)
---------------------------------
Same as before, with one fix: current_penalty is frequently null even when
initial_penalty has a real value (confirmed from a live sample row --
current_penalty=null, initial_penalty=4500.0). The original version only
fell back to a different penalty column when current_penalty was ENTIRELY
ABSENT from the dataframe -- but here it's present as a column, just mostly
null, so that fallback never triggered and target_reg was badly undercounting
severity. Now it coalesces row-by-row: use current_penalty where present,
fall back to initial_penalty where current_penalty is null.

INPUTS:
    --violation    data/raw/osha_api/violation_by_company.csv   (required)
    --inspection   data/raw/osha_api/inspection_by_company.csv  (optional)
    --registry     data/registry/company_registry_clean.csv     (for company_id -> ticker)

OUTPUT:
    data/registry/osha_targets.csv
    columns: symbol, company_id, n_inspections, n_violations, total_current_penalty,
             max_gravity, n_serious_violations, target_class, target_reg

Usage:
    python3 scripts/05_build_osha_targets.py \\
        --violation data/raw/osha_api/violation_by_company.csv \\
        --inspection data/raw/osha_api/inspection_by_company.csv \\
        --registry data/registry/company_registry_clean.csv \\
        --out data/registry/osha_targets.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def load_csv_safe(path: str) -> pd.DataFrame | None:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    df = pd.read_csv(p, low_memory=False)
    if df.empty:
        return None
    return df


def find_col(df: pd.DataFrame, candidates):
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--violation", required=True)
    ap.add_argument("--inspection", default=None)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", default="data/registry/osha_targets.csv")
    args = ap.parse_args()

    # --- company universe: unique company_id -> ticker ---
    registry = pd.read_csv(args.registry)
    for col in ("company_id", "ticker"):
        if col not in registry.columns:
            sys.exit(f"--registry must have a '{col}' column. Found: {registry.columns.tolist()}")
    companies = registry[["company_id", "ticker"]].drop_duplicates(subset="company_id")
    companies = companies.rename(columns={"ticker": "symbol"})

    # --- violations (required) ---
    viol = load_csv_safe(args.violation)
    if viol is None:
        sys.exit(
            f"'{args.violation}' is missing or empty. Run 04e_fetch_violations_by_activity.py first."
        )
    if "_matched_company_id" not in viol.columns:
        sys.exit(
            f"'{args.violation}' has no '_matched_company_id' column -- this doesn't look "
            f"like output from the per-alias fetch pipeline."
        )

    # FIX: coalesce current_penalty -> initial_penalty row-by-row, instead of
    # only falling back when the whole column is missing. current_penalty is
    # frequently null (e.g. before a contest is resolved) while
    # initial_penalty still holds the real assessed amount.
    current_col = find_col(viol, ["current_penalty"])
    initial_col = find_col(viol, ["initial_penalty"])
    other_penalty_col = find_col(viol, ["penalty", "final_penalty"])

    if current_col and initial_col:
        viol["_effective_penalty"] = viol[current_col].fillna(viol[initial_col]).fillna(0)
        n_backfilled = (viol[current_col].isna() & viol[initial_col].notna()).sum()
        print(f"Penalty coalescing: {n_backfilled:,} rows had null current_penalty but a real "
              f"initial_penalty -- backfilled instead of silently dropped/undercounted.")
    elif current_col:
        viol["_effective_penalty"] = viol[current_col].fillna(0)
    elif initial_col:
        viol["_effective_penalty"] = viol[initial_col].fillna(0)
    elif other_penalty_col:
        viol["_effective_penalty"] = viol[other_penalty_col].fillna(0)
    else:
        viol["_effective_penalty"] = 0.0
        print("WARNING: no penalty column found at all -- total_current_penalty will be 0 "
              "and target_reg will fall back to n_violations.")

    gravity_col = find_col(viol, ["gravity", "gravity_situation"])
    viol_type_col = find_col(viol, ["viol_type", "violation_type"])

    viol_agg = viol.groupby("_matched_company_id").agg(
        n_violations=("_matched_company_id", "count"),
        total_current_penalty=("_effective_penalty", "sum"),
        **({"max_gravity": (gravity_col, "max")} if gravity_col else {}),
    ).reset_index().rename(columns={"_matched_company_id": "company_id"})

    if viol_type_col:
        serious = viol[viol[viol_type_col].astype(str).str.upper().str.startswith("S", na=False)]
        n_serious = serious.groupby("_matched_company_id").size().reset_index(name="n_serious_violations")
        n_serious = n_serious.rename(columns={"_matched_company_id": "company_id"})
        viol_agg = viol_agg.merge(n_serious, on="company_id", how="left")
        viol_agg["n_serious_violations"] = viol_agg["n_serious_violations"].fillna(0)

    # --- inspections (optional) ---
    insp_agg = None
    if args.inspection:
        insp = load_csv_safe(args.inspection)
        if insp is not None:
            if "_matched_company_id" not in insp.columns:
                print(f"WARNING: '{args.inspection}' has no '_matched_company_id' column, skipping n_inspections.")
            else:
                id_col = "activity_nr" if "activity_nr" in insp.columns else insp.columns[0]
                insp_agg = insp.groupby("_matched_company_id")[id_col].nunique().reset_index(
                    name="n_inspections"
                ).rename(columns={"_matched_company_id": "company_id"})
        else:
            print(f"NOTE: '{args.inspection}' missing/empty -- n_inspections will be left out. "
                  f"Target variables still work fine from violations alone.")

    # --- assemble ---
    target_df = companies.merge(viol_agg, on="company_id", how="left")
    if insp_agg is not None:
        target_df = target_df.merge(insp_agg, on="company_id", how="left")

    fill_cols = ["n_violations", "total_current_penalty", "n_serious_violations", "n_inspections"]
    for c in fill_cols:
        if c in target_df.columns:
            target_df[c] = target_df[c].fillna(0)

    target_df["target_class"] = (target_df["n_violations"] > 0).astype(int)
    if "total_current_penalty" in target_df.columns and target_df["total_current_penalty"].sum() > 0:
        target_df["target_reg"] = target_df["total_current_penalty"]
    else:
        target_df["target_reg"] = target_df["n_violations"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target_df.to_csv(out_path, index=False)

    n_positive = int(target_df["target_class"].sum())
    print(f"Wrote {out_path} -- {len(target_df)} companies, {n_positive} with target_class=1 "
          f"({n_positive/len(target_df):.1%})")
    print(f"Columns: {target_df.columns.tolist()}")


if __name__ == "__main__":
    main()