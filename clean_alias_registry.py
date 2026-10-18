"""
clean_alias_registry.py
Fixes a systemic bug in the alias-building step: it parsed SEC Exhibit 21
"subsidiaries of the registrant" tables line-by-line and kept EVERY line as
an alias -- including table headers, ownership percentages, and bare
jurisdiction/country/city names ("Delaware, USA", "<0.0001%", "State of
Incorporation...", "USA", "Kuala Lumpur"). These get used in a LIKE
substring match against nationwide OSHA establishment names, so a bare
"USA" or "Asia" alias will match huge numbers of unrelated companies.

This script filters the registry down to plausible real company/subsidiary
names, using layered rules (see comments below), and writes:
    - company_registry_verified.csv   (cleaned, safe to re-fetch or re-verify with)
    - dropped_aliases_audit.csv       (every row removed + which rule caught it)

Nothing here calls the API -- pure local text filtering.

Usage:
    python3 clean_alias_registry.py --registry data/registry/company_registry_clean.csv \\
        --out data/registry/company_registry_verified.csv \\
        --audit data/registry/dropped_aliases_audit.csv
"""
import argparse
import re
import pandas as pd

US_STATES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
    "south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    "district of columbia",
}

COUNTRIES_REGIONS_CITIES = {
    "usa","u.s.","u.s.a.","united states","united states of america",
    "asia","africa","europe","australia","canada","mexico","china","japan",
    "india","brazil","russia","togo","saudi arabia","kuala lumpur",
    "trinidad and tobago","trinidad and tobago unlimited","cote d'ivore",
    "cote d'ivoire","british virgin islands","british columbia",
    "new south wales","queensland","australian capital territory",
    "nevada, usa","delaware, usa","new south wales, australia",
    "queensland, australia","zug","guam","malta","singapore","hong kong",
    "taiwan","thailand","vietnam","indonesia","philippines","pakistan",
    "kazakhstan","turkey","poland","portugal","spain","italy","germany",
    "netherlands","belgium","france","sweden","norway","denmark","finland",
    "switzerland","austria","israel","egypt","kenya","tanzania","uganda",
    "guatemala","honduras","peru","chile","argentina","colombia","ecuador",
    "paraguay","suriname","barbados","fiji","papua new guinea","solomon islands",
}

HEADER_PHRASE_PATTERNS = [
    r"state of.*incorporat", r"percent of.*capital", r"names? under which",
    r"parent of", r"name of.*subsidiary", r"ownership\*?$",
    r"as of (january|february|march|april|may|june|july|august|september|october|november|december)",
]

# Known-safe short strings we do NOT want auto-dropped despite being <=4 chars --
# confirmed distinctive enough in earlier manual review this session.
SHORT_ALLOWLIST = {"pg&e", "uber", "3m company"}


def classify(alias: str) -> str | None:
    """Returns the drop reason, or None if the alias should be kept."""
    if not isinstance(alias, str) or not alias.strip():
        return "empty"
    a = alias.strip()
    a_lower = a.lower()

    # Numeric / percentage / ownership-fraction rows
    if re.match(r"^[<>]?\s*[\d.,]+%?$", a) or "%" in a:
        return "numeric_or_percentage"

    # Bare jurisdiction / country / region / city names
    if a_lower in US_STATES or a_lower in COUNTRIES_REGIONS_CITIES:
        return "jurisdiction_or_geography"
    # "City, Country" or "State, Country" patterns like "Delaware, USA"
    if "," in a and any(part.strip().lower() in US_STATES | COUNTRIES_REGIONS_CITIES
                          for part in a.split(",")):
        return "jurisdiction_or_geography"

    # Table header / boilerplate phrases from Exhibit 21 tables
    for pat in HEADER_PHRASE_PATTERNS:
        if re.search(pat, a_lower):
            return "table_header_boilerplate"

    # Footnote-style rows, e.g. "(1) This subsidiary also conducts business..."
    if re.match(r"^\(\d+\)", a):
        return "footnote_text"

    # Very short generic strings -- high false-positive risk in a substring match,
    # unless explicitly allowlisted as confirmed-safe.
    if len(a) <= 4 and a_lower not in SHORT_ALLOWLIST:
        return "too_short_generic"

    return None  # keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit", required=True)
    args = ap.parse_args()

    reg = pd.read_csv(args.registry)
    if "alias" not in reg.columns:
        raise SystemExit(f"--registry must have an 'alias' column. Found: {reg.columns.tolist()}")

    reg["_drop_reason"] = reg["alias"].apply(classify)
    dropped = reg[reg["_drop_reason"].notna()].copy()
    kept = reg[reg["_drop_reason"].isna()].drop(columns=["_drop_reason"])

    kept.to_csv(args.out, index=False)
    dropped.to_csv(args.audit, index=False)

    print(f"Started with {len(reg):,} (company, alias) rows across {reg['company_id'].nunique()} companies")
    print(f"Kept:    {len(kept):,} rows")
    print(f"Dropped: {len(dropped):,} rows -- see {args.audit}")
    print("\nDrop reasons breakdown:")
    print(dropped["_drop_reason"].value_counts())

    # Flag companies that would have ZERO aliases left -- these need a manual
    # real alias added before any re-verification/re-fetch will find anything.
    kept_companies = set(kept["company_id"])
    all_companies = set(reg["company_id"])
    orphaned = all_companies - kept_companies
    if orphaned:
        print(f"\nWARNING: {len(orphaned)} companies have ZERO safe aliases left after cleaning: {sorted(orphaned)}")
        print("These need at least one manually-verified real alias before re-verification will find any matches.")


if __name__ == "__main__":
    main()