#!/usr/bin/env python3
"""
fetch_news.py
-------------
Research-level news layer for the multimodal ESG risk stack.

Primary source : GDELT DOC 2.0 API  (no API key required)
Fallback       : yfinance news      (ticker-native, free)

Design goals
- Clean (symbol, date) panels so single-modality / pairwise / full multimodal
  ablations stay easy.
- 3-year look-back (configurable).
- Raw articles + daily aggregates (count, average tone, source diversity).

Outputs (under --out-dir, default ./news/)
  raw/{SYMBOL}.parquet              individual articles
  daily/{SYMBOL}.parquet            daily aggregates (count, mean_tone, ...)
  fetch_log.csv                     status per ticker

CHANGELOG (fixes applied)
- yf_news(): yfinance now returns publish time as an ISO8601 string under
  content['pubDate'] (e.g. "2026-07-30T12:00:00Z"), not an epoch int/float.
  The old isinstance(pub, (int, float)) check always failed on this, so
  every yfinance-sourced article got date=None and was silently dropped
  during daily aggregation -> "ok" status but 0 days, no daily parquet.
  Fixed with _parse_any_datetime(), which handles epoch numbers, ISO8601
  strings, and ISO strings without a colon-safe timezone.
- gdelt_query(): now returns (articles, error_reason) instead of catching
  every failure into a bare `except Exception: return []`. This lets you
  distinguish genuine zero-coverage tickers from HTTP 429 rate-limiting or
  non-JSON (HTML error page) responses, both of which used to look
  identical to "no articles" in fetch_log.csv.
- fetch_one(): records gdelt_error / yf_error into the log so failures are
  diagnosable after a full run, and a retry subset can be isolated.
- parse_gdelt_date(): replaced the broken format-string-length hack with a
  straightforward multi-format parser (this was previously falling through
  to a fallback branch almost every time due to a logic bug).
- fetch_one() skip-branch (NEW): previously, when raw+daily parquet already
  existed and the ticker was skipped, status["n_articles"] was read from
  the raw parquet but status["n_days"] was left at its default of 0. Since
  main()'s summary logic treats status=="skipped" the same as status=="ok"
  for the "n_days == 0" warning check, every skipped ticker with a
  perfectly good existing daily file printed a false
  "-> ok but 0 daily rows" warning. Fixed by also reading the daily
  parquet's row count in the skip branch.

Usage
-----
python fetch_news.py --registry company_registry.csv
python fetch_news.py --registry company_registry.csv --years 3 --sleep 0.4
python fetch_news.py --registry company_registry.csv --symbols XOM,TSLA,JNJ  # test
python fetch_news.py --registry company_registry.csv --retry-from news/fetch_log.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_news")

# ---------------------------------------------------------------------------
# Shared datetime parsing (handles epoch numbers AND ISO8601 strings)
# ---------------------------------------------------------------------------

def _parse_any_datetime(value: Any) -> datetime | None:
    """Handles epoch int/float (yfinance's old format), ISO8601 strings
    (yfinance's current format, e.g. '2026-07-30T12:00:00Z'), GDELT's
    'YYYYMMDDTHHMMSSZ' seendate strings, and plain 'YYYYMMDD' strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str) and value.strip():
        s = value.strip()
        # Try strict ISO8601 first (handles both yfinance's pubDate and
        # anything with a '-' date separator)
        try:
            iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            pass
        # Try GDELT's compact seendate formats: YYYYMMDDTHHMMSSZ / YYYYMMDDHHMMSS
        compact = s.replace("Z", "").replace("T", "")
        for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
            try:
                return datetime.strptime(compact[: len(fmt.replace("%", "").replace("Y", "1234"))], fmt)
            except ValueError:
                continue
        # Last resort: grab the first 8 digits and treat as YYYYMMDD
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 8:
            try:
                return datetime.strptime(digits[:8], "%Y%m%d")
            except ValueError:
                return None
    return None


def parse_gdelt_date(s: str) -> datetime | None:
    return _parse_any_datetime(s)


# ---------------------------------------------------------------------------
# GDELT DOC 2.0 helper (no API key)
# ---------------------------------------------------------------------------

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def gdelt_query(
    query: str,
    start: datetime,
    end: datetime,
    maxrecords: int = 250,
    mode: str = "ArtList",
    max_retries: int = 3,
    backoff_base: float = 8.0,
) -> tuple[list[dict[str, Any]], str]:
    """
    Query GDELT DOC 2.0 Article List.
    Returns (articles, error_reason). error_reason is "" on success.
    On HTTP 429 (rate limited), retries with exponential backoff
    (backoff_base, backoff_base*2, backoff_base*4 seconds) before giving up
    -- GDELT's actual limit is tighter than a flat per-request sleep can
    reliably stay under, so a request-time retry is needed in addition to
    the between-ticker sleep.
    """
    start_str = start.strftime("%Y%m%d%H%M%S")
    end_str = end.strftime("%Y%m%d%H%M%S")

    params = {
        "query": query,
        "mode": mode,
        "maxrecords": str(maxrecords),
        "format": "json",
        "startdatetime": start_str,
        "enddatetime": end_str,
        "sort": "DateDesc",
    }
    url = GDELT_DOC_URL + "?" + urllib.parse.urlencode(params)

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "esg-research-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                last_error = "gdelt_http_429_rate_limited"
                if attempt < max_retries:
                    wait = backoff_base * (2 ** attempt)
                    log.info("    429 rate limited, backing off %.0fs (attempt %d/%d)",
                              wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    continue
                return [], last_error
            return [], f"gdelt_http_{e.code}"
        except urllib.error.URLError as e:
            return [], f"gdelt_network_error:{e.reason}"
        except Exception as e:
            return [], f"gdelt_unknown_error:{e}"

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            snippet = raw[:120].replace("\n", " ")
            return [], f"gdelt_non_json_response:{snippet}"

        articles = data.get("articles", []) if isinstance(data, dict) else []
        if not articles:
            return [], "gdelt_empty_result"
        return articles, ""

    return [], last_error


def build_gdelt_query(symbol: str, security: str) -> str:
    """
    Construct a reasonably precise query.
    Prefer company name; add ticker only when it is unambiguous.
    """
    name = security
    for suffix in [
        " Inc.", " Inc", " Corp.", " Corp", " Corporation", " Ltd.", " Ltd",
        " plc", " PLC", " Co.", " Company", " Group", " Holdings", " N.V.",
    ]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break

    if " " in name:
        q = f'"{name}"'
    else:
        q = name

    if len(symbol) >= 3 and symbol.isalpha():
        q = f"({q} OR {symbol})"

    return q


# ---------------------------------------------------------------------------
# Finnhub fallback (second tier, tried when GDELT returns nothing)
# ---------------------------------------------------------------------------

FINNHUB_URL = "https://finnhub.io/api/v1/company-news"


def finnhub_news(
    symbol: str,
    start: datetime,
    end: datetime,
    api_key: str,
    max_retries: int = 2,
) -> tuple[list[dict[str, Any]], str]:
    """
    Finnhub's company-news endpoint. Free tier: 60 calls/min, and in practice
    only returns meaningful results for roughly the trailing year even if you
    ask for a wider range -- so we chunk the requested window into <=365-day
    slices and issue one call per slice (older slices will often come back
    empty, which is expected and not an error).
    Returns (articles, error_reason).
    """
    if not api_key:
        return [], "finnhub_no_api_key"

    all_articles: list[dict[str, Any]] = []
    last_error = ""
    window_end = end
    while window_end > start:
        window_start = max(start, window_end - timedelta(days=365))
        params = {
            "symbol": symbol,
            "from": window_start.strftime("%Y-%m-%d"),
            "to": window_end.strftime("%Y-%m-%d"),
            "token": api_key,
        }
        url = FINNHUB_URL + "?" + urllib.parse.urlencode(params)

        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "esg-research-fetcher/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return [], "finnhub_invalid_api_key"
                if e.code == 429 and attempt < max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                last_error = f"finnhub_http_{e.code}"
                raw = None
                break
            except urllib.error.URLError as e:
                last_error = f"finnhub_network_error:{e.reason}"
                raw = None
                break
        else:
            raw = None

        if raw is not None:
            try:
                items = json.loads(raw)
                if isinstance(items, list):
                    all_articles.extend(items)
            except json.JSONDecodeError:
                last_error = "finnhub_non_json_response"

        window_end = window_start
        time.sleep(1.1)  # stay comfortably under 60 calls/min across chunks

    if not all_articles:
        return [], last_error or "finnhub_empty_result"
    return all_articles, ""


# ---------------------------------------------------------------------------
# yfinance fallback (FIXED date parsing)
# ---------------------------------------------------------------------------

def yf_news(symbol: str) -> tuple[list[dict[str, Any]], str]:
    """Returns (articles, error_reason)."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        items = t.news or []
        if not items:
            return [], "yfinance_empty_result"
        out = []
        for it in items:
            content = it.get("content", {}) if isinstance(it.get("content"), dict) else {}
            title = it.get("title") or content.get("title") or ""

            # FIX: yfinance's current schema puts publish time as an
            # ISO8601 string under content['pubDate'], not an epoch number.
            # Check both locations and parse with the format-agnostic helper.
            pub_raw = (
                it.get("providerPublishTime")
                or content.get("pubDate")
                or content.get("displayTime")
            )
            pub_dt = _parse_any_datetime(pub_raw)

            out.append({
                "title": title,
                "url": it.get("link") or content.get("clickThroughUrl", {}).get("url", ""),
                "seendate": pub_dt.strftime("%Y%m%dT%H%M%SZ") if pub_dt else "",
                "domain": it.get("publisher") or content.get("provider", {}).get("displayName", ""),
                "language": "English",
                "source": "yfinance",
            })
        return out, ""
    except Exception as e:
        return [], f"yfinance_error:{e}"


# ---------------------------------------------------------------------------
# Per-ticker fetch + daily aggregation
# ---------------------------------------------------------------------------

def fetch_one(
    symbol: str,
    security: str,
    years: int,
    out_dir: Path,
    skip_existing: bool = True,
    max_per_query: int = 250,
    finnhub_key: str = "",
) -> dict[str, Any]:
    status = {
        "symbol": symbol,
        "status": "ok",
        "n_articles": 0,
        "n_days": 0,
        "gdelt_error": "",
        "finnhub_error": "",
        "yf_error": "",
        "error": "",
    }

    raw_path = out_dir / "raw" / f"{symbol}.parquet"
    daily_path = out_dir / "daily" / f"{symbol}.parquet"

    if skip_existing and raw_path.exists() and daily_path.exists():
        status["status"] = "skipped"
        try:
            status["n_articles"] = len(pd.read_parquet(raw_path))
        except Exception:
            pass
        # FIX: n_days used to be left at its default of 0 here, which made
        # every skipped ticker with a perfectly good existing daily file
        # print a false "-> ok but 0 daily rows" warning in main(). Read the
        # actual row count from the existing daily parquet instead.
        try:
            status["n_days"] = len(pd.read_parquet(daily_path))
        except Exception:
            pass
        return status

    end = datetime.utcnow()
    start = end - timedelta(days=years * 365)

    # ---- GDELT (primary) ----
    query = build_gdelt_query(symbol, security)
    articles, gdelt_error = gdelt_query(query, start, end, maxrecords=max_per_query)
    status["gdelt_error"] = gdelt_error

    rows = []
    for a in articles:
        seendate = a.get("seendate") or a.get("seenDate") or ""
        dt = parse_gdelt_date(seendate)
        rows.append({
            "symbol": symbol,
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "domain": a.get("domain") or "",
            "language": a.get("language") or "",
            "seendate": seendate,
            "date": dt.date().isoformat() if dt else None,
            "tone": a.get("tone"),
            "source": "gdelt",
        })

    # ---- Finnhub (second tier -- tried only when GDELT came back empty) ----
    if not articles:
        fh_articles, fh_error = finnhub_news(symbol, start, end, finnhub_key)
        status["finnhub_error"] = fh_error
        for a in fh_articles:
            dt = _parse_any_datetime(a.get("datetime"))
            rows.append({
                "symbol": symbol,
                "title": a.get("headline") or "",
                "url": a.get("url") or "",
                "domain": a.get("source") or "",
                "language": "English",
                "seendate": dt.strftime("%Y%m%dT%H%M%SZ") if dt else "",
                "date": dt.date().isoformat() if dt else None,
                "tone": None,
                "source": "finnhub",
            })

    # ---- yfinance fallback / enrichment (recent only) ----
    yf_articles, yf_error = yf_news(symbol)
    status["yf_error"] = yf_error
    for a in yf_articles:
        dt = parse_gdelt_date(a.get("seendate", ""))
        rows.append({
            "symbol": symbol,
            "title": a.get("title") or "",
            "url": a.get("url") or "",
            "domain": a.get("domain") or "",
            "language": a.get("language") or "English",
            "seendate": a.get("seendate") or "",
            "date": dt.date().isoformat() if dt else None,
            "tone": None,
            "source": "yfinance",
        })

    if not rows:
        status["status"] = "no_articles"
        status["error"] = gdelt_error or status["finnhub_error"] or yf_error or "empty result from GDELT + Finnhub + yfinance"
        return status

    raw_df = pd.DataFrame(rows)
    raw_df = raw_df.drop_duplicates(subset=["url", "title"], keep="first")
    raw_df = raw_df.sort_values("date", ascending=False)

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_df.to_parquet(raw_path, index=False)
    status["n_articles"] = len(raw_df)

    # ---- Daily aggregates (ready for time-series models) ----
    if "date" in raw_df.columns and raw_df["date"].notna().any():
        daily = (
            raw_df.dropna(subset=["date"])
            .groupby("date", as_index=False)
            .agg(
                n_articles=("title", "count"),
                n_sources=("domain", "nunique"),
                mean_tone=("tone", "mean"),
            )
        )
        daily["symbol"] = symbol
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily.to_parquet(daily_path, index=False)
        status["n_days"] = len(daily)
    else:
        status["n_days"] = 0
        # This case is now diagnosable: raw articles exist but none had a
        # parseable date. Surface it instead of silently producing 0 days.
        if not status["error"]:
            status["error"] = "articles_found_but_no_parseable_dates"

    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-level news fetcher (GDELT + yfinance)")
    parser.add_argument("--registry", type=Path, default=Path("company_registry.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("news"))
    parser.add_argument("--years", type=int, default=3, help="Look-back years (default 3)")
    parser.add_argument("--sleep", type=float, default=2.5,
                         help="Sleep between tickers (default 2.5s). GDELT rate-limited heavily "
                              "even at 1.0s in practice; combined with gdelt_query's own "
                              "429 backoff-retry this should clear most of the rate-limit errors.")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated test subset")
    parser.add_argument("--no-skip", action="store_true")
    parser.add_argument("--maxrecords", type=int, default=250, help="GDELT maxrecords per query")
    parser.add_argument("--retry-from", type=Path, default=None,
                         help="Path to a previous fetch_log.csv — only re-run tickers whose "
                              "error indicates rate-limiting/non-JSON (i.e. likely recoverable), "
                              "not genuine no-coverage tickers.")
    parser.add_argument("--finnhub-key", type=str, default="",
                         help="Finnhub API key (free at finnhub.io). Falls back to the "
                              "FINNHUB_API_KEY env var if not passed. Used as a second-tier "
                              "fallback only for tickers where GDELT returns nothing.")
    args = parser.parse_args()

    finnhub_key = args.finnhub_key or os.environ.get("FINNHUB_API_KEY", "")
    if not finnhub_key:
        log.warning("No Finnhub API key provided (--finnhub-key or FINNHUB_API_KEY env var). "
                    "Finnhub fallback tier will be skipped; only GDELT + yfinance will run.")

    if not args.registry.exists():
        raise SystemExit(f"Registry not found: {args.registry}")

    df = pd.read_csv(args.registry)
    if "symbol" not in df.columns:
        raise SystemExit("Registry must contain 'symbol' column")

    name_col = "security" if "security" in df.columns else None
    records = []
    for _, row in df.iterrows():
        sym = str(row["symbol"]).strip().upper()
        name = str(row[name_col]).strip() if name_col else sym
        records.append((sym, name))

    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        records = [r for r in records if r[0] in wanted]
        log.info("Restricted to %d requested symbols", len(records))

    if args.retry_from:
        prev = pd.read_csv(args.retry_from)
        # Old-format logs (from before this fix) only have the generic
        # "empty result from GDELT + yfinance" message for every failure, so
        # matching on error text alone finds nothing. n_days==0 is the real,
        # format-independent signal: it catches both true no_articles rows
        # AND the "ok but 0 days" bug rows, and works on old or new logs.
        err = prev["error"].astype(str) if "error" in prev.columns else pd.Series([""] * len(prev))
        looks_recoverable = err.str.contains(
            "429|rate_limited|non_json|network_error|no_parseable_dates|finnhub_http_5", na=False
        )
        zero_days = prev.get("n_days", pd.Series([0] * len(prev))).fillna(0).astype(float) == 0
        recoverable = prev[looks_recoverable | zero_days]
        wanted = set(recoverable["symbol"].astype(str).str.upper())
        records = [r for r in records if r[0] in wanted]
        log.info("Retry mode: %d recoverable tickers from %s", len(records), args.retry_from)

    log.info(
        "Fetching news for %d companies | %d-year look-back | out=%s",
        len(records), args.years, args.out_dir,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    log_rows = []

    for i, (sym, name) in enumerate(records, 1):
        log.info("[%d/%d] %s  (%s)", i, len(records), sym, name[:40])
        st = fetch_one(
            symbol=sym,
            security=name,
            years=args.years,
            out_dir=args.out_dir,
            skip_existing=not args.no_skip,
            max_per_query=args.maxrecords,
            finnhub_key=finnhub_key,
        )
        log_rows.append(st)
        if st["status"] not in ("ok", "skipped"):
            log.warning("  -> %s  %s", st["status"], st.get("error", ""))
        elif st["n_days"] == 0:
            log.warning("  -> ok but 0 daily rows: %s", st.get("error", ""))
        time.sleep(args.sleep)

    log_df = pd.DataFrame(log_rows)
    log_path = args.out_dir / "fetch_log.csv"
    # If retrying, merge results back into the original log instead of overwriting it.
    # Guard against log_df being empty (0 records this run) -- an empty
    # DataFrame(log_rows) has no columns at all, so log_df["symbol"] would
    # raise KeyError before we ever get to use it.
    if args.retry_from and args.retry_from.exists():
        prev = pd.read_csv(args.retry_from)
        if len(log_df) > 0 and "symbol" in log_df.columns:
            prev = prev[~prev["symbol"].isin(log_df["symbol"])]
            log_df = pd.concat([prev, log_df], ignore_index=True)
        else:
            log_df = prev  # nothing new was fetched, keep the old log as-is
    log_df.to_csv(log_path, index=False)

    counts = log_df["status"].value_counts().to_dict()
    zero_day_ok = ((log_df["status"] == "ok") & (log_df["n_days"] == 0)).sum()
    log.info("Finished. Status counts: %s", counts)
    log.info("'ok' but 0 daily rows (check 'error' col for reason): %d", zero_day_ok)
    log.info("Log -> %s", log_path)


if __name__ == "__main__":
    main()