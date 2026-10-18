import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { fetchCompanySignals, fetchEsg, fetchFinancialStudy, fetchReasoning } from "../api";
import EsgStudy from "../components/EsgStudy";
import FinancialStudy from "../components/FinancialStudy";
import ReasoningPanel from "../components/ReasoningPanel";
import SignalsStudy from "../components/SignalsStudy";
import { ErrorBox, ExportButton, Skeleton } from "../components/ui";

const TABS = [
  { key: "esg", label: "ESG study", fetch: fetchEsg, report: "esg", reportLabel: "Export ESG report" },
  { key: "financial", label: "Financial study", fetch: fetchFinancialStudy, report: "financial", reportLabel: "Export financial report" },
  { key: "signals", label: "Signals", fetch: fetchCompanySignals, report: "signals", reportLabel: "Export signal register" },
  { key: "reasoning", label: "AI reasoning", fetch: (s) => fetchReasoning(s, false) },
];

/* Shows the real render error on screen instead of a black page. */
class Boundary extends React.Component {
  state = { err: null };
  static getDerivedStateFromError(err) {
    return { err };
  }
  componentDidCatch(err, info) {
    console.error("Tab render failed:", err, info);
  }
  render() {
    if (this.state.err) {
      return (
        <pre className="panel" style={{ color: "#ff5c7a", whiteSpace: "pre-wrap", padding: 16 }}>
          {String(this.state.err.stack || this.state.err)}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function CompanyDetail() {
  const { symbol } = useParams();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = TABS.find((t) => t.key === params.get("tab")) || TABS[0];

  const [cache, setCache] = useState({}); // key -> data
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState({});

  // new company -> forget everything
  useEffect(() => {
    setCache({});
    setErrors({});
  }, [symbol]);

  const load = useCallback(
    (t, force = false) => {
      if (!force && cache[t.key]) return;
      setLoading((l) => ({ ...l, [t.key]: true }));
      setErrors((e) => ({ ...e, [t.key]: null }));
      t.fetch(symbol)
        .then((d) => setCache((c) => ({ ...c, [t.key]: d })))
        .catch((e) => setErrors((x) => ({ ...x, [t.key]: String(e.message || e) })))
        .finally(() => setLoading((l) => ({ ...l, [t.key]: false })));
    },
    [symbol, cache]
  );

  useEffect(() => {
    load(tab); /* eslint-disable-next-line */
  }, [symbol, tab.key]);

  const head = cache.esg || cache.financial || cache.signals || cache.reasoning;
  const name = head?.canonical_name || head?.name || symbol;
  const sector = head?.gics_sector || head?.sector;
  const tier = cache.esg?.risk_tier || cache.signals?.risk_tier || cache.reasoning?.risk_tier;

  const d = cache[tab.key];
  return (
    <>
      <div className="detail-header">
        <div>
          <button className="btn" style={{ marginBottom: 10 }} onClick={() => nav(-1)}>
            ← Back
          </button>
          <h1>{name}</h1>
          <div className="meta">
            {symbol}
            {sector ? ` · ${sector}` : ""}
            {tier && (
              <span className={`tier ${String(tier).toLowerCase()}`} style={{ marginLeft: 10 }}>
                {tier}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          {tab.report && <ExportButton symbol={symbol} kind={tab.report} label={tab.reportLabel} />}
          <Link className="btn" to={`/chat?symbol=${encodeURIComponent(symbol)}`}>
            Ask AI about {symbol}
          </Link>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={t.key === tab.key ? "on" : ""}
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("tab", t.key);
              setParams(next, { replace: true });
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading[tab.key] && !d && (
        <Skeleton
          label={
            tab.key === "financial"
              ? "Building financial study (first load may fetch price history)…"
              : "Building study…"
          }
        />
      )}
      {errors[tab.key] && <ErrorBox error={errors[tab.key]} onRetry={() => load(tab, true)} />}

      <Boundary key={`${tab.key}-${symbol}`}>
        {d && tab.key === "esg" && <EsgStudy d={d} />}
        {d && tab.key === "financial" && <FinancialStudy d={d} />}
        {d && tab.key === "signals" && <SignalsStudy d={d} />}
        {d && tab.key === "reasoning" && <ReasoningPanel company={{ symbol }} reasoning={d} />}
      </Boundary>
    </>
  );
}