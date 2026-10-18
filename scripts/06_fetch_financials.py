#!/usr/bin/env python3
"""
fetch_financials.py
-------------------
Research-level financial data layer for the multimodal ESG risk prediction stack.

Matches the feature depth used in recent papers:
  - Multi-year daily prices → returns, volatility, drawdowns (LSTM / sequence models)
  - Quarterly & annual statements (8–12 quarters + 5 years annual)
  - Core risk ratios: leverage, profitability, liquidity, coverage, size
  - Clean panel keys for later fusion with news / ESG reports / geo

Primary source: yfinance (free, reliable for S&P 500 universe)

Outputs (under --out-dir, default ./financials/)
  prices/{SYMBOL}.parquet          daily OHLCV + adj close (10y default)
  statements/{SYMBOL}_income.parquet
  statements/{SYMBOL}_balance.parquet
  statements/{SYMBOL}_cashflow.parquet
  fundamentals.csv                 one-row-per-company snapshot + key ratios
  fetch_log.csv                    success / failure / skip status

Usage
-----
python fetch_financials.py --registry company_registry.csv
python fetch_financials.py --registry company_registry.csv --years 5 --sleep 0.4
python fetch_financials.py --registry company_registry.csv --symbols AAPL,XOM,TSLA  # test subset
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yfinance as yf
except ImportError as e:
    raise SystemExit(
        "yfinance is required. Install with:\n  pip install yfinance pandas pyarrow"
    ) from e

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_financials")

# ---------------------------------------------------------------------------
# Research-grade ratio helpers
# ---------------------------------------------------------------------------

def safe_div(a, b):
    try:
        if a is None or b is None or b == 0:
            return None
        return float(a) / float(b)
    except Exception:
        return None


def compute_snapshot_ratios(info: dict[str, Any], financials: dict[str, Any]) -> dict[str, Any]:
    """Key ratios used in ESG-distress / risk-score papers."""
    # Prefer info fields (already computed by Yahoo) then fall back to statements
    total_debt = info.get("totalDebt")
    total_equity = info.get("totalStockholderEquity") or info.get("bookValue")
    total_assets = info.get("totalAssets")
    ebitda = info.get("ebitda")
    ebit = info.get("ebit") or info.get("operatingIncome")
    revenue = info.get("totalRevenue")
    net_income = info.get("netIncomeToCommon")
    current_assets = None
    current_liab = None
    interest_exp = None

    # Try to enrich from latest annual/quarterly if available
    # (kept simple – full panel ratios can be derived later from the statement parquets)

    ratios = {
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "debt_to_equity": info.get("debtToEquity"),
        "debt_to_assets": safe_div(total_debt, total_assets),
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
        "return_on_assets": info.get("returnOnAssets"),
        "return_on_equity": info.get("returnOnEquity"),
        "profit_margins": info.get("profitMargins"),
        "operating_margins": info.get("operatingMargins"),
        "gross_margins": info.get("grossMargins"),
        "ebitda_margins": info.get("ebitdaMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "free_cashflow": info.get("freeCashflow"),
        "operating_cashflow": info.get("operatingCashflow"),
        "total_revenue": revenue,
        "total_debt": total_debt,
        "total_assets": total_assets,
        "total_cash": info.get("totalCash"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "float_shares": info.get("floatShares"),
        "beta": info.get("beta"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "average_volume": info.get("averageVolume"),
        "employees": info.get("fullTimeEmployees"),
        "long_business_summary": (info.get("longBusinessSummary") or "")[:500],
    }
    return ratios


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def fetch_one(
    symbol: str,
    years: int,
    out_dir: Path,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Fetch prices + statements + snapshot for one ticker. Returns status dict."""
    status = {
        "symbol": symbol,
        "status": "ok",
        "prices_rows": 0,
        "income_cols": 0,
        "error": "",
    }

    price_path = out_dir / "prices" / f"{symbol}.parquet"
    income_path = out_dir / "statements" / f"{symbol}_income.parquet"
    balance_path = out_dir / "statements" / f"{symbol}_balance.parquet"
    cashflow_path = out_dir / "statements" / f"{symbol}_cashflow.parquet"

    if skip_existing and price_path.exists() and income_path.exists():
        status["status"] = "skipped"
        try:
            status["prices_rows"] = len(pd.read_parquet(price_path))
        except Exception:
            pass
        return status

    try:
        ticker = yf.Ticker(symbol)

        # ---- 1. Daily prices (research length) ----
        period = f"{years}y"
        hist = ticker.history(period=period, auto_adjust=False)
        if hist is None or hist.empty:
            status["status"] = "no_price_data"
            status["error"] = "empty history"
            return status

        hist = hist.reset_index()
        # Normalize column names
        hist.columns = [c.lower().replace(" ", "_") for c in hist.columns]
        if "date" not in hist.columns and "index" in hist.columns:
            hist = hist.rename(columns={"index": "date"})
        hist["symbol"] = symbol
        price_path.parent.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(price_path, index=False)
        status["prices_rows"] = len(hist)

        # ---- 2. Financial statements (quarterly preferred for sequences) ----
        statements_dir = out_dir / "statements"
        statements_dir.mkdir(parents=True, exist_ok=True)

        def save_statement(df: pd.DataFrame | None, path: Path) -> int:
            if df is None or df.empty:
                return 0
            # yfinance returns items as rows, periods as columns → transpose for panel use
            out = df.T.reset_index()
            out = out.rename(columns={"index": "period"})
            out["symbol"] = symbol
            out.to_parquet(path, index=False)
            return out.shape[1] - 2  # rough feature count

        # Prefer quarterly; fall back to annual if needed
        income = ticker.quarterly_income_stmt
        if income is None or income.empty:
            income = ticker.income_stmt
        balance = ticker.quarterly_balance_sheet
        if balance is None or balance.empty:
            balance = ticker.balance_sheet
        cashflow = ticker.quarterly_cashflow
        if cashflow is None or cashflow.empty:
            cashflow = ticker.cashflow

        status["income_cols"] = save_statement(income, income_path)
        save_statement(balance, balance_path)
        save_statement(cashflow, cashflow_path)

        # ---- 3. Snapshot fundamentals + ratios ----
        info = ticker.info or {}
        ratios = compute_snapshot_ratios(info, {})
        status["_snapshot"] = {
            "symbol": symbol,
            "security_name": info.get("longName") or info.get("shortName") or "",
            "sector_yf": info.get("sector") or "",
            "industry_yf": info.get("industry") or "",
            "currency": info.get("currency") or "USD",
            **{k: v for k, v in ratios.items() if k != "long_business_summary"},
            "long_business_summary": ratios.get("long_business_summary", ""),
        }

    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)[:300]
        log.warning("%s  →  %s", symbol, status["error"])

    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-level financial data fetcher")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("company_registry.csv"),
        help="Path to company_registry.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("financials"),
        help="Root output directory",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="Years of daily price history (default 10 – research length)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.35,
        help="Sleep seconds between tickers (rate-limit courtesy)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional comma-separated subset for testing, e.g. AAPL,XOM,TSLA",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Re-download even if parquet already exists",
    )
    args = parser.parse_args()

    if not args.registry.exists():
        raise SystemExit(f"Registry not found: {args.registry}")

    df = pd.read_csv(args.registry)
    if "symbol" not in df.columns:
        raise SystemExit("Registry must contain a 'symbol' column")

    symbols = df["symbol"].astype(str).str.strip().str.upper().tolist()
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        symbols = [s for s in symbols if s in wanted]
        log.info("Restricted to %d requested symbols", len(symbols))

    log.info("Fetching financials for %d companies  |  %dy prices  |  out=%s",
             len(symbols), args.years, args.out_dir)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "prices").mkdir(exist_ok=True)
    (args.out_dir / "statements").mkdir(exist_ok=True)

    snapshots = []
    log_rows = []

    for i, sym in enumerate(symbols, 1):
        log.info("[%d/%d] %s", i, len(symbols), sym)
        st = fetch_one(
            sym,
            years=args.years,
            out_dir=args.out_dir,
            skip_existing=not args.no_skip,
        )
        log_rows.append({k: v for k, v in st.items() if not k.startswith("_")})
        if "_snapshot" in st:
            snapshots.append(st["_snapshot"])
        time.sleep(args.sleep)

    # Write fundamentals snapshot table
    if snapshots:
        fund_df = pd.DataFrame(snapshots)
        fund_path = args.out_dir / "fundamentals.csv"
        fund_df.to_csv(fund_path, index=False)
        log.info("Wrote fundamentals snapshot → %s  (%d rows)", fund_path, len(fund_df))

    # Write run log
    log_df = pd.DataFrame(log_rows)
    log_path = args.out_dir / "fetch_log.csv"
    log_df.to_csv(log_path, index=False)

    # Summary
    counts = log_df["status"].value_counts().to_dict()
    log.info("Finished. Status counts: %s", counts)
    log.info("Log → %s", log_path)


if __name__ == "__main__":
    main()
