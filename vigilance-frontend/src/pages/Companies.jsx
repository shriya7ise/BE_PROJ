import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchCompanies } from "../api";

function tierClass(t) {
  return String(t || "").toLowerCase();
}
function scoreColor(score) {
  if (score >= 70) return "#ff5c7a";
  if (score >= 40) return "#f5c542";
  if (score >= 20) return "#6b7280";
  return "#3dd68c";
}

const TIERS = ["", "Critical", "Watchlist", "Neutral", "Stable"];

export default function Companies() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [tier, setTier] = useState(params.get("tier") || "");
  const [q, setQ] = useState("");

  const [term, setTerm] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchCompanies({ page, pageSize: 50, tier: tier || undefined, search: term || undefined })
      .then(setData)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [page, tier, term]);

  function applyTier(t) {
    setTier(t);
    setPage(1);
    if (t) params.set("tier", t);
    else params.delete("tier");
    setParams(params);
  }

  const results = data?.results || [];
  const total = data?.total || 0;
  const pageSize = data?.page_size || 50;
  const maxPage = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="panel">
      <div className="panel-h">
        <h3>
          Companies <span>{total} match filters</span>
        </h3>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
        <select value={tier} onChange={(e) => applyTier(e.target.value)} style={selectStyle}>
          <option value="">All tiers</option>
          {TIERS.filter(Boolean).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setPage(1);
              setTerm(q.trim());
            }
          }}
          placeholder="Search name, symbol, sector…"
          style={{ ...selectStyle, minWidth: 220, flex: 1 }}
        />
        <button
          className="btn primary"
          type="button"
          onClick={() => {
            setPage(1);
            setTerm(q.trim());
          }}
        >
          Search
        </button>
      </div>

      {loading && <p style={{ color: "var(--muted)" }}>Loading…</p>}
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
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
              {results.map((c) => (
                <tr
                  key={c.symbol}
                  className="clickable"
                  onClick={() => nav(`/companies/${c.symbol}`)}
                >
                  <td>
                    <div className="entity-name">{c.canonical_name}</div>
                    <div className="entity-meta">
                      {c.symbol} · {c.gics_sector || "—"}
                      {c.score_is_estimated ? " · estimated" : ""}
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
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Prev
            </button>
            <span style={{ color: "var(--muted)" }}>
              Page {page} / {maxPage}
            </span>
            <button
              className="btn"
              disabled={page >= maxPage}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}

const selectStyle = {
  background: "var(--panel-2)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 13,
};
