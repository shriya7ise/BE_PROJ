import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchFinancials } from "../api";
import { HBar, Tooltip } from "../components/charts";

/* ---------- formatters ---------- */
function money(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
}
const pct = (v, d = 2) => (v == null ? "—" : `${(Number(v) * 100).toFixed(d)}%`);
const num = (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d));

function marginColor(v) {
  if (v == null) return "var(--muted)";
  if (v < 0) return "#ff5c7a";
  if (v < 0.05) return "#f5c542";
  return "#3dd68c";
}
function levColor(v) {
  if (v == null) return "var(--muted)";
  if (v > 200) return "#ff5c7a";
  if (v > 100) return "#f5c542";
  return "var(--text)";
}

const FOCUS = "#2ee6a8";
const DIM = "#5b6b7a";

function median(arr) {
  const a = arr.filter((v) => v != null && !Number.isNaN(Number(v))).map(Number).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
function percentileOf(v, arr) {
  const a = arr.filter((x) => x != null).map(Number);
  if (v == null || !a.length) return null;
  return (a.filter((x) => x < v).length / a.length) * 100;
}

/* metrics shown in the company-focus panel */
const METRICS = [
  { key: "profit_margins", label: "Profit margin", fmt: (v) => pct(v), good: true },
  { key: "revenue_growth", label: "Revenue growth", fmt: (v) => pct(v, 1), good: true },
  { key: "debt_to_equity", label: "Debt / equity", fmt: (v) => num(v, 1), good: false },
  { key: "current_ratio", label: "Current ratio", fmt: (v) => num(v, 2), good: true },
  { key: "trailing_pe", label: "P/E (trailing)", fmt: (v) => num(v, 1), good: null },
  { key: "beta", label: "Beta", fmt: (v) => num(v, 2), good: null },
];

const BETA_BUCKETS = [
  { label: "< 0.8", tag: "Defensive", test: (b) => b < 0.8 },
  { label: "0.8 – 1.2", tag: "Market-like", test: (b) => b >= 0.8 && b < 1.2 },
  { label: "1.2 – 1.6", tag: "Aggressive", test: (b) => b >= 1.2 && b < 1.6 },
  { label: "≥ 1.6", tag: "High vol", test: (b) => b >= 1.6 },
];

export default function Financials() {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [sector, setSector] = useState("");

  const [hover, setHover] = useState(null);
  const [hoverLeft, setHoverLeft] = useState(0);
  const [hoverTop, setHoverTop] = useState(0);

  const goCompany = (symbol) => nav(`/companies/${encodeURIComponent(symbol)}?tab=financial`);

  const hoverProps = (symbol) => ({
    onMouseEnter: (e) => { setHover(symbol); setHoverLeft(e.clientX); setHoverTop(e.clientY); },
    onMouseMove: (e) => { setHoverLeft(e.clientX); setHoverTop(e.clientY); },
    onMouseLeave: () => setHover(null),
  });

  useEffect(() => {
    fetchFinancials(300)
      .then(setData)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  const universeRows = useMemo(() => data?.results || [], [data]);

  const sectors = useMemo(
    () => [...new Set(universeRows.map((r) => r.gics_sector).filter(Boolean))].sort(),
    [universeRows]
  );

  /* rows matching the filter box + sector dropdown */
  const rows = useMemo(() => {
    let list = universeRows;
    if (sector) list = list.filter((r) => r.gics_sector === sector);
    if (q.trim()) {
      const n = q.trim().toLowerCase();
      list = list.filter(
        (r) => (r.symbol || "").toLowerCase().includes(n) || (r.canonical_name || "").toLowerCase().includes(n)
      );
    }
    return list;
  }, [universeRows, q, sector]);

  /* a single company is "in focus" when the search resolves to exactly one, or is an exact ticker */
  const focus = useMemo(() => {
    if (!q.trim()) return null;
    const n = q.trim().toLowerCase();
    const exact = rows.find((r) => (r.symbol || "").toLowerCase() === n);
    if (exact) return exact;
    return rows.length === 1 ? rows[0] : null;
  }, [rows, q]);

  /* the set every chart is drawn from */
  const { scope, scopeLabel } = useMemo(() => {
    if (focus) {
      let peers = universeRows
        .filter((r) => r.symbol !== focus.symbol && focus.gics_sector && r.gics_sector === focus.gics_sector)
        .sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))
        .slice(0, 30);
      if (peers.length < 6) {
        const extra = universeRows
          .filter((r) => r.symbol !== focus.symbol && !peers.includes(r))
          .sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))
          .slice(0, 12 - peers.length);
        peers = [...peers, ...extra];
      }
      return {
        scope: [focus, ...peers],
        scopeLabel: focus.gics_sector ? `${focus.symbol} vs ${focus.gics_sector} peers` : `${focus.symbol} vs largest peers`,
      };
    }
    if (q.trim() || sector) return { scope: rows, scopeLabel: `${rows.length} matching entities` };
    return { scope: universeRows, scopeLabel: "full coverage universe" };
  }, [focus, universeRows, rows, q, sector]);

  /* top-N of the scope, always keeping the focused company visible */
  const pick = (list, n, cmp) => {
    const sorted = [...list].sort(cmp);
    let top = sorted.slice(0, n);
    if (focus && !top.some((r) => r.symbol === focus.symbol)) top = [...top.slice(0, n - 1), focus];
    return top;
  };

  const marginBars = useMemo(
    () => pick(scope, 25, (a, b) => (b.profit_margins ?? -9) - (a.profit_margins ?? -9)),
    [scope, focus] // eslint-disable-line
  );
  const capBars = useMemo(
    () => pick(scope, 15, (a, b) => (b.market_cap || 0) - (a.market_cap || 0)),
    [scope, focus] // eslint-disable-line
  );
  const maxCap = Math.max(...capBars.map((r) => r.market_cap || 0), 1);
  const maxMarginAbs = Math.max(...marginBars.map((r) => Math.abs(r.profit_margins || 0)), 0.01);

  const scatter = useMemo(
    () =>
      scope
        .filter((r) => r.debt_to_equity != null && r.revenue_growth != null)
        .map((r) => ({
          ...r,
          x: Math.max(0, Math.min(r.debt_to_equity, 400)),
          y: Math.max(-0.3, Math.min(0.5, r.revenue_growth)),
        })),
    [scope]
  );
  const scatterMaxCap = Math.max(...scatter.map((r) => r.market_cap || 0), 1);

  const betaBuckets = useMemo(() => {
    const vals = scope.map((r) => r.beta).filter((b) => b != null);
    return BETA_BUCKETS.map((b) => ({
      ...b,
      count: vals.filter(b.test).length,
      hasFocus: focus && focus.beta != null && b.test(focus.beta),
    }));
  }, [scope, focus]);

  /* KPI numbers for the current scope */
  const kpi = useMemo(() => {
    if (!q.trim() && !sector && data) {
      return {
        cap: data.aggregate_market_cap,
        margin: data.mean_profit_margin,
        neg: data.negative_margin_count,
        lev: data.high_leverage_count,
        n: data.n,
      };
    }
    const m = scope.map((r) => r.profit_margins).filter((v) => v != null);
    return {
      cap: scope.reduce((s, r) => s + (r.market_cap || 0), 0),
      margin: m.length ? m.reduce((s, v) => s + v, 0) / m.length : null,
      neg: scope.filter((r) => r.profit_margins != null && r.profit_margins < 0).length,
      lev: scope.filter((r) => (r.debt_to_equity || 0) > 200).length,
      n: scope.length,
    };
  }, [data, scope, q, sector]);

  /* company-vs-sector-vs-universe table for the focus panel */
  const profile = useMemo(() => {
    if (!focus) return null;
    const sectorRows = universeRows.filter((r) => r.gics_sector === focus.gics_sector);
    const capRank = [...universeRows].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0)).findIndex((r) => r.symbol === focus.symbol) + 1;
    const secRank = [...sectorRows].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0)).findIndex((r) => r.symbol === focus.symbol) + 1;
    return {
      capRank,
      secRank,
      secSize: sectorRows.length,
      metrics: METRICS.map((m) => ({
        ...m,
        value: focus[m.key],
        sectorMed: median(sectorRows.map((r) => r[m.key])),
        univMed: median(universeRows.map((r) => r[m.key])),
        pctile: percentileOf(focus[m.key], universeRows.map((r) => r[m.key])),
      })),
    };
  }, [focus, universeRows]);

  const tableRows = focus ? scope : rows;
  const hoverRow = hover != null ? universeRows.find((r) => r.symbol === hover) : null;
  const isFocus = (r) => focus && r.symbol === focus.symbol;

  if (error) return <div className="panel" style={{ color: "var(--red)" }}>{error}</div>;
  if (!data) return <div className="panel">Loading financial matrix…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Header + filters */}
      <div className="panel">
        <div style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--muted)" }}>FINANCIAL LAYER / YFINANCE</div>
        <h2 style={{ fontSize: 18, margin: "6px 0" }}>Entity financial metrics</h2>
        <p style={{ color: "var(--muted)", fontSize: 12, maxWidth: 720 }}>
          Cross-referenced with ESG risk to weight material exposure. Search a ticker or company name and every chart
          below re-centres on it, compared against its sector peers.
        </p>
        <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter ticker or name…" style={filterStyle} />
          <select value={sector} onChange={(e) => setSector(e.target.value)} style={filterStyle}>
            <option value="">All sectors</option>
            {sectors.map((s) => (<option key={s} value={s}>{s}</option>))}
          </select>
          {(q || sector) && (
            <button className="btn" onClick={() => { setQ(""); setSector(""); }}>Clear</button>
          )}
          <span style={{ color: "var(--muted)", fontSize: 12 }}>
            showing {rows.length} / {data.n} entities · charts: {scopeLabel}
          </span>
        </div>
        {q.trim() && rows.length === 0 && (
          <div style={{ color: "#f5c542", fontSize: 12, marginTop: 10 }}>
            No entity matches “{q}”. Charts are showing the full universe.
          </div>
        )}
      </div>

      {/* KPI row */}
      {focus ? (
        <div className="kpi-row">
          <div className="kpi">
            <label>{focus.symbol} · Market cap</label>
            <div className="val cyan">{money(focus.market_cap)}</div>
            <div className="sub">#{profile.capRank} OF {data.n} · #{profile.secRank} OF {profile.secSize} IN SECTOR</div>
          </div>
          <div className="kpi">
            <label>Profit margin</label>
            <div className="val" style={{ color: marginColor(focus.profit_margins) }}>{pct(focus.profit_margins)}</div>
            <div className="sub">SECTOR MEDIAN {pct(profile.metrics[0].sectorMed)}</div>
          </div>
          <div className="kpi">
            <label>Debt / equity</label>
            <div className="val" style={{ color: levColor(focus.debt_to_equity) }}>{num(focus.debt_to_equity, 1)}</div>
            <div className="sub">SECTOR MEDIAN {num(profile.metrics[2].sectorMed, 1)}</div>
          </div>
          <div className="kpi">
            <label>Revenue growth</label>
            <div className="val" style={{ color: marginColor(focus.revenue_growth) }}>{pct(focus.revenue_growth, 1)}</div>
            <div className="sub">SECTOR MEDIAN {pct(profile.metrics[1].sectorMed, 1)}</div>
          </div>
        </div>
      ) : (
        <div className="kpi-row">
          <div className="kpi">
            <label>Aggregate market cap</label>
            <div className="val cyan">{money(kpi.cap)}</div>
            <div className="sub">{q || sector ? "FILTERED SET" : "COVERAGE UNIVERSE"}</div>
          </div>
          <div className="kpi">
            <label>Mean profit margin</label>
            <div className="val">{kpi.margin != null ? pct(kpi.margin) : "—"}</div>
            <div className="sub">n={kpi.n}</div>
          </div>
          <div className="kpi">
            <label>Negative margin</label>
            <div className="val red">{kpi.neg}</div>
            <div className="sub">ENTITIES</div>
          </div>
          <div className="kpi">
            <label>High leverage (D/E &gt; 200)</label>
            <div className="val red">{kpi.lev}</div>
            <div className="sub">ENTITIES</div>
          </div>
        </div>
      )}

      {/* Company focus panel */}
      {focus && profile && (
        <div className="panel">
          <div className="panel-h" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3>
              {focus.canonical_name || focus.symbol} <span>{focus.gics_sector || ""}</span>
            </h3>
            <button className="btn primary" onClick={() => goCompany(focus.symbol)}>Open full study →</button>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>{focus.symbol}</th>
                  <th>Sector median</th>
                  <th>All median</th>
                  <th style={{ width: 260 }}>Position vs all {data.n} companies</th>
                </tr>
              </thead>
              <tbody>
                {profile.metrics.map((m) => {
                  const p = m.pctile;
                  const goodPos = m.good === null ? null : m.good ? p : p == null ? null : 100 - p;
                  const c = goodPos == null ? FOCUS : goodPos >= 60 ? "#3dd68c" : goodPos >= 35 ? "#f5c542" : "#ff5c7a";
                  return (
                    <tr key={m.key}>
                      <td>{m.label}</td>
                      <td style={{ fontWeight: 600 }}>{m.fmt(m.value)}</td>
                      <td style={{ color: "var(--muted)" }}>{m.fmt(m.sectorMed)}</td>
                      <td style={{ color: "var(--muted)" }}>{m.fmt(m.univMed)}</td>
                      <td>
                        {p == null ? (
                          <span style={{ color: "var(--muted)" }}>n/a</span>
                        ) : (
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{ position: "relative", flex: 1, height: 6, background: "#1c2230", borderRadius: 3 }}>
                              <span style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "#3a4458" }} />
                              <span style={{ position: "absolute", left: 0, width: `${p}%`, height: "100%", background: c, opacity: 0.4, borderRadius: 3 }} />
                              <span style={{ position: "absolute", left: `${p}%`, top: -3, width: 12, height: 12, marginLeft: -6, borderRadius: "50%", background: c }} />
                            </div>
                            <span style={{ width: 34, fontSize: 11, color: c, textAlign: "right" }}>{p.toFixed(0)}</span>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 8 }}>
            Dot = percentile among all companies (50 = median). For debt/equity, a lower value is shown as healthier.
          </div>
        </div>
      )}

      <div className="grid-2" style={{ alignItems: "stretch" }}>
        {/* Profitability bars */}
        <div className="panel">
          <div className="panel-h">
            <h3>Profitability · Net margin {focus ? `· ${focus.symbol} vs peers` : ""}</h3>
          </div>
          <HBar
            rows={marginBars.map((r) => ({
              label: r.symbol,
              value: r.profit_margins || 0,
              color: isFocus(r) ? FOCUS : r.profit_margins < 0 ? "#ff5c7a" : DIM,
              title: `${r.symbol}: ${pct(r.profit_margins)}`,
              display: pct(r.profit_margins),
            }))}
            max={maxMarginAbs}
            fmt={(v) => pct(v)}
            labelWidth={52}
          />
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 8 }}>
            Sorted by margin. {focus ? "Teal bar = selected company. " : ""}Red = negative.
          </div>
        </div>

        {/* Risk quadrant scatter */}
        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div className="panel-h">
            <h3>Risk quadrant · Leverage × revenue growth</h3>
          </div>
          <div
            style={{
              position: "relative",
              flex: 1,
              minHeight: 420,
              background: "#0e1218",
              borderRadius: 8,
              border: "1px solid var(--border)",
              overflow: "hidden",
            }}
          >
            {/* guide lines: growth = 0 and D/E = 200 */}
            <div style={{ position: "absolute", left: 0, right: 0, top: "62.5%", borderTop: "1px dashed #2a3344" }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "50%", borderLeft: "1px dashed #2a3344" }} />
            <span style={quad({ top: 8, right: 10 })}>HIGH LEVERAGE · GROWING</span>
            <span style={quad({ top: 8, left: 10 })}>LOW LEVERAGE · GROWING</span>
            <span style={quad({ bottom: 22, left: 10 })}>LOW LEVERAGE · SHRINKING</span>
            <span style={quad({ bottom: 22, right: 10 })}>HIGH LEVERAGE · SHRINKING</span>
            <span style={{ position: "absolute", bottom: 4, left: 8, fontSize: 10, color: "var(--muted)" }}>D/E 0</span>
            <span style={{ position: "absolute", bottom: 4, left: "50%", transform: "translateX(-50%)", fontSize: 10, color: "var(--muted)" }}>200</span>
            <span style={{ position: "absolute", bottom: 4, right: 8, fontSize: 10, color: "var(--muted)" }}>400+ →</span>

            {scatter.map((r) => {
              const f = isFocus(r);
              const left = (r.x / 400) * 96 + 2;
              const top = (100 - ((r.y + 0.3) / 0.8) * 100) * 0.88 + 6;
              const size = f ? 18 : 7 + Math.min(16, ((r.market_cap || 0) / scatterMaxCap) * 16);
              return (
                <div key={r.symbol}>
                  <div
                    onClick={() => goCompany(r.symbol)}
                    {...hoverProps(r.symbol)}
                    style={{
                      position: "absolute",
                      left: `${left}%`,
                      top: `${top}%`,
                      width: size,
                      height: size,
                      marginLeft: -size / 2,
                      marginTop: -size / 2,
                      borderRadius: "50%",
                      background: f ? FOCUS : focus ? "rgba(139,147,167,0.35)" : "rgba(46,230,168,0.35)",
                      border: f ? "3px solid #fff" : "1px solid var(--cyan)",
                      boxShadow: f ? "0 0 14px #2ee6a8" : "none",
                      cursor: "pointer",
                      zIndex: f ? 3 : 1,
                    }}
                  />
                  {(f || (focus && scatter.length <= 14)) && (
                    <span
                      style={{
                        position: "absolute",
                        left: `${left}%`,
                        top: `${top}%`,
                        marginLeft: size / 2 + 4,
                        marginTop: -7,
                        fontSize: f ? 12 : 10,
                        fontWeight: f ? 700 : 400,
                        color: f ? "#fff" : "var(--muted)",
                        pointerEvents: "none",
                        zIndex: 4,
                      }}
                    >
                      {r.symbol}
                    </span>
                  )}
                </div>
              );
            })}
            {scatter.length === 0 && (
              <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 12 }}>
                No leverage / growth data for this set.
              </div>
            )}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 8 }}>
            Bubble size ≈ market cap. Click a bubble to open that company. The sector dropdown filters the charts and table.
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: "stretch" }}>
        {/* Market cap concentration */}
        <div className="panel">
          <div className="panel-h">
            <h3>Capitalization · Market cap {focus ? "vs peers" : "concentration"}</h3>
          </div>
          {capBars.map((r) => {
            const f = isFocus(r);
            return (
              <div
                key={r.symbol}
                onClick={() => goCompany(r.symbol)}
                {...hoverProps(r.symbol)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                  cursor: "pointer",
                  background: f ? "rgba(46,230,168,0.08)" : "transparent",
                  padding: "2px 6px",
                  borderRadius: 4,
                }}
              >
                <span style={{ width: 44, fontFamily: "var(--mono)", fontSize: 12, fontWeight: f ? 700 : 400 }}>{r.symbol}</span>
                <div style={{ flex: 1, height: 10, background: "#1c2230", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ width: `${((r.market_cap || 0) / maxCap) * 100}%`, height: "100%", background: f ? FOCUS : "var(--cyan)", opacity: f || !focus ? 1 : 0.5, borderRadius: 4 }} />
                </div>
                <span style={{ width: 72, textAlign: "right", fontSize: 12 }}>{money(r.market_cap)}</span>
                <span style={{ width: 52, textAlign: "right", fontSize: 11, color: marginColor(r.profit_margins) }}>{pct(r.profit_margins, 1)}</span>
              </div>
            );
          })}
        </div>

        {/* Beta distribution */}
        <div className="panel">
          <div className="panel-h">
            <h3>Volatility · Beta distribution {focus ? `· ${focus.symbol} β ${num(focus.beta, 2)}` : ""}</h3>
          </div>
          {(() => {
            const maxB = Math.max(...betaBuckets.map((x) => x.count), 1);
            return betaBuckets.map((b) => (
              <div key={b.label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ width: 72, fontSize: 11, color: b.hasFocus ? "#fff" : "var(--muted)", fontWeight: b.hasFocus ? 700 : 400 }}>{b.label}</span>
                <div style={{ flex: 1, height: 12, background: "#1c2230", borderRadius: 4 }}>
                  <div style={{ width: `${(b.count / maxB) * 100}%`, height: "100%", background: b.hasFocus ? FOCUS : "#6b7c8f", borderRadius: 4 }} />
                </div>
                <span style={{ width: 28, fontSize: 12 }}>{b.count}</span>
                <span style={{ width: 84, fontSize: 10, color: "var(--muted)" }}>
                  {b.tag}{b.hasFocus ? " ◀ " + focus.symbol : ""}
                </span>
              </div>
            ));
          })()}
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 8 }}>
            Counts of companies by beta in the current chart set ({scope.length}).
          </div>
        </div>
      </div>

      {/* Matrix table */}
      <div className="panel">
        <div className="panel-h">
          <h3>
            {focus ? `Peer matrix · ${focus.symbol} and ${tableRows.length - 1} peers` : "Financial matrix"}{" "}
            <span>Per-entity metrics · N={tableRows.length}</span>
          </h3>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Ticker</th><th>Cap share</th><th>Market cap</th><th>Profit margin</th>
                <th>D/E</th><th>Current</th><th>Rev growth</th><th>P/E</th><th>Beta</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((r) => (
                <tr
                  key={r.symbol}
                  className="clickable"
                  onClick={() => goCompany(r.symbol)}
                  {...hoverProps(r.symbol)}
                  style={{ cursor: "pointer", background: isFocus(r) ? "rgba(46,230,168,0.08)" : undefined }}
                >
                  <td style={{ fontFamily: "var(--mono)", fontWeight: 600 }}>{r.symbol}</td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ width: 48, height: 4, background: "#1c2230", borderRadius: 2 }}>
                        <div style={{ width: `${Math.min(100, (r.cap_share || 0) * 100 * 3)}%`, height: "100%", background: "var(--cyan)" }} />
                      </div>
                      <span style={{ fontSize: 11 }}>{r.cap_share != null ? `${(r.cap_share * 100).toFixed(2)}%` : "—"}</span>
                    </div>
                  </td>
                  <td>{money(r.market_cap)}</td>
                  <td style={{ color: marginColor(r.profit_margins) }}>{pct(r.profit_margins)}</td>
                  <td style={{ color: levColor(r.debt_to_equity) }}>{num(r.debt_to_equity, 1)}</td>
                  <td>{num(r.current_ratio, 2)}</td>
                  <td style={{ color: marginColor(r.revenue_growth) }}>{pct(r.revenue_growth, 1)}</td>
                  <td>{num(r.trailing_pe, 1)}</td>
                  <td>{num(r.beta, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Tooltip
        visible={hoverRow != null}
        x={hoverLeft}
        y={hoverTop}
        content={
          hoverRow
            ? {
                ticker: hoverRow.symbol,
                name: hoverRow.canonical_name || "",
                metrics: {
                  "Market cap": money(hoverRow.market_cap),
                  "Profit margin": pct(hoverRow.profit_margins, 1),
                  "D/E": num(hoverRow.debt_to_equity, 1),
                  "Revenue growth": pct(hoverRow.revenue_growth, 1),
                },
              }
            : null
        }
      />
    </div>
  );
}

const quad = (pos) => ({ position: "absolute", fontSize: 9, letterSpacing: "0.06em", color: "#3a4458", pointerEvents: "none", ...pos });

const filterStyle = {
  background: "var(--panel-2)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 13,
};