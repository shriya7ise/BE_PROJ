"""
verify_matches_locally.py
Re-checks every already-fetched inspection row against the CLEANED alias
list (from clean_alias_registry.py) -- purely local text matching, no API
calls. A row is kept only if its estab_name actually contains at least one
of that company's verified-safe aliases as a substring (case-insensitive),
which is the same criterion the original fetch used, just re-applied with
garbage aliases removed from the candidate list.

Violations are then filtered to match: only violation rows whose
activity_nr survives in the cleaned inspection set are kept, since that's
the only linkage that exists between the two files.

Outputs:
    inspection_by_company_verified.csv
    violation_by_company_verified.csv
    verification_report.csv   -- per-company before/after row counts, so you
                                  can see exactly which companies lost rows
                                  (and which, like Newmont, may drop to zero)

Usage:
    python3 verify_matches_locally.py \\
        --inspection data/raw/osha_api/inspection_by_company.csv \\
        --violation data/raw/osha_api/violation_by_company.csv \\
        --verified-registry data/registry/company_registry_verified.csv \\
        --outdir data/raw/osha_api
"""
import argparse
from pathlib import Path

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspection", required=True)
    ap.add_argument("--violation", required=True)
    ap.add_argument("--verified-registry", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    insp = pd.read_csv(args.inspection, low_memory=False)
    viol = pd.read_csv(args.violation, low_memory=False)
    reg = pd.read_csv(args.verified_registry)

    if "_matched_company_id" not in insp.columns or "estab_name" not in insp.columns:
        raise SystemExit(f"inspection file missing _matched_company_id/estab_name. "
                          f"Found: {insp.columns.tolist()}")

    # company_id -> list of safe aliases, lowercased for matching
    safe_aliases = reg.groupby("company_id")["alias"].apply(
        lambda s: [str(a).lower() for a in s if isinstance(a, str) and a.strip()]
    ).to_dict()

    def row_is_verified(row) -> bool:
        cid = row["_matched_company_id"]
        estab = str(row.get("estab_name", "")).lower()
        aliases = safe_aliases.get(cid, [])
        return any(alias in estab for alias in aliases)

    print(f"Re-verifying {len(insp):,} inspection rows against cleaned aliases...")
    insp["_verified"] = insp.apply(row_is_verified, axis=1)

    before_counts = insp.groupby("_matched_company_id").size().rename("rows_before")
    insp_verified = insp[insp["_verified"]].drop(columns=["_verified"])
    after_counts = insp_verified.groupby("_matched_company_id").size().rename("rows_after")

    report = pd.concat([before_counts, after_counts], axis=1).fillna(0).astype(int)
    report["rows_dropped"] = report["rows_before"] - report["rows_after"]
    report["dropped_to_zero"] = (report["rows_before"] > 0) & (report["rows_after"] == 0)
    report = report.sort_values("rows_dropped", ascending=False)
    report.to_csv(outdir / "verification_report.csv")

    insp_out = outdir / "inspection_by_company_verified.csv"
    insp_verified.to_csv(insp_out, index=False)

    # --- Filter violations to only activity_nr values that survived verification ---
    surviving_activity_nrs = set(insp_verified["activity_nr"])
    viol_verified = viol[viol["activity_nr"].isin(surviving_activity_nrs)]
    viol_out = outdir / "violation_by_company_verified.csv"
    viol_verified.to_csv(viol_out, index=False)

    print(f"\nInspection rows: {len(insp):,} -> {len(insp_verified):,} "
          f"({len(insp) - len(insp_verified):,} dropped as garbage-alias-only matches)")
    print(f"Violation rows:  {len(viol):,} -> {len(viol_verified):,} "
          f"({len(viol) - len(viol_verified):,} dropped, following the same activity_nr set)")
    print(f"\nWrote {insp_out}")
    print(f"Wrote {viol_out}")
    print(f"Wrote {outdir / 'verification_report.csv'}")

    dropped_to_zero = report[report["dropped_to_zero"]]
    if len(dropped_to_zero) > 0:
        print(f"\n{len(dropped_to_zero)} companies dropped from >0 rows to ZERO "
              f"-- their entire matched history was garbage-alias-only:")
        print(dropped_to_zero.index.tolist())
        print("These likely need a manually-verified real alias added before they'll "
              "show any legitimate OSHA history.")


if __name__ == "__main__":
    main()