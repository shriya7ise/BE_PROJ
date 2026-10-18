import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ComboChart, HBar, LineChart, PercentileStrip, Radar, COL } from "./charts";
import { Callout, Kpis, Narrative, Section, metric, money, ordinal, pct, tierColor, int } from "./ui";

const RANGES = [["1Y", 52], ["3Y", 156], ["5Y", 260], ["All", 99999]];

function Ratios({ g }) {
  return (
    <div className="card">
      <div className="card-t">{g.label}</div>
      <div className="tscroll">
        <table className="dtable">
          <thead>
            <tr><th>Metric</th><th className="r">Company</th><th className="r">Sector median</th><th className="r">All median</th><th style={{ width: 150 }}>Health vs all companies</th></tr>
          </thead>
          <tbody>
            {g.items.map((i) => (
              <tr key={i.key} title={i.description}>
                <td>{i.label}<div className="muted sm">{i.description}</div></td>
                <td className="r"><b>{metric(i.value, i.kind)}</b></td>
                <td className="r muted">{metric(i.sector_median, i.kind)}</td>
                <td className="r muted">{metric(i.universe_median, i.kind)}</td>
                <td><PercentileStrip pct={i.health_percentile} good /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PriceHistory({ p, symbol }) {
  const [range, setRange] = useState("All");
  const n = RANGES.find((r) => r[0] === range)[1];
  const series = useMemo(() => p.series.slice(-n).map((x) => ({ x: x.d, y: x.c })), [p, n]);
  const dd = useMemo(() => p.drawdown.slice(-n).map((x) => ({ x: x.d, y: x.v })), [p, n]);
  return (
    <>
      <Kpis items={[
        { label: "Last price", value: `$${p.last_price.toFixed(2)}`, sub: p.end },
        { label: "CAGR", value: pct(p.cagr), color: p.cagr >= 0 ? COL.green : COL.red, sub: `${p.start.slice(0, 4)}-${p.end.slice(0, 4)}` },
        { label: "Max drawdown", value: pct(p.max_drawdown), color: COL.red, sub: p.max_drawdown_date },
        { label: "Up days", value: pct(p.pct_up_days, 0), sub: `best ${pct(p.best_day)} · worst ${pct(p.worst_day)}` },
        { label: "52-week position", value: p.range_position != null ? pct(p.range_position, 0) : "n/a", sub: `$${p.low_52w.toFixed(0)} - $${p.high_52w.toFixed(0)}` },
      ]} />
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-t">
          {symbol} price (weekly close)
          <span className="seg">{RANGES.map(([l]) => <button key={l} className={l === range ? "on" : ""} onClick={() => setRange(l)}>{l}</button>)}</span>
        </div>
        <LineChart data={series} yFmt={(v) => `$${v.toFixed(0)}`} />
        <div className="card-t" style={{ marginTop: 10 }}>Drawdown from peak</div>
        <LineChart data={dd} color={COL.red} height={130} baseline={0} yFmt={(v) => `${(v * 100).toFixed(0)}%`} />
      </div>
      <div className="grid2" style={{ marginTop: 12 }}>
        <div className="card">
          <div className="card-t">Calendar-year returns</div>
          <ComboChart signed labels={p.calendar_returns.map((c) => String(c.year))} bars={p.calendar_returns.map((c) => c.ret)} barLabel="Return"
            barColor={COL.green} barFmt={(v) => `${(v * 100).toFixed(1)}%`} />
        </div>
        <div className="card">
          <div className="card-t">Rolling 3-month volatility (annualised)</div>
          <LineChart data={p.rolling_vol.map((x) => ({ x: x.d, y: x.v }))} color={COL.blue} height={230} yFmt={(v) => `${(v * 100).toFixed(0)}%`} />
        </div>
      </div>
    </>
  );
}

function Statements({ st }) {
  const rows = st.annual;
  const L = (f) => rows.map((r) => (r[f] == null ? 0 : r[f]));
  return (
    <>
      <div className="grid2">
        <div className="card">
          <div className="card-t">Revenue and net income</div>
          <ComboChart labels={rows.map((r) => `FY${r.year}`)} bars={L("revenue")} barLabel="Revenue" barFmt={(v) => money(v, 1)}
            lines={[{ label: "Net income", values: L("net_income"), color: COL.amber, fmt: (v) => money(v, 2) }]} />
        </div>
        <div className="card">
          <div className="card-t">Margin trend</div>
          <ComboChart labels={rows.map((r) => `FY${r.year}`)} bars={rows.map((r) => r.operating_margin ?? 0)} barLabel="Operating margin"
            barFmt={(v) => pct(v)} barColor={COL.blue} signed
            lines={[{ label: "Gross margin", values: L("gross_margin"), color: COL.teal, fmt: pct }]} />
        </div>
      </div>
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-t">Annual statements{st.revenue_cagr != null && <span className="muted sm"> · revenue CAGR {pct(st.revenue_cagr)}</span>}</div>
        <div className="tscroll">
          <table className="dtable">
            <thead>
              <tr><th>FY</th><th className="r">Revenue</th><th className="r">Growth</th><th className="r">Gross mgn</th><th className="r">Op. mgn</th><th className="r">Net income</th><th className="r">Net mgn</th><th className="r">Op. cash flow</th><th className="r">Free cash flow</th><th className="r">Total debt</th><th className="r">Cash</th></tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((r) => (
                <tr key={r.period}>
                  <td><b>{r.year}</b></td><td className="r">{money(r.revenue)}</td>
                  <td className="r" style={{ color: (r.revenue_growth ?? 0) >= 0 ? COL.green : COL.red }}>{pct(r.revenue_growth)}</td>
                  <td className="r">{pct(r.gross_margin)}</td><td className="r">{pct(r.operating_margin)}</td>
                  <td className="r">{money(r.net_income)}</td><td className="r">{pct(r.net_margin)}</td>
                  <td className="r">{money(r.operating_cf)}</td><td className="r">{money(r.free_cf)}</td>
                  <td className="r">{money(r.total_debt)}</td><td className="r">{money(r.cash)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function FinancialStudy({ d }) {
  const nav = useNavigate();
  const s = d.snapshot, h = d.history;
  const ov = d.overall_score;
  const oc = ov >= 60 ? COL.green : ov >= 40 ? COL.amber : COL.red;
  const radarSeries = [
    { name: "Sector median", values: d.scorecard.map((x) => x.sector_score ?? 50), color: COL.grey, dash: "4 3" },
    { name: d.symbol, values: d.scorecard.map((x) => x.score ?? 0), color: COL.teal },
  ];
  const b = d.esg_bridge;
  const peerRows = d.peers.filter((p) => p.profit_margins != null).slice(0, 9)
    .map((p) => ({ label: p.symbol, value: p.profit_margins * 100, display: `${(p.profit_margins * 100).toFixed(1)}%`, color: p.symbol === d.symbol ? COL.teal : COL.grey }));

  return (
    <div className="stack">
      <div className="panel hero">
        <div style={{ flex: 1, minWidth: 300 }}>
          <Kpis items={[
            { label: "Market cap", value: money(s.market_cap), sub: `#${s.market_cap_rank} of ${s.universe}` },
            { label: "Revenue", value: money(s.total_revenue) },
            { label: "Free cash flow", value: money(s.free_cashflow), color: (s.free_cashflow ?? 0) >= 0 ? COL.green : COL.red },
            { label: "Net debt", value: money(s.net_debt), sub: s.net_debt < 0 ? "net cash" : "" },
            { label: "Health score", value: ov != null ? `${ov.toFixed(0)}/100` : "n/a", color: oc, sub: "50 = median" },
          ]} />
          <Callout color={oc}>{d.narrative[0].text}</Callout>
          <div className="grid2" style={{ marginTop: 12 }}>
            <div className="card">
              <div className="card-t" style={{ color: COL.green }}>Strengths</div>
              {d.highlights.strengths.length ? <ul className="notes">{d.highlights.strengths.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="muted sm">No metric above the 80th percentile.</p>}
            </div>
            <div className="card">
              <div className="card-t" style={{ color: COL.red }}>Concerns</div>
              {d.highlights.concerns.length ? <ul className="notes">{d.highlights.concerns.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="muted sm">No metric below the 20th percentile.</p>}
            </div>
          </div>
        </div>
        <div className="hero-gauge" style={{ minWidth: 300 }}>
          <div className="card-t">Financial health profile</div>
          <Radar axes={d.scorecard.map((x) => x.dimension)} series={radarSeries} />
        </div>
      </div>

      <Section title="In-depth explanation" sub="Plain-language reading of the financial profile, generated from the data.">
        <Narrative sections={d.narrative.slice(1)} />
      </Section>

      <Section title="Company snapshot">
        <div className="snap">
          {[
            ["Enterprise value", money(s.enterprise_value)], ["Total cash", money(s.total_cash)], ["Total debt", money(s.total_debt)],
            ["Total assets", money(s.total_assets)], ["Operating cash flow", money(s.operating_cashflow)], ["Employees", int(s.employees)],
            ["Revenue / employee", money(s.revenue_per_employee)], ["Shares outstanding", s.shares_outstanding ? `${(s.shares_outstanding / 1e6).toFixed(0)}M` : "n/a"],
            ["52-week range", s.fifty_two_week_low ? `$${s.fifty_two_week_low.toFixed(2)} - $${s.fifty_two_week_high.toFixed(2)}` : "n/a"],
            ["Avg. volume", int(s.average_volume)], ["Size rank in sector", `#${s.sector_cap_rank} of ${s.sector_size}`], ["Sector", d.sector],
          ].map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}
        </div>
        {d.business_summary && <p className="prose" style={{ marginTop: 12 }}>{d.business_summary}</p>}
      </Section>

      <Section title="Financial history" sub="Price behaviour and multi-year statements.">
        {h.prices.available ? <PriceHistory p={h.prices} symbol={d.symbol} /> : (
          <Callout color={COL.amber}>
            <b>Price history not available yet.</b>
            <div className="sm muted">The backend caches prices and statements under <code>financials/prices</code> and <code>financials/statements</code>. Run <code>scripts/06_fetch_financials.py</code>, or <code>pip install yfinance</code> and reload this page to fetch them automatically.</div>
          </Callout>
        )}
        {h.statements.available && <div style={{ marginTop: 14 }}><Statements st={h.statements} /></div>}
      </Section>

      <Section title="Ratio analysis versus peers" sub="Every metric against its sector and the whole universe. The health bar flips leverage and volatility so a longer bar is always better.">
        <div className="stack">{d.groups.map((g) => <Ratios key={g.key} g={g} />)}</div>
      </Section>

      <Section title="Peer comparison" sub="Same-sector companies closest in size. Click a row to open it.">
        <div className="grid2">
          <div className="card tscroll">
            <table className="dtable">
              <thead><tr><th>Company</th><th className="r">Mkt cap</th><th className="r">Net mgn</th><th className="r">Growth</th><th className="r">D/E</th><th className="r">P/E</th></tr></thead>
              <tbody>
                {d.peers.map((p) => (
                  <tr key={p.symbol} className={p.symbol === d.symbol ? "me clickable" : "clickable"} onClick={() => nav(`/companies/${p.symbol}?tab=financial`)}>
                    <td><b>{p.symbol}</b> <span className="muted">{p.security_name}</span></td>
                    <td className="r">{money(p.market_cap, 1)}</td><td className="r">{pct(p.profit_margins)}</td>
                    <td className="r">{pct(p.revenue_growth)}</td><td className="r">{p.debt_to_equity != null ? `${p.debt_to_equity.toFixed(0)}%` : "n/a"}</td>
                    <td className="r">{p.trailing_pe?.toFixed(1) ?? "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <div className="card-t">Net margin vs peers</div>
            <HBar rows={peerRows} labelWidth={60} fmt={(v) => `${v.toFixed(1)}%`} />
          </div>
        </div>
      </Section>

      {b && (
        <Section title="ESG ↔ financial materiality" sub="How large the safety-enforcement record is relative to the company's economics.">
          <Kpis items={[
            { label: "OSHA penalties", value: money(b.penalties), color: COL.red, sub: `${int(b.violations)} citations` },
            { label: "% of revenue", value: b.pct_of_revenue != null ? `${(b.pct_of_revenue * 100).toFixed(4)}%` : "n/a" },
            { label: "% of free cash flow", value: b.pct_of_free_cashflow != null ? `${(b.pct_of_free_cashflow * 100).toFixed(2)}%` : "n/a" },
            { label: "Citations / 1,000 staff", value: b.violations_per_1000_employees != null ? b.violations_per_1000_employees.toFixed(1) : "n/a" },
            { label: "ESG risk tier", value: b.risk_tier, color: tierColor(b.risk_tier), sub: `score ${b.composite_score.toFixed(1)}` },
          ]} />
          {d.narrative.find((x) => x.title.startsWith("ESG")) && <p className="prose" style={{ marginTop: 10 }}>{d.narrative.find((x) => x.title.startsWith("ESG")).text}</p>}
        </Section>
      )}
      <p className="muted sm">Source: yfinance fundamentals snapshot. Debt / equity follows the yfinance convention (217 = 217%). Generated {d.generated_at}. For informational purposes only.</p>
    </div>
  );
}
