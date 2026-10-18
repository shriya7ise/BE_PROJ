"""
cap_aliases_per_company.py
For financial holding companies, PE firms, and REITs, Exhibit 21 subsidiary
lists aren't real name variants of the parent -- they're hundreds of
separate single-purpose entities (one portfolio company, or one property,
per subsidiary). Querying OSHA for each of these is mostly wasted API calls
against entities that structurally have no OSHA footprint of their own.

This caps each company to at most --max-aliases rows, always keeping:
    1. The canonical_name itself (if present as its own alias row)
    2. Then whichever other aliases come first in the file, up to the cap

This is a blunt cut, not a smart one -- for a PE firm with 1200+ portfolio
companies, there's no principled way to guess which few are "real" without
manual review, so this just accepts the loss of a few possible real matches
in exchange for making the fetch tractable. If you want deeper coverage
for a SPECIFIC company later, you can always add its known real operating
subsidiaries back in manually (same registry_patch pattern used for Lear).

Usage:
    python3 cap_aliases_per_company.py --registry data/registry_sp400/company_registry_verified.csv \\
        --out data/registry_sp400/company_registry_capped.csv \\
        --max-aliases 15
"""
import argparse
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--registry", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--max-aliases", type=int, default=15)
args = ap.parse_args()

reg = pd.read_csv(args.registry)
before_total = len(reg)
before_counts = reg.groupby("company_id").size()

def cap_group(g: pd.DataFrame) -> pd.DataFrame:
    if len(g) <= args.max_aliases:
        return g
    canonical_row = g[g["alias"] == g["canonical_name"]]
    rest = g[g["alias"] != g["canonical_name"]]
    keep_n_rest = max(0, args.max_aliases - len(canonical_row))
    return pd.concat([canonical_row, rest.head(keep_n_rest)])

# NOTE: deliberately NOT using groupby().apply() here -- newer pandas
# versions silently drop the grouping column from what's passed into the
# applied function (the include_groups behavior change), which would strip
# company_id out of the result entirely. A plain loop avoids that footgun.
capped_parts = []
for cid, g in reg.groupby("company_id", sort=False):
    capped_parts.append(cap_group(g))
capped = pd.concat(capped_parts, ignore_index=True)
capped.to_csv(args.out, index=False)

after_counts = capped.groupby("company_id").size()
affected = before_counts[before_counts > args.max_aliases]

print(f"Before: {before_total:,} rows across {reg['company_id'].nunique()} companies")
print(f"After:  {len(capped):,} rows")
print(f"Removed: {before_total - len(capped):,} rows")
print(f"\n{len(affected)} companies were over the cap of {args.max_aliases} and got trimmed:")
print(affected.sort_values(ascending=False).head(15))
print(f"\nWrote {args.out}")