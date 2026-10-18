import { Fragment, useMemo, useState } from "react";
import { ComboChart, Donut, HBar, COL } from "./charts";
import { Callout, Chip, Kpis, Section, ordinal, sevColor, tierColor } from "./ui";

const SEV = { Critical: COL.red, High: COL.orange, Medium: COL.amber, Low: COL.mute };
const PAGE = 20;

export default function SignalsStudy({ d }) {
  const [cat, setCat] = useState("");
  const [minSev, setMinSev] = useState(0);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const sev = Object.fromEntries(d.by_severity.map((x) => [x.label, x.count]));
  const rows = useMemo(
    () => d.signals.filter((s) => (!cat || s.category === cat) && s.severity >= minSev),
    [d, cat, minSev]
  );
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice((page - 1) * PAGE, page * PAGE);
  const tc = tierColor(d.risk_tier);

  return (
    <div className="stack">
      <div className="panel">
        <Kpis items={[
          { label: "Active signals", value: d.total, sub: `universe median ${d.universe_median.toFixed(0)}` },
          { label: "Critical", value: sev.Critical || 0, color: COL.red },
          { label: "High", value: sev.High || 0, color: COL.orange },
          { label: "Percentile vs all", value: d.universe_percentile != null ? ordinal(d.universe_percentile) : "n/a", sub: "more signals = higher" },
          { label: "Evidence streams", value: `${d.corroboration_count} / 4`, color: tc, sub: d.status },
        ]} />
        <Callout color={tc}>
          {d.canonical_name} has {d.total} signals, {d.universe_percentile != null && d.universe_percentile >= 75 ? "well above" : d.universe_percentile != null && d.universe_percentile <= 40 ? "below" : "around"} the
          universe median of {d.universe_median.toFixed(0)}. {sev.Critical ? `${sev.Critical} are rated Critical (willful or repeat OSHA citations). ` : ""}
          Signals are prompts for analyst review, not findings of wrongdoing.
        </Callout>
      </div>

      <div className="grid3">
        <Section title="By category">
          <HBar labelWidth={110} rows={d.by_category.map((c) => ({ label: c.category, value: c.count, display: c.count }))} />
        </Section>
        <Section title="By severity">
          <Donut center={d.total} sub="signals" size={130}
            parts={d.by_severity.filter((x) => x.count).map((x) => ({ label: x.label, value: x.count, color: SEV[x.label] }))} />
        </Section>
        <Section title="By year">
          <ComboChart height={170} labels={d.by_year.map((y) => String(y.year))} bars={d.by_year.map((y) => y.count)}
            barLabel="Signals" barColor={d.by_year.map((y) => sevColor(y.max_severity))} />
        </Section>
      </div>

      <Section title="Signal log" sub="Highest severity first. Click a row for detail."
        right={
          <div className="filters">
            <select value={cat} onChange={(e) => { setCat(e.target.value); setPage(1); }}>
              <option value="">All categories</option>
              {d.by_category.map((c) => <option key={c.category} value={c.category}>{c.category} ({c.count})</option>)}
            </select>
            <select value={minSev} onChange={(e) => { setMinSev(Number(e.target.value)); setPage(1); }}>
              <option value={0}>Any severity</option><option value={5}>Medium+</option><option value={7}>High+</option><option value={9}>Critical</option>
            </select>
          </div>
        }>
        <div className="tscroll">
          <table className="dtable">
            <thead><tr><th>Date</th><th>Severity</th><th>Category</th><th>Source</th><th>Signal</th></tr></thead>
            <tbody>
              {shown.map((s) => (
                <Fragment key={s.id}>
                  <tr className="clickable" onClick={() => setOpen(open === s.id ? null : s.id)}>
                    <td className="nowrap">{s.date || "ongoing"}<div className="muted sm">{s.age}</div></td>
                    <td><b style={{ color: sevColor(s.severity) }}>{s.severity.toFixed(1)}</b> <span className="muted sm">{s.severity_label}</span></td>
                    <td>{s.category}</td>
                    <td>{s.tiers.map((t) => <Chip key={t} color={COL.blue}>{t}</Chip>)}</td>
                    <td>{s.headline}</td>
                  </tr>
                  {open === s.id && (
                    <tr className="detail-row"><td colSpan={5}>
                      <span className="muted">Signal code</span> <code>{s.signal_code}</code>
                      {s.detail && <> · <span className="muted">Detail</span> {s.detail}</>}
                    </td></tr>
                  )}
                </Fragment>
              ))}
              {!shown.length && <tr><td colSpan={5} className="muted">No signals match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
          <span className="muted">Page {page} of {pages} · {rows.length} signals</span>
          <button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      </Section>
      <p className="muted sm">Signals are generated by transparent rules over OSHA citations, 10-K language, market statistics, satellite data and news volume. Generated {d.generated_at}.</p>
    </div>
  );
}
