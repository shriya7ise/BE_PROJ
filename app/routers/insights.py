"""
Deep-dive endpoints used by the Company detail, Financials and Signals pages.

  GET /api/companies/{symbol}/esg           full ESG dossier
  GET /api/companies/{symbol}/financials    full financial study (+ price / statement history)
  GET /api/companies/{symbol}/signals       signal register for one company
  GET /api/companies/{symbol}/report/{kind}.pdf   kind = esg | financial | signals
  GET /api/financials                       universe table for the Financials page
  GET /api/signals                          universe feed for the Signals page
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app import analysis as A

router = APIRouter()


def _or_404(obj, symbol):
    if obj is None:
        raise HTTPException(404, f"Unknown symbol {symbol}")
    return obj


@router.get("/companies/{symbol}/esg")
def company_esg(symbol: str):
    return A.clean(_or_404(A.esg_dossier(symbol), symbol))


@router.get("/companies/{symbol}/financials")
def company_financials(symbol: str, live: bool = True):
    return _or_404(A.financial_study(symbol, allow_live=live), symbol)


@router.get("/companies/{symbol}/signals")
def company_signals(symbol: str):
    return _or_404(A.signals_for(symbol), symbol)


@router.get("/companies/{symbol}/report/{kind}.pdf")
def company_report(symbol: str, kind: str):
    try:
        from app import reports as R
    except ImportError as e:
        raise HTTPException(501, f"PDF export needs extra packages: pip install reportlab matplotlib ({e})")
    if kind == "esg":
        d = A.clean(_or_404(A.esg_dossier(symbol), symbol)); pdf = R.esg_report(d)
    elif kind == "financial":
        d = _or_404(A.financial_study(symbol, allow_live=True), symbol); pdf = R.financial_report(d)
    elif kind == "signals":
        d = _or_404(A.signals_for(symbol), symbol); pdf = R.signals_report(d)
    else:
        raise HTTPException(404, "kind must be esg, financial or signals")
    name = f"{symbol.upper()}_{kind}_report.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Access-Control-Expose-Headers": "Content-Disposition"})


@router.get("/financials")
def financials(limit: int = Query(500, ge=1, le=1000)):
    return A.financial_list(limit)


@router.get("/signals")
def signals(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), category: str | None = None,
            min_severity: float | None = None, q: str | None = None):
    return A.signals_list(page, page_size, category, min_severity, q)
