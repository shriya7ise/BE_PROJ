import { useState } from "react";
import { ComboChart, Donut, Gauge, HBar, PercentileStrip, COL } from "./charts";
import { Callout, Chip, Kpis, Narrative, Section, int, money, ordinal, pct, tierColor } from "./ui";

const TYPE_COLOR = { S: COL.amber, W: COL.red, R: COL.orange, O: COL.grey, U: "#3a4458" };

function Pillar({ p }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card pillar">
      <div className="pillar-h">
        <strong>{p.label}</strong>
        <Chip color={p.level === "very high" || p.level === "high" ? COL.amber : COL.mute}>{p.level} emphasis</Chip>
      </div>
      <div className="pillar-v">
        {p.value != null ? p.value.toFixed(3) : "n/a"} <small>terms / 1k words</small>
      </div>
      <p className="muted sm">{p.description}</p>
      <div className="kv"><span>vs all companies</span><PercentileStrip pct={p.universe_percentile} /></div>
      <div className="kv"><span>vs sector peers</span><PercentileStrip pct={p.sector_percentile} /></div>
      <div className="kv sm muted">
        <span>Median (all / sector)</span>
        <span>{p.universe_median?.toFixed(3)} / {p.sector_median?.toFixed(3) ?? "n/a"}</span>
      </div>
      {p.passages?.length > 0 && (
        <>
          <button className="linkbtn" onClick={() => setOpen(!open)}>
            {open ? "Hide" : "Show"} {p.passages.length} passages from the 10-K
          </button>
          {open && p.passages.map((t, i) => <blockquote key={i}>{t}</blockquote>)}
        </>
      )}
    </div>
  );
}

function CitationTable({ rows, showExposed }) {
  return (
    <div className="tscroll">
      <table className="dtable">
        <thead>
          <tr><th>Date</th><th>Standard</th><th>Class</th><th className="r">Penalty</th>{showExposed && <th className="r">Exposed</th>}</tr>
        </thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={i}>
              <td>{c.date}</td>
              <td><b>{c.standard}</b> <span className="muted">{c.title}</span></td>
              <td><Chip color={c.type === "Willful" ? COL.red : c.type === "Repeat" ? COL.orange : c.type === "Serious" ? COL.amber : COL.mute}>{c.type}</Chip></td>
              <td className="r">{money(c.penalty)}</td>
              {showExposed && <td className="r">{c.exposed ?? "n/a"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EsgStudy({ d }) {
  const o = d.osha, n = d.news, g = d.geo;
  const tc = tierColor(d.risk_tier);
  return (
    <div className="stack">
      {/* HERO */}
      <div className="panel hero">
        <div className="hero-gauge">
          <Gauge value={d.composite_score} color={tc} />
          <div className="muted sm" style={{ textAlign: "center" }}>Composite risk score</div>
          <Chip color={tc}>{d.risk_tier.toUpperCase()}</Chip>
        </div>
        <div style={{ flex: 1, minWidth: 280 }}>
          <Kpis items={[
            { label: "Rank", value: `#${d.rank}`, sub: `of ${d.universe} tracked` },
            { label: "Model P(risk)", value: d.model_probability != null ? pct(d.model_probability, 0) : "n/a", sub: d.model_split === "train" ? "in-sample" : d.model_split ? `${d.model_split} split` : "" , color: COL.teal },
            { label: "Evidence streams", value: `${d.corroboration_count} / 4`, sub: d.status },
            { label: "OSHA penalties", value: money(o.total_penalty || 0), color: o.total_penalty ? COL.red : undefined, sub: `${int(o.n_violations)} citations` },
          ]} />
          <Callout color={tc}>{d.narrative[0].text}</Callout>
        </div>
      </div>

      {/* PROFILE + FLAGS */}
      <div className="grid2">
        <Section title="Evidence streams" sub="Independent sources that must agree before a company is escalated.">
          <div className="flags">
            {d.flags.map((f) => (
              <div key={f.key} className={`flag ${f.triggered ? "on" : ""}`}>
                <span className="flag-dot" />
                <div>
                  <b>{f.label}</b>
                  <div className="muted sm">{f.detail}</div>
                </div>
                <Chip color={f.triggered ? COL.red : COL.green}>{f.triggered ? "FLAGGED" : "CLEAR"}</Chip>
              </div>
            ))}
          </div>
          <div className="reco"><b>Recommended action</b><p>{d.recommendation}</p></div>
        </Section>
        <Section title="Business profile" sub={[d.gics_sector, d.industry].filter(Boolean).join(" · ")}>
          <p className="prose">{d.business_summary || "No business description available."}</p>
          {d.filing.available && (
            <p className="muted sm" style={{ marginTop: 10 }}>
              Source filing: {d.filing.form || "10-K"} filed {d.filing.filing_date || "n/a"} (period {d.filing.report_date || "n/a"}),
              {" "}accession {d.filing.accession || "n/a"}, ~{int(d.filing.word_count)} words analysed.
            </p>
          )}
        </Section>
      </div>

      {/* NARRATIVE */}
      <Section title="In-depth explanation" sub="Generated from this company's data, section by section. Every number traces to a source table.">
        <Narrative sections={d.narrative} />
      </Section>

      {/* PILLARS */}
      <Section title="Environmental · Social · Governance · Safety" sub="Keyword intensity in the latest 10-K, benchmarked against all companies and the sector. Higher means management discusses the topic more; it is a measure of attention and exposure, not performance.">
        <div className="grid4">{d.pillars.map((p) => <Pillar key={p.key} p={p} />)}</div>
      </Section>

      {/* OSHA */}
      <Section title="Regulatory & enforcement record (OSHA)" sub="Citation-level records matched to this company.">
        {!o.has_records ? (
          <p className="muted">No OSHA citations on record ({o.n_inspections} inspections).</p>
        ) : (
          <>
            <Kpis items={[
              { label: "Inspections", value: int(o.n_inspections) },
              { label: "Citations", value: int(o.n_violations), sub: `${(o.violations_per_inspection ?? 0).toFixed(2)} per inspection` },
              { label: "Total penalties", value: money(o.total_penalty), color: COL.red, sub: `rank #${o.rank} of ${o.universe}` },
              { label: "Serious / willful / repeat", value: pct(o.serious_share, 0), color: COL.amber, sub: `${o.willful} willful · ${o.repeat} repeat` },
              { label: "Trend", value: o.trend.label, sub: o.trend.change_pct != null ? `${o.trend.change_pct > 0 ? "+" : ""}${o.trend.change_pct.toFixed(0)}% (${o.trend.recent_window} vs ${o.trend.prior_window})` : "" },
            ]} />
            <div className="grid2" style={{ marginTop: 14 }}>
              <div className="card">
                <div className="card-t">Penalties and citations by year</div>
                <ComboChart
                  labels={o.by_year.map((y) => String(y.year))}
                  bars={o.by_year.map((y) => y.penalty)} barLabel="Penalties" barFmt={(v) => money(v, 1)}
                  lines={[
                    { label: "Citations", values: o.by_year.map((y) => y.violations), color: COL.red },
                    { label: "Serious/W/R", values: o.by_year.map((y) => y.serious), color: COL.amber, dash: "4 3" },
                  ]}
                />
              </div>
              <div className="card">
                <div className="card-t">Citations by severity class</div>
                <Donut
                  center={int(o.n_violations)} sub="citations"
                  parts={o.by_type.map((t) => ({ label: t.label, value: t.count, color: TYPE_COLOR[t.code] || COL.grey, display: `${t.count} · ${money(t.penalty, 1)}` }))}
                />
                <p className="muted sm" style={{ marginTop: 8 }}>
                  {pct(o.contested_share, 0)} of citations were contested · {int(o.workers_exposed)} worker exposures recorded · {o.first_date} to {o.last_date}
                </p>
              </div>
            </div>
            <div className="grid2" style={{ marginTop: 14 }}>
              <div className="card">
                <div className="card-t">Costliest standards</div>
                <HBar labelWidth={210} rows={o.top_standards.map((s) => ({ label: s.code, sub: s.title, value: s.penalty, display: `${money(s.penalty, 1)} · ${s.count}` }))} />
              </div>
              <div className="card">
                <div className="card-t">Largest individual citations</div>
                <CitationTable rows={o.largest_citations.slice(0, 6)} showExposed />
              </div>
            </div>
            <div className="card" style={{ marginTop: 14 }}>
              <div className="card-t">Most recent citations</div>
              <CitationTable rows={o.recent_citations} />
            </div>
          </>
        )}
      </Section>

      {/* NEWS + GEO */}
      <div className="grid2">
        <Section title="Media attention" sub="Headline volume from collected news feeds.">
          {!n.available ? <p className="muted">No news collected for this company.</p> : (
            <>
              <Kpis items={[
                { label: "Articles", value: int(n.total_articles) },
                { label: "Last 30 days", value: int(n.last_30d), color: n.last_30d > 2 * n.avg_per_month ? COL.amber : undefined },
                { label: "Avg / month", value: n.avg_per_month.toFixed(0) },
              ]} />
              <ComboChart height={170} labels={n.monthly.map((m) => m.month)} bars={n.monthly.map((m) => m.count)} barLabel="Articles" barColor={COL.blue} />
              <div className="headlines">
                {n.latest.map((a, i) => (
                  <a key={i} href={a.url} target="_blank" rel="noreferrer">
                    <span>{a.title}</span><small>{a.domain} · {a.date}</small>
                  </a>
                ))}
              </div>
              {!n.tone_available && <p className="muted sm">Sentiment tone scores are not in the dataset, so only volume is analysed.</p>}
            </>
          )}
        </Section>
        <Section title="Geospatial footprint" sub="Satellite-derived indicators around the geocoded location.">
          {!g.available ? <p className="muted">{g.note || "No satellite data available."}</p> : (
            <>
              <p className="muted sm">📍 {g.address} ({g.lat?.toFixed(3)}, {g.lon?.toFixed(3)})</p>
              <div className="geo">
                {g.metrics.map((m) => (
                  <div className="geo-row" key={m.key} title={m.description}>
                    <span>{m.label}</span>
                    <b>{m.value.toFixed(m.unit === "%" || m.unit === "°C" ? 1 : 2)}{m.unit}</b>
                    <PercentileStrip pct={m.percentile} color={COL.blue} />
                  </div>
                ))}
              </div>
              <Callout color={COL.amber}><span className="sm">{g.caveat}</span></Callout>
            </>
          )}
        </Section>
      </div>

      {/* MODEL */}
      <Section title="Model view" sub="Four-way XGBoost classifier (financial + ESG + news + geographic features).">
        <div className="grid2">
          <div className="card">
            <div className="card-t">Top global drivers (feature importance)</div>
            <HBar labelWidth={200} color={COL.blue} rows={d.top_drivers.map((x) => ({ label: x.feature.replace(/_/g, " "), value: x.importance * 100, display: `${(x.importance * 100).toFixed(1)}%` }))} />
          </div>
          <div className="card">
            <div className="card-t">How to read this</div>
            <p className="prose">
              The model gives this company a {d.model_probability != null ? pct(d.model_probability, 1) : "n/a"} probability of material workplace-safety risk.
              {d.model_split === "train" && " It was part of the training set, so the figure is in-sample and optimistic."}
              {" "}Driver importances are global: they describe the model, not this specific company.
            </p>
          </div>
        </div>
      </Section>

      <Section title="Methodology & caveats">
        <ul className="notes">{d.methodology.map((m, i) => <li key={i}>{m}</li>)}</ul>
        <p className="muted sm">Generated {d.generated_at}. For informational purposes only.</p>
      </Section>
    </div>
  );
}
