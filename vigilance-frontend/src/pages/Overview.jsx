import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchOverview, fetchCompanies } from "../api";

function tierClass(t) {
  return String(t || "").toLowerCase();
}
function scoreColor(score) {
  if (score >= 70) return "#ff5c7a";
  if (score >= 40) return "#f5c542";
  if (score >= 20) return "#6b7280";
  return "#3dd68c";
}
const TIER_COLORS = {
  Stable: "#3dd68c",
  Neutral: "#6b7280",
  Watchlist: "#f5c542",
  Critical: "#ff5c7a",
};

export default function Overview() {
  const nav = useNavigate();
  const [overview, setOverview] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([fetchOverview(), fetchCompanies({ page: 1, pageSize: 15 })])
      .then(([ov, co]) => {
        setOverview(ov);
        setCompanies(co.results || []);
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  if (error) {
    return <div className="panel" style={{ color: "var(--red)" }}>{error}</div>;
  }
  if (!overview) {
    return <div className="panel">Loading overview…</div>;
  }

  const dist = overview.risk_distribution || [];
  const maxCount = Math.max(...dist.map((d) => d.count), 1);
  const models = overview.top_models || [];

  return (
    <>
      <div className="kpi-row">
        <div className="kpi">
          <label>Entities tracked</label>
          <div className="val">{overview.entities_tracked}</div>
          <div className="sub">FROM API</div>
        </div>
        <div className="kpi">
          <label>Critical alerts</label>
          <div className="val red">{overview.critical_alerts_active}</div>
          <div className="sub">ACTIVE</div>
        </div>
        <div className="kpi">
          <label>Model AUC (mean)</label>
          <div className="val cyan">
            {overview.model_auc_mean != null ? Number(overview.model_auc_mean).toFixed(3) : "—"}
          </div>
          <div className="sub">
            σ {overview.model_auc_std != null ? Number(overview.model_auc_std).toFixed(3) : "—"}
          </div>
        </div>
        <div className="kpi">
          <label>Ingestion SLA</label>
          <div className="val cyan">
            {overview.ingestion_sla_pct != null ? `${overview.ingestion_sla_pct}%` : "—"}
          </div>
          <div className="sub">LIVE API</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-h">
            <h3>
              Risk distribution <span>/ N={overview.entities_tracked}</span>
            </h3>
          </div>
          {/* Fixed-height bars: use px height, not % of auto parent */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: 12,
              height: 180,
              marginTop: 8,
            }}
          >
            {dist.map((b) => {
              const h = Math.max(8, Math.round((b.count / maxCount) * 140));
              const color = TIER_COLORS[b.tier] || "#6b7280";
              return (
                <div
                  key={b.tier}
                  style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "flex-end",
                    height: "100%",
                    cursor: "pointer",
                  }}
                  onClick={() => nav(`/companies?tier=${encodeURIComponent(b.tier)}`)}
                  title={`Filter companies: ${b.tier}`}
                >
                  <div
                    style={{
                      width: "100%",
                      height: h,
                      background: color,
                      borderRadius: "8px 8px 4px 4px",
                      boxShadow: `0 0 12px ${color}33`,
                    }}
                  />
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>{b.tier}</div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{b.count}</div>
                  <div style={{ fontSize: 10, color: "var(--muted)" }}>{b.range}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="panel">
          <div className="panel-h">
            <h3>
              Model matrix <span>Top by AUC</span>
            </h3>
          </div>
          {models.map((m, i) => (
            <div className="model-row" key={i}>
              <div>
                <div className="name">{m.combo_name}</div>
                <div className="desc">
                  {m.combo_group} · {m.model_name}
                </div>
              </div>
              <div className="auc">
                {Number(m.auc).toFixed(3)}
                <div style={{ color: "var(--muted)", fontSize: 10, fontWeight: 400 }}>AUC</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-h">
          <h3>
            Entity risk index <span>Top by score (page 1)</span>
          </h3>
          <Link className="link-cyan" to="/companies">
            All companies →
          </Link>
        </div>
        <table>
          <thead>
            <tr>
              <th>Entity</th>
              <th>Score</th>
              <th>Corroboration</th>
              <th>Tier</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((c) => (
              <tr
                key={c.symbol}
                className="clickable"
                onClick={() => nav(`/companies/${c.symbol}`)}
              >
                <td>
                  <div className="entity-name">{c.canonical_name}</div>
                  <div className="entity-meta">
                    {c.symbol} · {c.gics_sector || "—"}
                  </div>
                </td>
                <td>
                  <span style={{ color: scoreColor(c.composite_score), fontWeight: 600 }}>
                    {Number(c.composite_score).toFixed(1)}
                  </span>
                </td>
                <td>{c.corroboration_count ?? 0}</td>
                <td>
                  <span className={`tier ${tierClass(c.risk_tier)}`}>{c.risk_tier}</span>
                </td>
                <td>
                  <span className={`status ${tierClass(c.status)}`}>{c.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
