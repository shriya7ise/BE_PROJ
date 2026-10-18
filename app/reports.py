"""
Professional PDF reports (ESG dossier, financial study, signal register).

Requires:  pip install reportlab matplotlib
Every number, chart and sentence is generated from app.analysis output.
"""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from app import analysis as A  # noqa: E402

NAVY = colors.HexColor("#0b1620")
TEAL = colors.HexColor("#0d8f6f")
INK = colors.HexColor("#1b2430")
MUTED = colors.HexColor("#6b7686")
LINE = colors.HexColor("#d9dee5")
SOFT = colors.HexColor("#f3f6f9")
RED, AMBER, GREEN = "#d93a55", "#e0a400", "#1f9d68"
C_TEAL, C_NAVY, C_GREY = "#0d8f6f", "#26384a", "#9aa5b3"
W = A4[0] - 32 * mm  # usable width

TIER_COL = {"Critical": RED, "Watchlist": AMBER, "Neutral": "#6b7280", "Stable": GREEN}

ST = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, spaceBefore=10, spaceAfter=5),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, textColor=TEAL, spaceBefore=8, spaceAfter=3),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=13, textColor=INK, spaceAfter=4),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white),
    "quote": ParagraphStyle("quote", fontName="Helvetica-Oblique", fontSize=8.3, leading=11.5, textColor=INK,
                            leftIndent=8, borderPadding=(2, 2, 2, 6), spaceAfter=5),
    "kpil": ParagraphStyle("kpil", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=9),
    "call": ParagraphStyle("call", fontName="Helvetica", fontSize=9, leading=13, textColor=INK),
}


def _t(s) -> str:
    """Sanitise text for the built-in Helvetica font and Paragraph markup."""
    if s is None:
        return "n/a"
    s = str(s)
    for a, b in (("↔", "and"), ("≥", ">="), ("≤", "<="), ("→", "->"), ("–", "-"), ("’", "'"), ("“", '"'), ("”", '"'), ("‘", "'")):
        s = s.replace(a, b)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style="p"):
    return Paragraph(_t(text), ST[style])


def H(text):
    """Section heading that never strands at the bottom of a page."""
    return [CondPageBreak(60 * mm), Paragraph(_t(text), ST["h1"])]


# ---------------------------------------------------------------- page furniture
class _Doc(BaseDocTemplate):
    def __init__(self, buf, title, subtitle, accent):
        super().__init__(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=18 * mm,
                         bottomMargin=16 * mm, title=title, author="Vigilance ESG")
        self.title_, self.sub_, self.accent = title, subtitle, accent
        fr = Frame(self.leftMargin, self.bottomMargin, W, A4[1] - 34 * mm, id="f", leftPadding=0, rightPadding=0,
                   topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="p", frames=[fr], onPage=self._furniture)])

    def _furniture(self, c, doc):
        c.saveState()
        if doc.page > 1:
            c.setFont("Helvetica", 7.5)
            c.setFillColor(MUTED)
            c.drawString(16 * mm, A4[1] - 11 * mm, _t(self.sub_))
            c.drawRightString(A4[0] - 16 * mm, A4[1] - 11 * mm, "VIGILANCE ESG")
            c.setStrokeColor(LINE)
            c.line(16 * mm, A4[1] - 13 * mm, A4[0] - 16 * mm, A4[1] - 13 * mm)
        c.setStrokeColor(LINE)
        c.line(16 * mm, 12 * mm, A4[0] - 16 * mm, 12 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(16 * mm, 8 * mm, "For informational purposes only. Not investment, legal or compliance advice.")
        c.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {doc.page}")
        c.restoreState()


def _cover(title, name, symbol, sub, accent, kpis):
    """Dark header band + KPI strip as flowables."""
    head = Table(
        [[Paragraph(f'<font color="#7fe3c1" size="8">VIGILANCE ESG  |  {_t(title).upper()}</font>', ST["p"])],
         [Paragraph(f'<font color="white" size="21"><b>{_t(name)}</b></font>', ParagraphStyle("nm", parent=ST["p"], leading=27))],
         [Paragraph(f'<font color="#b9c4d0" size="9">{_t(symbol)}  |  {_t(sub)}</font>', ST["p"])],
         [Paragraph(f'<font color="#8795a6" size="7.5">Generated {datetime.now():%d %b %Y, %H:%M}</font>', ST["p"])]],
        colWidths=[W])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 14),
                              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                              ("TOPPADDING", (0, 0), (-1, 0), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
                              ("LINEBELOW", (0, -1), (-1, -1), 3, accent)]))
    return [head, Spacer(1, 8), kpi_row(kpis)]


def kpi_row(items):
    cells = []
    for label, value, col in items:
        cells.append([Paragraph(_t(label).upper(), ST["kpil"]),
                      Paragraph(f'<font size="15" color="{col or "#1b2430"}"><b>{_t(value)}</b></font>', ST["p"])])
    n = len(cells)
    t = Table([[c for c in cells]], colWidths=[W / n] * n)
    # each cell holds two paragraphs -> nest in sub-tables
    t = Table([[Table([[c[0]], [c[1]]], colWidths=[W / n - 4]) for c in cells]], colWidths=[W / n] * n)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                           ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def table(header, rows, widths, align_right=(), zebra=True, font=8, width=None):
    data = [[Paragraph(_t(h), ST["th"]) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, (str, int, float)) else Paragraph(_t(c), ST["cell"]) for c in r])
    tw = sum(widths)
    t = Table(data, colWidths=[w / tw * (width or W) for w in widths], repeatRows=1)
    sty = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
           ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE)]
    if zebra:
        for i in range(2, len(data), 2):
            sty.append(("BACKGROUND", (0, i), (-1, i), SOFT))
    t.setStyle(TableStyle(sty))
    return t


def callout(text, color=TEAL):
    t = Table([[Paragraph(_t(text), ST["call"])]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LINEBEFORE", (0, 0), (0, -1), 3, color),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def fig_img(fig, width=W, ratio=None):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(buf).getSize()
    buf.seek(0)
    return Image(buf, width=width, height=width * ih / iw)


def side_by_side(a, b, gap=6):
    t = Table([[a, b]], colWidths=[W / 2 - gap / 2, W / 2 - gap / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def sec(title, flow):
    return KeepTogether([P(title, "h1")] + flow[:1]) if flow else P(title, "h1")


# ---------------------------------------------------------------- chart helpers
def _style(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c9d1da")
    ax.tick_params(colors="#4b5766", labelsize=7, length=2)
    if grid:
        ax.grid(axis=grid, color="#e9edf2", lw=0.6)
        ax.set_axisbelow(True)


def _fig(w=3.6, h=2.4):
    f, ax = plt.subplots(figsize=(w, h))
    _style(ax)
    return f, ax


def _title(ax, t):
    ax.set_title(t, fontsize=8.5, fontweight="bold", color="#1b2430", loc="left", pad=7)


def ch_gauge(score, tier):
    from matplotlib.patches import Wedge
    f, ax = plt.subplots(figsize=(3.4, 2.1))
    ax.set_xlim(-1.15, 1.15); ax.set_ylim(-0.35, 1.15); ax.set_aspect("equal"); ax.axis("off")
    for lo, hi, c in [(0, 20, GREEN), (20, 40, "#8dc9a8"), (40, 70, AMBER), (70, 100, RED)]:
        ax.add_patch(Wedge((0, 0), 1.0, 180 - hi * 1.8, 180 - lo * 1.8, width=0.28, color=c))
    th = np.pi * (1 - score / 100)
    ax.plot([0, 0.72 * np.cos(th)], [0, 0.72 * np.sin(th)], color="#1b2430", lw=2.4, solid_capstyle="round")
    ax.add_patch(plt.Circle((0, 0), 0.06, color="#1b2430"))
    ax.text(0, -0.22, f"{score:.0f} / 100", ha="center", fontsize=14, fontweight="bold", color=TIER_COL.get(tier, C_NAVY))
    for v in (0, 20, 40, 70, 100):
        a = np.pi * (1 - v / 100)
        ax.text(1.1 * np.cos(a), 1.1 * np.sin(a), str(v), ha="center", va="center", fontsize=6, color="#6b7686")
    return fig_img(f, W / 2 - 4)


def ch_pillars(pillars):
    f, ax = _fig(3.6, 2.4)
    labs = [p["label"] for p in pillars]
    uni = [p["universe_percentile"] or 0 for p in pillars]
    sec_ = [p["sector_percentile"] if p["sector_percentile"] is not None else np.nan for p in pillars]
    y = np.arange(len(labs))
    ax.barh(y + 0.19, uni, 0.34, color=C_TEAL, label="vs all companies")
    ax.barh(y - 0.19, np.nan_to_num(sec_), 0.34, color=C_NAVY, label="vs sector peers")
    ax.axvline(50, color="#999", lw=0.8, ls="--")
    ax.set_yticks(y); ax.set_yticklabels(labs); ax.invert_yaxis(); ax.set_xlim(0, 100)
    ax.set_xlabel("percentile (50 = median)", fontsize=7)
    ax.legend(fontsize=6.5, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.28), ncol=2); _style(ax, "x")
    _title(ax, "10-K disclosure emphasis")
    return fig_img(f, W / 2 - 4)


def ch_osha_year(by_year):
    f, ax = _fig(7.2, 2.5)
    yrs = [d["year"] for d in by_year]
    ax.bar(yrs, [d["penalty"] / 1e6 for d in by_year], color=C_TEAL, width=0.65)
    ax.set_ylabel("penalties ($M)", fontsize=7)
    ax2 = ax.twinx(); ax2.plot(yrs, [d["violations"] for d in by_year], color=RED, marker="o", ms=3, lw=1.6)
    ax2.plot(yrs, [d["serious"] for d in by_year], color=AMBER, marker="o", ms=3, lw=1.3, ls="--")
    ax2.set_ylabel("citations", fontsize=7); ax2.tick_params(labelsize=7, colors="#4b5766")
    for s in ("top",): ax2.spines[s].set_visible(False)
    ax.set_xticks(yrs)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=C_TEAL), plt.Line2D([], [], color=RED, marker="o"),
                       plt.Line2D([], [], color=AMBER, marker="o", ls="--")],
              labels=["Penalties", "Citations", "Serious / willful / repeat"], fontsize=6.5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.12), ncol=3)
    _title(ax, "OSHA enforcement by year of issuance")
    return fig_img(f, W)


def ch_donut(by_type):
    f, ax = plt.subplots(figsize=(3.4, 2.4))
    pal = {"S": AMBER, "W": RED, "R": "#e8742b", "O": C_GREY, "U": "#cfd6de"}
    vals = [d["count"] for d in by_type]
    ax.pie(vals, colors=[pal.get(d["code"], C_GREY) for d in by_type], startangle=90, counterclock=False,
           wedgeprops=dict(width=0.38, edgecolor="white"))
    ax.legend([f"{d['label']} ({d['count']})" for d in by_type], fontsize=6.5, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.02), ncol=2)
    _title(ax, "Citations by severity class")
    return fig_img(f, W / 2 - 4)


def hbar(title, labels, values, color=C_TEAL, fmt="{:.1f}", xlabel="", w=3.6, h=2.4, maxlab=34):
    f, ax = _fig(w, h)
    labels = [(l if len(l) <= maxlab else l[:maxlab - 1] + "…") for l in labels]
    y = np.arange(len(labels))
    ax.barh(y, values, color=color, height=0.62)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=6.6); ax.invert_yaxis()
    mx = max([abs(v) for v in values] + [1e-9])
    for i, v in enumerate(values):
        ax.text(v + mx * 0.015 * (1 if v >= 0 else -1), i, fmt.format(v), va="center", fontsize=6.5, color="#26384a",
                ha="left" if v >= 0 else "right")
    ax.set_xlim(min(0, min(values) * 1.25), mx * 1.22)
    ax.set_xlabel(xlabel, fontsize=7); _style(ax, "x"); _title(ax, title)
    return fig_img(f, W / 2 - 4)


def ch_months(monthly, title):
    f, ax = _fig(7.2, 2.0)
    ax.bar([m["month"] for m in monthly], [m["count"] for m in monthly], color=C_NAVY, width=0.6)
    ax.tick_params(axis="x", rotation=0)
    _title(ax, title)
    return fig_img(f, W)


def ch_radar(scorecard, name):
    dims = [s["dimension"] for s in scorecard if s["score"] is not None]
    vals = [s["score"] for s in scorecard if s["score"] is not None]
    sec_ = [s["sector_score"] or 50 for s in scorecard if s["score"] is not None]
    if len(dims) < 3:
        return None
    ang = np.linspace(0, 2 * np.pi, len(dims), endpoint=False).tolist()
    f, ax = plt.subplots(figsize=(3.4, 3.1), subplot_kw={"polar": True})
    for series, col, lab in ((sec_, C_GREY, "Sector median"), (vals, C_TEAL, name)):
        d = series + series[:1]
        ax.plot(ang + ang[:1], d, color=col, lw=1.8, label=lab)
        ax.fill(ang + ang[:1], d, color=col, alpha=0.18)
    ax.set_xticks(ang); ax.set_xticklabels(dims, fontsize=7)
    ax.set_ylim(0, 100); ax.set_yticks([25, 50, 75]); ax.set_yticklabels(["25", "50", "75"], fontsize=5.5, color="#888")
    ax.grid(color="#dfe5ec"); ax.spines["polar"].set_color("#dfe5ec")
    ax.legend(fontsize=6.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2)
    return fig_img(f, W / 2 - 4)


def ch_health(items, title):
    items = [i for i in items if i["health_percentile"] is not None][:12]
    f, ax = _fig(3.6, 0.28 * len(items) + 0.8)
    y = np.arange(len(items))
    cols = [GREEN if i["health_percentile"] >= 60 else AMBER if i["health_percentile"] >= 35 else RED for i in items]
    ax.barh(y, [i["health_percentile"] for i in items], color=cols, height=0.62)
    ax.axvline(50, color="#999", lw=0.8, ls="--")
    ax.set_yticks(y); ax.set_yticklabels([i["label"] for i in items], fontsize=6.6); ax.invert_yaxis(); ax.set_xlim(0, 100)
    ax.set_xlabel("health percentile vs all companies (higher = healthier)", fontsize=6.5); _style(ax, "x"); _title(ax, title)
    return fig_img(f, W / 2 - 4)


def ch_peers(name, symbol, rows, key, label, pct=True):
    rr = [r for r in rows if r.get(key) is not None][:8]
    if len(rr) < 3:
        return None
    f, ax = _fig(3.6, 2.4)
    syms = [r["symbol"] for r in rr]
    vals = [r[key] * (100 if pct else 1) for r in rr]
    ax.bar(syms, vals, color=[C_TEAL if s == symbol else C_GREY for s in syms], width=0.62)
    ax.tick_params(axis="x", labelsize=6.5)
    _title(ax, f"{label}: {symbol} vs closest-size sector peers")
    return fig_img(f, W / 2 - 4)


def ch_price(prices, symbol):
    import pandas as pd
    s = prices["series"]
    d = pd.to_datetime([x["d"] for x in s]); c = [x["c"] for x in s]
    dd = prices["drawdown"]; dd_d = pd.to_datetime([x["d"] for x in dd])
    f, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 3.6), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    for a in (a1, a2):
        _style(a)
    a1.plot(d, c, color=C_TEAL, lw=1.4); a1.fill_between(d, c, min(c), color=C_TEAL, alpha=0.1)
    a1.set_ylabel("price ($)", fontsize=7); _title(a1, f"{symbol} price history (weekly)")
    a2.fill_between(dd_d, [x["v"] * 100 for x in dd], 0, color=RED, alpha=0.35)
    a2.set_ylabel("drawdown %", fontsize=7)
    return fig_img(f, W)


def ch_calret(cal, title="Calendar-year returns"):
    f, ax = _fig(3.6, 2.4)
    ax.bar([str(c["year"]) for c in cal], [c["ret"] * 100 for c in cal], color=[GREEN if c["ret"] >= 0 else RED for c in cal])
    ax.axhline(0, color="#777", lw=0.6); ax.tick_params(axis="x", labelsize=6, rotation=45)
    ax.set_ylabel("%", fontsize=7); _title(ax, title)
    return fig_img(f, W / 2 - 4)


def ch_vol(roll):
    import pandas as pd
    f, ax = _fig(3.6, 2.4)
    ax.plot(pd.to_datetime([x["d"] for x in roll]), [x["v"] * 100 for x in roll], color=C_NAVY, lw=1.3)
    ax.set_ylabel("%", fontsize=7); _title(ax, "Rolling 3-month volatility (annualised)")
    return fig_img(f, W / 2 - 4)


def ch_statements(rows, key_a, key_b, la, lb, title):
    rr = [r for r in rows if r.get(key_a) is not None]
    if len(rr) < 2:
        return None
    f, ax = _fig(3.6, 2.4)
    x = np.arange(len(rr)); w = 0.38
    ax.bar(x - w / 2, [r[key_a] / 1e9 for r in rr], w, color=C_TEAL, label=la)
    ax.bar(x + w / 2, [(r.get(key_b) or 0) / 1e9 for r in rr], w, color=C_NAVY, label=lb)
    ax.set_xticks(x); ax.set_xticklabels([str(r["year"]) for r in rr], fontsize=6.5)
    ax.set_ylabel("$ billions", fontsize=7); ax.legend(fontsize=6.5, frameon=False); _title(ax, title)
    return fig_img(f, W / 2 - 4)


def ch_margins(rows):
    rr = [r for r in rows if r.get("operating_margin") is not None or r.get("net_margin") is not None]
    if len(rr) < 2:
        return None
    f, ax = _fig(3.6, 2.4)
    ax.plot([r["year"] for r in rr], [(r.get("gross_margin") or np.nan) * 100 for r in rr], color=C_GREY, marker="o", ms=3, label="Gross")
    ax.plot([r["year"] for r in rr], [(r.get("operating_margin") or np.nan) * 100 for r in rr], color=C_TEAL, marker="o", ms=3, label="Operating")
    ax.plot([r["year"] for r in rr], [(r.get("net_margin") or np.nan) * 100 for r in rr], color=C_NAVY, marker="o", ms=3, label="Net")
    ax.set_xticks([r["year"] for r in rr]); ax.set_ylabel("% of revenue", fontsize=7)
    ax.legend(fontsize=6.5, frameon=False); _title(ax, "Margin trend")
    return fig_img(f, W / 2 - 4)


def ch_capstructure(s):
    cash, debt = s.get("total_cash"), s.get("total_debt")
    if cash is None or debt is None:
        return None
    f, ax = _fig(3.6, 2.4)
    vals = [cash / 1e9, debt / 1e9, (s.get("free_cashflow") or 0) / 1e9]
    ax.bar(["Cash", "Total debt", "Free cash flow"], vals, color=[GREEN, RED, C_TEAL], width=0.55)
    for i, v in enumerate(vals):
        ax.text(i, v, f"${v:.1f}B", ha="center", va="bottom", fontsize=7)
    ax.set_ylabel("$ billions", fontsize=7); _title(ax, "Cash, debt and free cash flow")
    return fig_img(f, W / 2 - 4)


def ch_signal_cat(by_cat):
    if not by_cat:
        return None
    return hbar("Signals by category", [c["category"] for c in by_cat], [c["count"] for c in by_cat], fmt="{:.0f}")


def ch_signal_year(by_year):
    if not by_year:
        return None
    f, ax = _fig(3.6, 2.4)
    ax.bar([str(y["year"]) for y in by_year], [y["count"] for y in by_year],
           color=[RED if y["max_severity"] >= 9 else AMBER if y["max_severity"] >= 7 else C_GREY for y in by_year])
    ax.tick_params(axis="x", labelsize=6.5, rotation=45); _title(ax, "Signals by year (colour = peak severity)")
    return fig_img(f, W / 2 - 4)


# ---------------------------------------------------------------- formatting
def usd(v):
    return A.money(v)


def pc(v, d=1):
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def fx(v, kind):
    if v is None:
        return "n/a"
    return f"{v:.1%}" if kind == "pct" else f"{v:.0f}%" if kind == "pp" else f"{v:.2f}x"


def _build(title, subtitle, accent, story):
    buf = io.BytesIO()
    doc = _Doc(buf, title, subtitle, accent)
    doc.build(story)
    return buf.getvalue()


def _disclaimer(extra):
    return [Spacer(1, 10), P("Notes & methodology", "h2")] + [P(f"- {x}", "small") for x in extra]


# ================================================================= ESG REPORT
def esg_report(d: dict) -> bytes:
    tier_col = TIER_COL.get(d["risk_tier"], C_NAVY)
    o, n, g = d["osha"], d["news"], d["geo"]
    kpis = [("Composite risk score", f"{d['composite_score']:.1f}", tier_col),
            ("Risk tier", d["risk_tier"], tier_col),
            ("Rank", f"#{d['rank']} of {d['universe']}", None),
            ("Model P(risk)", f"{d['model_probability']:.0%}" if d["model_probability"] is not None else "n/a", None),
            ("Evidence streams", f"{d['corroboration_count']} / 4", None)]
    story = _cover("ESG risk study", d["canonical_name"], d["symbol"],
                   f"{d['gics_sector']}" + (f"  |  {d['industry']}" if d.get("industry") else ""), TEAL, kpis)

    story += [*H("1. Executive summary")]
    for s in d["narrative"][:1]:
        story.append(callout(s["text"], tier_col))
    story.append(Spacer(1, 6))
    story.append(side_by_side(ch_gauge(d["composite_score"], d["risk_tier"]), ch_pillars(d["pillars"])))
    story += [P("Evidence streams", "h2"),
              table(["Stream", "Status", "Detail"],
                    [[f["label"], P("FLAGGED", "cellb") if f["triggered"] else "Clear", f["detail"]] for f in d["flags"]],
                    [3, 1.2, 5])]
    story += [P("Recommended action", "h2"), callout(d["recommendation"], tier_col)]
    if d.get("business_summary"):
        story += [P("Business profile", "h2"), P(d["business_summary"])]

    # ---- pillars
    story += [PageBreak(), *H("2. Disclosure analysis - Environmental, Social, Governance, Safety"),
              P("Measured as keyword intensity in the company's latest annual report (10-K). It indicates how much management "
                "discusses each topic compared with other companies; it is a measure of attention and exposure, not of performance.", "small"),
              Spacer(1, 4)]
    story.append(table(["Pillar", "Terms / 1k words", "Percentile (all)", "Percentile (sector)", "Sector median", "Emphasis"],
                       [[p["label"], f"{p['value']:.3f}" if p["value"] is not None else "n/a",
                         f"{p['universe_percentile']:.0f}" if p["universe_percentile"] is not None else "n/a",
                         f"{p['sector_percentile']:.0f}" if p["sector_percentile"] is not None else "n/a",
                         f"{p['sector_median']:.3f}" if p["sector_median"] is not None else "n/a", p["level"]]
                        for p in d["pillars"]], [2.4, 1.6, 1.5, 1.6, 1.5, 1.4]))
    story.append(Spacer(1, 4))
    story.append(P(d["narrative"][2]["text"] if len(d["narrative"]) > 2 else ""))
    for p in d["pillars"]:
        if p["passages"]:
            story.append(P(f"{p['label']} - what the 10-K says", "h2"))
            story.append(P(p["description"], "small"))
            for ps in p["passages"]:
                story.append(P(f'"{ps}"', "quote"))
    f = d["filing"]
    if f["available"]:
        story.append(P(f"Source: {f.get('form') or '10-K'} filed {f.get('filing_date') or 'n/a'} (period ending {f.get('report_date') or 'n/a'}), "
                       f"accession {f.get('accession') or 'n/a'}, ~{int(f['word_count'] or 0):,} words analysed.", "small"))

    # ---- OSHA
    story += [PageBreak(), *H("3. Regulatory & enforcement record (OSHA)")]
    if o.get("has_records"):
        story.append(kpi_row([("Inspections", f"{o['n_inspections']:,}", None), ("Citations", f"{o['n_violations']:,}", None),
                              ("Total penalties", usd(o["total_penalty"]), RED), ("Serious / W / R", f"{o['serious_share']:.0%}", AMBER),
                              ("Rank (penalties)", f"#{o['rank']}", None)]))
        story += [Spacer(1, 5), P(d["narrative"][1]["text"])]
        story.append(ch_osha_year(o["by_year"]))
        story.append(side_by_side(ch_donut(o["by_type"]),
                                  hbar("Costliest standards ($M)", [s["code"] + " " + s["title"] for s in o["top_standards"]],
                                       [s["penalty"] / 1e6 for s in o["top_standards"]], color=C_NAVY, fmt="${:.2f}M", maxlab=30)))
        story += [P("Violation classes", "h2"),
                  table(["Class", "Meaning", "Citations", "Penalties"],
                        [[t["label"], t["description"], f"{t['count']:,}", usd(t["penalty"])] for t in o["by_type"]], [1.5, 4.5, 1, 1.2])]
        story += [P("Most-cited standards", "h2"),
                  table(["Standard", "Title", "Citations", "Penalties"],
                        [[s["code"], s["title"], f"{s['count']:,}", usd(s["penalty"])] for s in o["top_standards"]], [1.2, 4.5, 1, 1.2])]
        story += [P("Largest individual citations", "h2"),
                  table(["Date", "Standard", "Class", "Penalty", "Workers exposed"],
                        [[c["date"], f"{c['standard']} - {c['title']}", c["type"], usd(c["penalty"]),
                          f"{int(c['exposed'])}" if c["exposed"] is not None else "n/a"] for c in o["largest_citations"]], [1.2, 4.5, 1.1, 1.1, 1.1])]
        story += [P("Most recent citations", "h2"),
                  table(["Date", "Standard", "Class", "Penalty"],
                        [[c["date"], f"{c['standard']} - {c['title']}", c["type"], usd(c["penalty"])] for c in o["recent_citations"]], [1.2, 5, 1.2, 1.1])]
    else:
        story.append(P(d["narrative"][1]["text"]))

    # ---- news + geo
    story += [PageBreak(), *H("4. Media attention")]
    if n.get("available"):
        story += [kpi_row([("Articles", f"{n['total_articles']:,}", None), ("Last 30 days", f"{n['last_30d']}", None),
                           ("Avg / month", f"{n['avg_per_month']:.0f}", None), ("Window", f"{n['first_date'][5:]} to {n['last_date'][5:]}", None)]),
                  Spacer(1, 4), ch_months(n["monthly"], "Articles per month")]
        story.append(P("Latest headlines", "h2"))
        story.append(table(["Date", "Source", "Headline"], [[x["date"], x["domain"] or "", x["title"]] for x in n["latest"]], [1.1, 1.4, 6]))
        if not n["tone_available"]:
            story.append(P("Sentiment tone scores are not available in the current dataset; only volume and headlines are shown.", "small"))
    else:
        story.append(P("No news articles were collected for this company."))

    story += [*H("5. Geospatial footprint")]
    if g.get("available"):
        story += [P(f"Geocoded location: {g.get('address') or 'n/a'} ({g['lat']:.4f}, {g['lon']:.4f}). {g['caveat']}", "small")]
        story.append(side_by_side(
            hbar("Percentile vs all companies", [m["label"] for m in g["metrics"]], [m["percentile"] for m in g["metrics"]],
                 fmt="{:.0f}", color=C_TEAL),
            table(["Metric", "Value", "Median"], [[m["label"], f"{m['value']:.2f}{m['unit']}", f"{m['median']:.2f}{m['unit']}"] for m in g["metrics"]],
                  [3, 1.2, 1.2], width=W / 2 - 4)))
    else:
        story.append(P(g.get("note") or "No satellite data available."))

    # ---- model
    story += [*H("6. Model view")]
    if d["top_drivers"]:
        story.append(side_by_side(
            hbar("Top global model drivers (importance %)", [x["feature"] for x in d["top_drivers"]],
                 [x["importance"] * 100 for x in d["top_drivers"]], color=C_NAVY, fmt="{:.1f}%", maxlab=26),
            P(f"The four-way XGBoost classifier (financial + ESG + news + geographic features) estimates a "
              f"{d['model_probability']:.1%} probability of material risk for this company." if d["model_probability"] is not None else
              "Model probability is unavailable.") ))
        if d["model_split"] == "train":
            story.append(P("Caution: this company was part of the training set, so its probability is in-sample and optimistic. "
                           "Driver importances are global and identical for every company.", "small"))
    story += _disclaimer(d["methodology"])
    return _build("ESG risk study", f"{d['canonical_name']} ({d['symbol']}) - ESG risk study", TEAL, story)


# ================================================================= FINANCIAL REPORT
def financial_report(d: dict) -> bytes:
    s, h = d["snapshot"], d["history"]
    ov = d["overall_score"]
    oc = GREEN if (ov or 0) >= 60 else AMBER if (ov or 0) >= 40 else RED
    kpis = [("Market cap", usd(s["market_cap"]), None), ("Revenue", usd(s["total_revenue"]), None),
            ("Free cash flow", usd(s["free_cashflow"]), None), ("Net debt", usd(s["net_debt"]), None),
            ("Health score", f"{ov:.0f}/100" if ov is not None else "n/a", oc)]
    story = _cover("Financial study", d["name"], d["symbol"], f"{d['sector']}" + (f"  |  {d['industry']}" if d.get("industry") else ""), TEAL, kpis)
    story += [*H("1. Executive summary"), callout(d["narrative"][0]["text"], oc), Spacer(1, 6)]
    rad = ch_radar(d["scorecard"], d["symbol"])
    hl = d["highlights"]
    right = [P("Strengths", "h2")] + ([P(f"+ {x}", "cell") for x in hl["strengths"]] or [P("None above the 80th percentile.", "cell")]) + \
            [P("Concerns", "h2")] + ([P(f"- {x}", "cell") for x in hl["concerns"]] or [P("None below the 20th percentile.", "cell")])
    story.append(side_by_side(rad or P(""), right))
    story += [P("Score by dimension", "h2"),
              table(["Dimension", f"{d['symbol']}", "Sector median", "Reading"],
                    [[x["dimension"], f"{x['score']:.0f}" if x["score"] is not None else "n/a",
                      f"{x['sector_score']:.0f}" if x["sector_score"] is not None else "n/a",
                      "n/a" if x["score"] is None else ("Strong" if x["score"] >= 65 else "Average" if x["score"] >= 40 else "Weak")]
                     for x in d["scorecard"]], [3, 1.2, 1.4, 1.2])]
    story.append(P("Scores are percentile ranks versus all tracked companies (50 = median; higher = healthier, with leverage and volatility inverted).", "small"))

    # snapshot
    story += [PageBreak(), *H("2. Company snapshot")]
    snap = [("Market capitalisation", usd(s["market_cap"])), ("Enterprise value", usd(s["enterprise_value"])),
            ("Annual revenue", usd(s["total_revenue"])), ("Total cash", usd(s["total_cash"])), ("Total debt", usd(s["total_debt"])),
            ("Net debt", usd(s["net_debt"])), ("Total assets", usd(s["total_assets"])), ("Operating cash flow", usd(s["operating_cashflow"])),
            ("Free cash flow", usd(s["free_cashflow"])), ("Employees", f"{int(s['employees']):,}" if s["employees"] else "n/a"),
            ("Revenue / employee", usd(s["revenue_per_employee"])), ("Shares outstanding", f"{s['shares_outstanding']/1e6:,.0f}M" if s["shares_outstanding"] else "n/a"),
            ("52-week range", f"${s['fifty_two_week_low']:.2f} - ${s['fifty_two_week_high']:.2f}" if s["fifty_two_week_low"] else "n/a"),
            ("Size rank (all / sector)", f"#{s['market_cap_rank']} of {s['universe']}  /  #{s['sector_cap_rank']} of {s['sector_size']}")]
    half = (len(snap) + 1) // 2
    story.append(side_by_side(table(["Item", "Value"], snap[:half], [2, 1.5], width=W / 2 - 4), table(["Item", "Value"], snap[half:], [2, 1.5], width=W / 2 - 4)))
    if d.get("business_summary"):
        story += [P("Business description", "h2"), P(d["business_summary"])]
    for sec_ in d["narrative"][1:4]:
        story += [P(sec_["title"], "h2"), P(sec_["text"])]
    story.append(side_by_side(ch_capstructure(s) or P(""),
                              ch_peers(d["name"], d["symbol"], d["peers"], "operating_margins", "Operating margin") or P("")))

    # ratio groups
    story += [PageBreak(), *H("3. Ratio analysis versus peers"),
              P("Each metric is shown against the median of its GICS sector and of the whole tracked universe, with the company's percentile "
                "ranking. 'Health' converts the percentile so that higher is always better.", "small")]
    for gr in d["groups"]:
        rows = [[i["label"], fx(i["value"], i["kind"]), fx(i["sector_median"], i["kind"]), fx(i["universe_median"], i["kind"]),
                 f"{i['universe_percentile']:.0f}" if i["universe_percentile"] is not None else "n/a",
                 f"{i['health_percentile']:.0f}" if i["health_percentile"] is not None else "n/a", i["description"]] for i in gr["items"]]
        story.append(KeepTogether([P(gr["label"], "h2"),
                                   table(["Metric", "Value", "Sector median", "Universe median", "Pctl", "Health", "Meaning"], rows,
                                         [2, 1, 1.1, 1.2, .7, .8, 4.2])]))
    prof = next((g for g in d["groups"] if g["key"] == "profitability"), None)
    levg = next((g for g in d["groups"] if g["key"] == "leverage"), None)
    allitems = [i for g in d["groups"] for i in g["items"]]
    story += [Spacer(1, 6), side_by_side(ch_health([i for i in allitems if i["key"] in
                                                    {x["key"] for g in d["groups"] if g["key"] in ("profitability", "growth", "cashflow") for x in g["items"]}],
                                                   "Operating health"),
                                         ch_health([i for i in allitems if i["key"] in
                                                    {x["key"] for g in d["groups"] if g["key"] in ("leverage", "market", "valuation") for x in g["items"]}],
                                                   "Balance sheet, market & valuation"))]

    # peers
    story += [PageBreak(), *H("4. Peer comparison"), P("Companies in the same sector with the closest market capitalisation.", "small"),
              table(["Symbol", "Company", "Mkt cap", "Net margin", "Op. margin", "Rev. growth", "D/E", "P/E", "Beta"],
                    [[p["symbol"], p["security_name"], usd(p["market_cap"]), pc(p["profit_margins"]), pc(p["operating_margins"]),
                      pc(p["revenue_growth"]), f"{p['debt_to_equity']:.0f}%" if p["debt_to_equity"] is not None else "n/a",
                      f"{p['trailing_pe']:.1f}" if p["trailing_pe"] is not None else "n/a", f"{p['beta']:.2f}" if p["beta"] is not None else "n/a"]
                     for p in d["peers"]], [.8, 2.6, 1.1, 1, 1, 1.1, .8, .7, .7])]
    pr = ch_peers(d["name"], d["symbol"], d["peers"], "profit_margins", "Net margin")
    pg = ch_peers(d["name"], d["symbol"], d["peers"], "revenue_growth", "Revenue growth")
    if pr or pg:
        story += [Spacer(1, 6), side_by_side(pr or P(""), pg or P(""))]

    # history
    story += [*H("5. Financial history")]
    p_ = h["prices"]
    if p_["available"]:
        story += [kpi_row([("Last price", f"${p_['last_price']:.2f}", None), ("CAGR", pc(p_["cagr"]), None),
                           ("Max drawdown", pc(p_["max_drawdown"]), RED), ("Up days", pc(p_["pct_up_days"], 0), None),
                           ("52w position", pc(p_["range_position"], 0) if p_["range_position"] is not None else "n/a", None)]),
                  Spacer(1, 4), ch_price(p_, d["symbol"]),
                  side_by_side(ch_calret(p_["calendar_returns"]), ch_vol(p_["rolling_vol"]) if p_["rolling_vol"] else P(""))]
        story.append(P(d["narrative"][-1]["text"] if d["narrative"][-1]["title"] == "Price history" else "", "p"))
    else:
        story.append(P("Price history is not available locally for this company. Run scripts/06_fetch_financials.py, or install yfinance "
                       "so the dashboard can fetch and cache it automatically."))
    st = h["statements"]
    if st["available"]:
        rows = st["annual"]
        story += [P("Annual statements", "h2"),
                  table(["FY", "Revenue", "Growth", "Gross margin", "Op. margin", "Net income", "Net margin", "Op. cash flow", "Free cash flow", "Total debt", "Cash"],
                        [[str(r["year"]), usd(r.get("revenue")), pc(r.get("revenue_growth")), pc(r.get("gross_margin")), pc(r.get("operating_margin")),
                          usd(r.get("net_income")), pc(r.get("net_margin")), usd(r.get("operating_cf")), usd(r.get("free_cf")), usd(r.get("total_debt")), usd(r.get("cash"))]
                         for r in reversed(rows)], [.7, 1, .8, .9, .9, 1, .9, 1, 1, 1, 1])]
        story.append(side_by_side(ch_statements(rows, "revenue", "net_income", "Revenue", "Net income", "Revenue vs net income") or P(""),
                                  ch_margins(rows) or P("")))
        if st.get("revenue_cagr") is not None:
            story.append(P(f"Revenue compound annual growth over the available statements: {st['revenue_cagr']:.1%}.", "p"))
    else:
        story.append(P("Annual statements are not available locally for this company.", "small"))

    # esg bridge
    b = d.get("esg_bridge")
    if b:
        story += [*H("6. ESG and financial materiality"),
                  kpi_row([("OSHA penalties", usd(b["penalties"]), None), ("Citations", f"{b['violations']:,}", None),
                           ("% of revenue", f"{b['pct_of_revenue']:.4%}" if b["pct_of_revenue"] is not None else "n/a", None),
                           ("% of free cash flow", f"{b['pct_of_free_cashflow']:.2%}" if b["pct_of_free_cashflow"] is not None else "n/a", None),
                           ("ESG risk tier", b["risk_tier"], TIER_COL.get(b["risk_tier"]))]),
                  Spacer(1, 4)]
        nb = next((x for x in d["narrative"] if x["title"].startswith("ESG")), None)
        if nb:
            story.append(P(nb["text"]))
    story += _disclaimer([
        "Source: yfinance fundamentals snapshot (financials/fundamentals.csv) and engineered dataset (output/financials_dataset.csv).",
        "Debt / equity follows the yfinance convention (217 means 217%).",
        "Net debt / EBITDA uses EBITDA margin x revenue. Percentiles compare with all tracked companies, not the full market.",
        "Price and statement history appear only where local files exist or could be fetched."])
    return _build("Financial study", f"{d['name']} ({d['symbol']}) - Financial study", TEAL, story)


# ================================================================= SIGNALS REPORT
def signals_report(d: dict) -> bytes:
    tc = TIER_COL.get(d["risk_tier"], C_NAVY)
    sev = {x["label"]: x["count"] for x in d["by_severity"]}
    kpis = [("Total signals", f"{d['total']}", None), ("Critical", f"{sev.get('Critical', 0)}", RED), ("High", f"{sev.get('High', 0)}", AMBER),
            ("Percentile vs peers", f"{d['universe_percentile']:.0f}" if d["universe_percentile"] is not None else "n/a", None),
            ("Risk tier", d["risk_tier"], tc)]
    story = _cover("Signal register", d["canonical_name"], d["symbol"], d["gics_sector"], TEAL, kpis)
    story += [*H("1. Summary"),
              callout(f"{d['canonical_name']} has {d['total']} active signals (universe median {d['universe_median']:.0f}), placing it in the "
                      f"{A.ordinal(d['universe_percentile'] or 0)} percentile. {d['corroboration_count']} of 4 independent evidence streams are flagged "
                      f"and the status is '{d['status']}'.", tc),
              Spacer(1, 6), side_by_side(ch_signal_cat(d["by_category"]) or P(""), ch_signal_year(d["by_year"]) or P(""))]
    story += [*H("2. Signal log (highest severity first)"),
              table(["Date", "Sev.", "Category", "Source", "Signal"],
                    [[s["date"] or "ongoing", f"{s['severity']:.1f} {s['severity_label']}", s["category"], ", ".join(s["tiers"]), s["headline"]]
                     for s in d["signals"][:150]], [1.1, 1.3, 1.2, 1, 6])]
    if d["total"] > 150:
        story.append(P(f"Showing the 150 highest-severity of {d['total']} signals.", "small"))
    story += _disclaimer([
        "Signals are generated by transparent rules over OSHA citations, 10-K language, market statistics, satellite data and news volume.",
        "Severity (1-10): willful citation 10, repeat 8, serious / large penalty 6-7; statistical signals scale with the percentile of the metric.",
        "A signal is a prompt for analyst review, not a finding of wrongdoing."])
    return _build("Signal register", f"{d['canonical_name']} ({d['symbol']}) - Signal register", TEAL, story)
