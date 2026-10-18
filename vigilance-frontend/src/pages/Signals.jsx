import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchSignals } from "../api";

function sevColor(sev) {
  if (sev >= 9) return "#ff5c7a";
  if (sev >= 6) return "#f5c542";
  return "#8b93a7";
}

const CATEGORIES = ["", "environmental", "governance", "labor", "regulatory", "market", "media"];

export default function Signals() {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  const [category, setCategory] = useState("");
  const [minSeverity, setMinSeverity] = useState("");
  const [q, setQ] = useState("");

  function load(p = 1) {
    setLoading(true);
    setError(null);
    fetchSignals({
      page: p,
      pageSize: 25,
      category: category || undefined,
      minSeverity: minSeverity === "" ? undefined : Number(minSeverity),
    })
      .then((d) => {
        // client-side search on current page results (API has no q yet)
        if (q.trim()) {
          const needle = q.trim().toLowerCase();
          const filtered = (d.results || []).filter(
            (s) =>
              (s.headline || "").toLowerCase().includes(needle) ||
              (s.entity_name || "").toLowerCase().includes(needle) ||
              (s.entity_symbol || "").toLowerCase().includes(needle)
          );
          setData({ ...d, results: filtered });
        } else {
          setData(d);
        }
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    setPage(1);
    load(1);
  }, [category, minSeverity]);

  useEffect(() => {
    load(page);
  }, [page]);

  const results = data?.results || [];
  const total = data?.total || 0;
  const maxPage = Math.max(1, Math.ceil(total / (data?.page_size || 25)));

  return (
    <div className="panel">
      <div className="panel-h">
        <div>
          <div style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--muted)", marginBottom: 4 }}>
            ALERTING PIPELINE · ASYNC
          </div>
          <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 16, color: "var(--text)" }}>
            Live signal feed
          </h3>
          <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 6, maxWidth: 640 }}>
            Filter by category and severity. Click a row to open the company.
          </p>
        </div>
        <button className="btn" type="button" onClick={() => load(page)}>
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          marginBottom: 14,
          alignItems: "center",
        }}
      >
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          style={selectStyle}
        >
          <option value="">All categories</option>
          {CATEGORIES.filter(Boolean).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={minSeverity}
          onChange={(e) => setMinSeverity(e.target.value)}
          style={selectStyle}
        >
          <option value="">Any severity</option>
          {[10, 9, 8, 7, 6, 5].map((n) => (
            <option key={n} value={n}>
              SEV ≥ {n}
            </option>
          ))}
        </select>

        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(page)}
          placeholder="Search headline or entity…"
          style={{ ...selectStyle, minWidth: 220, flex: 1 }}
        />
        <button className="btn primary" type="button" onClick={() => load(page)}>
          Apply search
        </button>
      </div>

      {loading && <p style={{ color: "var(--muted)" }}>Loading…</p>}
      {error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
          <table>
            <thead>
              <tr>
                <th>Signal</th>
                <th>Severity</th>
                <th>Entity</th>
                <th>Category</th>
                <th>Tiers</th>
                <th>Corr.</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {results.map((s) => (
                <tr
                  key={s.id}
                  className="clickable"
                  onClick={() => s.entity_symbol && nav(`/companies/${s.entity_symbol}?tab=signals`)}
                >
                  <td>
                    <div className="entity-name" style={{ fontWeight: 500 }}>
                      {s.headline}
                    </div>
                    <div className="entity-meta">{s.signal_code}</div>
                  </td>
                  <td>
                    <span style={{ color: sevColor(s.severity), fontWeight: 600 }}>
                      {s.severity_label}
                    </span>
                  </td>
                  <td>
                    <div className="entity-name">{s.entity_name}</div>
                    <div className="entity-meta">{s.entity_symbol || s.company_id}</div>
                  </td>
                  <td>{s.category}</td>
                  <td>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {(s.tiers || []).map((t) => (
                        <span className="tag" key={t}>
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>{s.corroboration}</td>
                  <td style={{ color: "var(--muted)" }}>{s.age}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {results.length === 0 && (
            <p style={{ color: "var(--muted)", marginTop: 12 }}>No signals match these filters.</p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
            <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Prev
            </button>
            <span style={{ color: "var(--muted)" }}>
              Page {page} / {maxPage} · {total} signals (server total for category/severity)
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
