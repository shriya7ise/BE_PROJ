import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { alertsApi } from "../alertsApi";
import { LineChart } from "../components/charts";

/* ---------- constants & helpers ---------- */
const SEV = {
  critical: { c: "#ff5c7a", label: "Critical" },
  high: { c: "#ff8a4c", label: "High" },
  medium: { c: "#f5c542", label: "Medium" },
  low: { c: "#5aa9ff", label: "Low" },
};
const STATE_LABEL = { new: "New", acknowledged: "Acknowledged", snoozed: "Snoozed", resolved: "Resolved" };
const STATE_TABS = [
  ["open", "Open"], ["new", "Unreviewed"], ["acknowledged", "Acknowledged"],
  ["snoozed", "Snoozed"], ["resolved", "Resolved"], ["all", "All"],
];
const EVENT_LABEL = {
  created: "Raised", changed: "Changed", acknowledged: "Acknowledged", snoozed: "Snoozed", snooze_ended: "Snooze ended",
  resolved: "Resolved", reopened: "Reopened", auto_resolved: "Auto-resolved", severity_increased: "Severity increased",
  note: "Note", expired: "Expired",
};

function ago(iso) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  const m = s / 60;
  if (m < 60) return `${Math.floor(m)}m ago`;
  const h = m / 60;
  if (h < 24) return `${Math.floor(h)}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const money = (v) => (v == null ? "—" : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);

function SevChip({ sev }) {
  const s = SEV[sev] || SEV.low;
  return (
    <span style={{ color: s.c, border: `1px solid ${s.c}`, borderRadius: 999, padding: "1px 8px", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>
      {s.label}
    </span>
  );
}
function StateChip({ a }) {
  const c = a.state === "new" ? "#2ee6a8" : a.state === "resolved" ? "#6b7280" : "#8b93a7";
  return (
    <span style={{ color: c, fontSize: 11 }}>
      {STATE_LABEL[a.state] || a.state}
      {a.state === "snoozed" && a.snooze_until ? ` until ${new Date(a.snooze_until).toLocaleDateString()}` : ""}
    </span>
  );
}

const sel = {
  background: "var(--panel-2)", color: "var(--text)", border: "1px solid var(--border)",
  borderRadius: 6, padding: "7px 9px", fontSize: 13,
};

/* =====================================================================
   Detail drawer
   ===================================================================== */
function Detail({ id, reloadKey, onClose, onAct, cfg, onToggleWatch }) {
  const nav = useNavigate();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState("");
  const [days, setDays] = useState(7);

  useEffect(() => {
    let live = true;
    setErr(null);
    alertsApi.get(id).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [id, reloadKey]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const a = d?.alert;
  const ctx = d?.context;
  const hist = (d?.history || []).map((h) => ({ x: h.t.slice(0, 16).replace("T", " "), y: h.score }));
  const watched = a ? (cfg?.settings?.watchlist || []).includes(a.symbol) : false;

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 40 }} />
      <aside
        style={{
          position: "fixed", top: 0, right: 0, bottom: 0, width: "min(560px, 100vw)", zIndex: 50,
          background: "var(--panel)", borderLeft: "1px solid var(--border)", overflowY: "auto", padding: 20,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
          <span style={{ fontSize: 11, letterSpacing: "0.08em", color: "var(--muted)" }}>ALERT #{id}</span>
          <button className="btn" onClick={onClose}>Close ✕</button>
        </div>
        {err && <div style={{ color: "var(--red)" }}>{err}</div>}
        {!a && !err && <div style={{ color: "var(--muted)" }}>Loading…</div>}
        {a && (
          <>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
              <SevChip sev={a.severity} />
              <StateChip a={a} />
              <span style={{ color: "var(--muted)", fontSize: 11 }}>{a.kind === "change" ? "Change" : "Standing condition"}</span>
            </div>
            <h2 style={{ fontSize: 17, margin: "4px 0 6px" }}>{a.title}</h2>
            <div style={{ color: "var(--muted)", fontSize: 12, marginBottom: 12 }}>
              <b style={{ color: "var(--text)" }}>{a.symbol}</b> · {a.name} · {a.sector}{" "}
              <button className="btn" style={{ marginLeft: 6, padding: "1px 8px" }} onClick={() => onToggleWatch(a.symbol)}>
                {watched ? "★ Watching" : "☆ Watch"}
              </button>
            </div>

            <p style={{ fontSize: 13, lineHeight: 1.5, margin: "0 0 10px" }}>{a.detail}</p>
            {(a.from_value || a.to_value) && (
              <div style={{ fontSize: 13, marginBottom: 12 }}>
                {a.from_value ? <>{a.from_value} <span style={{ color: "var(--muted)" }}>→</span> </> : null}
                <b>{a.to_value}</b>
              </div>
            )}

            {ctx && (
              <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-t">Where it stands now</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "6px 16px", fontSize: 13 }}>
                  <div><span style={{ color: "var(--muted)" }}>Score </span><b>{Number(ctx.score).toFixed(1)}</b> ({ctx.tier})</div>
                  <div><span style={{ color: "var(--muted)" }}>Status </span><b>{ctx.status}</b></div>
                  <div><span style={{ color: "var(--muted)" }}>Risk signals </span><b>{ctx.corro} of 4</b></div>
                  <div><span style={{ color: "var(--muted)" }}>Rank </span><b>#{ctx.rank}</b> of {ctx.of}</div>
                  <div><span style={{ color: "var(--muted)" }}>Violations </span><b>{Number(ctx.n_viol).toFixed(0)}</b></div>
                  <div><span style={{ color: "var(--muted)" }}>Penalties </span><b>{money(ctx.penalty)}</b></div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <span style={{ color: "var(--muted)" }}>Sector average score </span>
                    <b>{ctx.sector_avg_score ?? "—"}</b> <span style={{ color: "var(--muted)" }}>({ctx.sector_size} companies)</span>
                  </div>
                </div>
              </div>
            )}

            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-t">Score history</div>
              {hist.length >= 2 ? (
                <LineChart data={hist} height={150} yFmt={(v) => v.toFixed(0)} />
              ) : (
                <p className="muted sm" style={{ margin: 0 }}>
                  History builds as the underlying data changes and snapshots are recorded ({hist.length} so far). Press “Refresh data” after re-running your pipeline.
                </p>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
              {a.state === "new" && <button className="btn primary" onClick={() => onAct(a.id, { action: "ack", note })}>Acknowledge</button>}
              {(a.state === "new" || a.state === "acknowledged") && (
                <>
                  <select style={sel} value={days} onChange={(e) => setDays(Number(e.target.value))}>
                    {[1, 3, 7, 14, 30].map((n) => <option key={n} value={n}>{n} day{n > 1 ? "s" : ""}</option>)}
                  </select>
                  <button className="btn" onClick={() => onAct(a.id, { action: "snooze", days, note })}>Snooze</button>
                </>
              )}
              {a.state !== "resolved" && <button className="btn" onClick={() => onAct(a.id, { action: "resolve", note })}>Resolve</button>}
              {(a.state === "resolved" || a.state === "snoozed") && <button className="btn" onClick={() => onAct(a.id, { action: "reopen", note })}>Reopen</button>}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              <button className="btn" onClick={() => nav(`/companies/${encodeURIComponent(a.symbol)}?tab=reasoning`)}>Open company study</button>
              <button
                className="btn primary"
                onClick={() =>
                  nav(`/chat?symbol=${encodeURIComponent(a.symbol)}&ask=${encodeURIComponent(
                    `Why was this alert raised for ${a.name} ("${a.title}") and what measurable actions should we take?`
                  )}`)
                }
              >
                Ask AI for recommended actions
              </button>
            </div>

            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-t">Note</div>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={a.note ? `Latest: ${a.note}` : "Add context for your team (saved to the timeline)…"}
                rows={3}
                style={{ ...sel, width: "100%", resize: "vertical", boxSizing: "border-box" }}
              />
              <button className="btn" style={{ marginTop: 6 }} disabled={!note.trim()} onClick={() => { onAct(a.id, { action: "note", note }); setNote(""); }}>
                Save note
              </button>
            </div>

            <div className="card">
              <div className="card-t">Timeline</div>
              {(d.events || []).map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "5px 0", borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <span style={{ width: 120, color: "var(--muted)", flexShrink: 0 }}>{fmtDate(e.ts)}</span>
                  <span>
                    <b>{EVENT_LABEL[e.action] || e.action}</b>
                    {e.actor && e.actor !== "system" ? ` · ${e.actor}` : ""}
                    {e.detail ? <div style={{ color: "var(--muted)" }}>{e.detail}</div> : null}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </aside>
    </>
  );
}

/* =====================================================================
   Settings
   ===================================================================== */
function Settings({ cfg, companies, onSave, onTest }) {
  const [draft, setDraft] = useState(() => JSON.parse(JSON.stringify(cfg.settings)));
  const [wlInput, setWlInput] = useState("");
  const [testRes, setTestRes] = useState(null);
  const [saving, setSaving] = useState(false);
  const meta = cfg.rule_meta;
  const symbols = useMemo(() => new Set(companies.map((c) => c.symbol)), [companies]);

  const setRule = (rule, key, val) =>
    setDraft((d) => ({ ...d, rules: { ...d.rules, [rule]: { ...d.rules[rule], [key]: val } } }));
  const addWatch = () => {
    const s = wlInput.trim().toUpperCase().split(/[\s(]/)[0];
    if (s && !draft.watchlist.includes(s)) setDraft((d) => ({ ...d, watchlist: [...d.watchlist, s] }));
    setWlInput("");
  };
  const group = (kind) => Object.entries(meta).filter(([, m]) => m.kind === kind);

  const RuleCard = ([rule, m]) => (
    <div key={rule} className="card" style={{ marginBottom: 8, opacity: draft.rules[rule].enabled ? 1 : 0.6 }}>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600 }}>
        <input type="checkbox" checked={!!draft.rules[rule].enabled} onChange={(e) => setRule(rule, "enabled", e.target.checked)} />
        {m.label}
      </label>
      <div style={{ color: "var(--muted)", fontSize: 12, margin: "4px 0 6px 24px" }}>{m.description}</div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginLeft: 24 }}>
        {m.fields.map((f) => (
          <label key={f.key} style={{ fontSize: 12, color: "var(--muted)" }}>
            {f.label}
            <input
              type="number" min={f.min} max={f.max} step={f.type === "int" ? 1 : "any"}
              value={draft.rules[rule][f.key] ?? ""}
              onChange={(e) => setRule(rule, f.key, e.target.value)}
              style={{ ...sel, display: "block", width: 150, marginTop: 3 }}
            />
          </label>
        ))}
      </div>
    </div>
  );

  const channelNote = (ok, envName) => (
    <span style={{ fontSize: 11, color: ok ? "#3dd68c" : "#f5c542", marginLeft: 8 }}>
      {ok ? "server configured ✓" : `not configured on the server (${envName})`}
    </span>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="panel">
        <div className="panel-h"><h3>Standing conditions</h3></div>
        <p className="muted sm" style={{ marginTop: 0 }}>Open when the condition becomes true and close automatically when it clears.</p>
        {group("condition").map(RuleCard)}
      </div>

      <div className="panel">
        <div className="panel-h"><h3>Change detection</h3></div>
        <p className="muted sm" style={{ marginTop: 0 }}>Compare each new data snapshot with the previous one. These stay open until someone handles them.</p>
        {group("change").map(RuleCard)}
      </div>

      <div className="panel">
        <div className="panel-h"><h3>Watchlist</h3></div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
          <input
            list="wl-list" value={wlInput} onChange={(e) => setWlInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addWatch()} placeholder="Add a ticker (for example DLTR)…" style={{ ...sel, width: 260 }}
          />
          <datalist id="wl-list">
            {companies.map((c) => <option key={c.symbol} value={c.symbol}>{c.canonical_name}</option>)}
          </datalist>
          <button className="btn" onClick={addWatch}>Add</button>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {draft.watchlist.length === 0 && <span className="muted sm">No companies watched yet.</span>}
          {draft.watchlist.map((s) => (
            <span key={s} style={{ border: "1px solid var(--border)", borderRadius: 999, padding: "2px 10px", fontSize: 12, color: symbols.size && !symbols.has(s) ? "#f5c542" : "var(--text)" }}>
              {s}{" "}
              <button type="button" style={{ background: "none", border: 0, color: "var(--muted)", cursor: "pointer" }} onClick={() => setDraft((d) => ({ ...d, watchlist: d.watchlist.filter((x) => x !== s) }))}>×</button>
            </span>
          ))}
        </div>
        <label style={{ fontSize: 13 }}>
          <input type="checkbox" checked={draft.watchlist_only} onChange={(e) => setDraft((d) => ({ ...d, watchlist_only: e.target.checked }))} />{" "}
          Only raise alerts for watched companies (all other open alerts are closed)
        </label>
      </div>

      <div className="panel">
        <div className="panel-h"><h3>Notifications</h3></div>
        <p className="muted sm" style={{ marginTop: 0 }}>
          New alerts at or above the chosen severity are sent as one message per evaluation. Secrets live in the backend <code>.env</code>, never in the browser.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={draft.notify.slack} onChange={(e) => setDraft((d) => ({ ...d, notify: { ...d.notify, slack: e.target.checked } }))} /> Slack
            {channelNote(cfg.channels.slack, "ALERT_SLACK_WEBHOOK")}
          </label>
          <label style={{ fontSize: 13 }}>
            <input type="checkbox" checked={draft.notify.email} onChange={(e) => setDraft((d) => ({ ...d, notify: { ...d.notify, email: e.target.checked } }))} /> Email
            {channelNote(cfg.channels.email, "SMTP_HOST, ALERT_EMAIL_TO")}
          </label>
          <label style={{ fontSize: 13 }}>
            Minimum severity{" "}
            <select style={sel} value={draft.notify.min_severity} onChange={(e) => setDraft((d) => ({ ...d, notify: { ...d.notify, min_severity: e.target.value } }))}>
              {Object.keys(SEV).reverse().map((s) => <option key={s} value={s}>{SEV[s].label}</option>)}
            </select>
          </label>
          <div>
            <button className="btn" onClick={async () => setTestRes(await onTest())}>Send test message</button>
            {testRes && <span className="muted sm" style={{ marginLeft: 10 }}>Slack: {testRes.slack}; Email: {testRes.email}</span>}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h3>Schedule and retention</h3></div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, color: "var(--muted)" }}>
            Re-evaluate every (hours)
            <input type="number" min={1} max={168} value={draft.snapshot_interval_hours} onChange={(e) => setDraft((d) => ({ ...d, snapshot_interval_hours: e.target.value }))} style={{ ...sel, display: "block", width: 140, marginTop: 3 }} />
          </label>
          <label style={{ fontSize: 12, color: "var(--muted)" }}>
            Close untouched change alerts after (days)
            <input type="number" min={1} max={365} value={draft.auto_expire_days} onChange={(e) => setDraft((d) => ({ ...d, auto_expire_days: e.target.value }))} style={{ ...sel, display: "block", width: 140, marginTop: 3 }} />
          </label>
        </div>
      </div>

      <div>
        <button
          className="btn primary" disabled={saving}
          onClick={async () => { setSaving(true); try { await onSave(draft); } finally { setSaving(false); } }}
        >
          {saving ? "Saving…" : "Save and apply"}
        </button>
        <span className="muted sm" style={{ marginLeft: 10 }}>Alerts are re-evaluated immediately with the new rules.</span>
      </div>
    </div>
  );
}

/* =====================================================================
   Page
   ===================================================================== */
export default function Alerts() {
  const [params, setParams] = useSearchParams();
  const openId = params.get("alert") ? Number(params.get("alert")) : null;

  const [tab, setTab] = useState("alerts");
  const [filters, setFilters] = useState({ state: "open", severity: "", rule: "", sector: "", q: "", watchlist: false, sort: "severity" });
  const [qInput, setQInput] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [toast, setToast] = useState(null);
  const [detailKey, setDetailKey] = useState(0);
  const [settingsKey, setSettingsKey] = useState(0);

  const flash = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast((t) => (t === msg ? null : t)), 5000);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, s] = await Promise.all([alertsApi.list({ ...filters, page, page_size: 25 }), alertsApi.summary()]);
      setData(d);
      setSummary(s);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);
  useEffect(() => { alertsApi.settings().then(setCfg).catch(() => {}); alertsApi.companies().then(setCompanies).catch(() => {}); }, []);
  useEffect(() => {
    const t = setTimeout(() => { setFilters((f) => (f.q === qInput ? f : { ...f, q: qInput })); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const setF = (patch) => { setFilters((f) => ({ ...f, ...patch })); setPage(1); setSelected(new Set()); };
  const openDetail = (id) => { const n = new URLSearchParams(params); n.set("alert", String(id)); setParams(n, { replace: true }); };
  const closeDetail = useCallback(() => { const n = new URLSearchParams(params); n.delete("alert"); setParams(n, { replace: true }); }, [params, setParams]);

  async function act(id, body) {
    try {
      await alertsApi.act(id, body);
      flash(`Alert #${id}: ${body.action === "ack" ? "acknowledged" : body.action === "note" ? "note saved" : body.action + (body.action.endsWith("e") ? "d" : "ed")}`);
      setDetailKey((k) => k + 1);
      load();
    } catch (e) { flash(`Failed: ${e.message || e}`); }
  }
  async function bulk(action, days = 7) {
    try {
      const r = await alertsApi.bulk({ ids: [...selected], action, days });
      flash(`${r.updated} alert(s) updated`);
      setSelected(new Set());
      load();
    } catch (e) { flash(`Failed: ${e.message || e}`); }
  }
  async function refreshData() {
    setRefreshing(true);
    try {
      const { run } = await alertsApi.refresh(true);
      flash(`Data re-read. ${run.data_changed ? "Data changed" : "Data unchanged"}; ${run.new_alerts} new or updated alert(s), ${run.auto_resolved} closed automatically.`);
      await load();
    } catch (e) { flash(`Refresh failed: ${e.message || e}`); } finally { setRefreshing(false); }
  }
  async function toggleWatch(sym) {
    if (!cfg) return;
    const wl = new Set(cfg.settings.watchlist);
    wl.has(sym) ? wl.delete(sym) : wl.add(sym);
    try {
      const r = await alertsApi.saveSettings({ watchlist: [...wl] });
      setCfg(r);
      setSettingsKey((k) => k + 1);
      load();
    } catch (e) { flash(`Failed: ${e.message || e}`); }
  }
  async function saveSettings(draft) {
    try {
      const r = await alertsApi.saveSettings(draft);
      setCfg(r);
      setSettingsKey((k) => k + 1);
      flash("Settings saved and applied");
      load();
    } catch (e) { flash(`Failed: ${e.message || e}`); }
  }

  const watch = useMemo(() => new Set(cfg?.settings?.watchlist || []), [cfg]);
  const ruleLabel = (r) => cfg?.rule_meta?.[r]?.label || r;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const allOnPage = data?.results?.length > 0 && data.results.every((a) => selected.has(a.id));

  const card = (label, value, sub, color, onClick, active) => (
    <div className="kpi" onClick={onClick} style={{ cursor: "pointer", outline: active ? "1px solid var(--cyan)" : "none" }}>
      <label>{label}</label>
      <div className="val" style={{ color }}>{value ?? "—"}</div>
      <div className="sub">{sub}</div>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 10, letterSpacing: "0.08em", color: "var(--muted)" }}>ALERT CENTRE</div>
            <h2 style={{ fontSize: 18, margin: "6px 0" }}>What needs attention</h2>
            <p style={{ color: "var(--muted)", fontSize: 12, maxWidth: 680, margin: 0 }}>
              Standing risk conditions and changes between data snapshots. Triage each alert, add notes, snooze or resolve it, and ask the AI what to do.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}>
            <button className="btn" onClick={refreshData} disabled={refreshing}>{refreshing ? "Refreshing…" : "↻ Refresh data"}</button>
            <button className="btn" onClick={() => window.open(alertsApi.exportUrl({ ...filters }), "_blank")}>⬇ Export CSV</button>
          </div>
        </div>
        {summary && (
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 10 }}>
            Last evaluated {ago(summary.last_run?.ran_at)} · {summary.snapshots} data snapshot(s) · latest data {fmtDate(summary.last_snapshot_at)}
          </div>
        )}
        <div className="tabs" style={{ marginTop: 12 }}>
          <button className={tab === "alerts" ? "on" : ""} onClick={() => setTab("alerts")}>Alerts</button>
          <button className={tab === "settings" ? "on" : ""} onClick={() => setTab("settings")}>Rules, watchlist and notifications</button>
        </div>
      </div>

      {toast && (
        <div className="panel" style={{ borderColor: "var(--cyan)", fontSize: 13 }}>{toast}</div>
      )}
      {error && <div className="panel" style={{ color: "var(--red)" }}>Failed to load alerts: {error}. Is the API running on port 8000?</div>}

      {tab === "settings" ? (
        cfg ? (
          <Settings
            key={settingsKey} cfg={cfg} companies={companies} onSave={saveSettings}
            onTest={async () => { try { return await alertsApi.testNotify(); } catch (e) { return { slack: String(e.message || e), email: "" }; } }}
          />
        ) : <div className="panel">Loading settings…</div>
      ) : (
        <>
          {summary?.baseline_only && (
            <div className="panel" style={{ fontSize: 13 }}>
              <b>Baseline recorded.</b> Alerts below reflect current conditions. Change alerts (tier worsens, score jumps, new violations) appear once your data files change and you press “Refresh data” (or the scheduled check runs). Scores come from your CSV pipeline, so they only change when you re-run it.
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
            {card("Open", summary?.open, "NEW + ACKNOWLEDGED", undefined, () => setF({ state: "open", severity: "" }), filters.state === "open" && !filters.severity)}
            {card("Unreviewed", summary?.new, "NEED TRIAGE", "#2ee6a8", () => setF({ state: "new", severity: "" }), filters.state === "new")}
            {card("Critical", summary?.by_severity?.critical, "OPEN", SEV.critical.c, () => setF({ state: "open", severity: "critical" }), filters.severity === "critical")}
            {card("High", summary?.by_severity?.high, "OPEN", SEV.high.c, () => setF({ state: "open", severity: "high" }), filters.severity === "high")}
            {card("Snoozed", summary?.snoozed, "PAUSED", undefined, () => setF({ state: "snoozed", severity: "" }), filters.state === "snoozed")}
            {card("Resolved", summary?.resolved, "ALL TIME", undefined, () => setF({ state: "resolved", severity: "" }), filters.state === "resolved")}
          </div>

          <div className="panel">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              {STATE_TABS.map(([k, l]) => (
                <button key={k} className={`btn ${filters.state === k ? "primary" : ""}`} onClick={() => setF({ state: k })}>{l}</button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="Search company, ticker or text…" style={{ ...sel, width: 240 }} />
              <select style={sel} value={filters.severity} onChange={(e) => setF({ severity: e.target.value })}>
                <option value="">All severities</option>
                {Object.keys(SEV).reverse().map((s) => <option key={s} value={s}>{SEV[s].label}</option>)}
              </select>
              <select style={sel} value={filters.rule} onChange={(e) => setF({ rule: e.target.value })}>
                <option value="">All rules</option>
                {(data?.facets?.rules || []).map((r) => <option key={r} value={r}>{ruleLabel(r)}</option>)}
              </select>
              <select style={sel} value={filters.sector} onChange={(e) => setF({ sector: e.target.value })}>
                <option value="">All sectors</option>
                {(data?.facets?.sectors || []).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select style={sel} value={filters.sort} onChange={(e) => setF({ sort: e.target.value })}>
                <option value="severity">Sort: severity</option>
                <option value="recent">Sort: most recent</option>
                <option value="score">Sort: risk score</option>
              </select>
              <label style={{ fontSize: 13 }}>
                <input type="checkbox" checked={filters.watchlist} onChange={(e) => setF({ watchlist: e.target.checked })} /> Watchlist only
              </label>
              {loading && <span className="muted sm">updating…</span>}
            </div>
          </div>

          {selected.size > 0 && (
            <div className="panel" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <b style={{ fontSize: 13 }}>{selected.size} selected</b>
              <button className="btn primary" onClick={() => bulk("ack")}>Acknowledge</button>
              <button className="btn" onClick={() => bulk("snooze", 7)}>Snooze 7 days</button>
              <button className="btn" onClick={() => bulk("resolve")}>Resolve</button>
              <button className="btn" onClick={() => setSelected(new Set())}>Clear</button>
            </div>
          )}

          <div className="panel">
            {!data ? (
              <div className="muted">Loading alerts…</div>
            ) : data.results.length === 0 ? (
              <div style={{ padding: "24px 8px", textAlign: "center" }}>
                <div style={{ fontSize: 15, marginBottom: 6 }}>No alerts match these filters</div>
                <div className="muted sm">
                  {filters.state === "open" && !filters.q && !filters.severity && !filters.rule && !filters.sector && !filters.watchlist
                    ? "Nothing needs attention right now. Adjust thresholds under “Rules, watchlist and notifications” if you expected more."
                    : "Try clearing a filter."}
                </div>
              </div>
            ) : (
              <div className="tscroll">
                <table className="dtable">
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}>
                        <input type="checkbox" checked={allOnPage} onChange={(e) => setSelected(e.target.checked ? new Set(data.results.map((a) => a.id)) : new Set())} />
                      </th>
                      <th>Severity</th><th>Alert</th><th className="r">Score</th><th>Rule</th><th>State</th><th>Raised</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((a) => (
                      <tr key={a.id} className="clickable" onClick={() => openDetail(a.id)} style={{ cursor: "pointer" }}>
                        <td onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox" checked={selected.has(a.id)}
                            onChange={(e) => setSelected((s) => { const n = new Set(s); e.target.checked ? n.add(a.id) : n.delete(a.id); return n; })}
                          />
                        </td>
                        <td><SevChip sev={a.severity} /></td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{a.title}</div>
                          <div className="muted sm"><b style={{ color: "var(--text)" }}>{a.symbol}</b> · {a.sector}{a.note ? " · 📝 note" : ""}</div>
                        </td>
                        <td className="r">{a.score != null ? Number(a.score).toFixed(1) : "—"}<div className="muted sm">{a.tier}</div></td>
                        <td className="muted">{ruleLabel(a.rule)}<div className="sm">{a.kind === "change" ? "change" : "standing"}</div></td>
                        <td><StateChip a={a} /></td>
                        <td className="muted" title={fmtDate(a.first_seen)}>{ago(a.first_seen)}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <button
                            title={watch.has(a.symbol) ? "Remove from watchlist" : "Add to watchlist"}
                            style={{ background: "none", border: 0, cursor: "pointer", fontSize: 16, color: watch.has(a.symbol) ? "#f5c542" : "var(--muted)" }}
                            onClick={() => toggleWatch(a.symbol)}
                          >
                            {watch.has(a.symbol) ? "★" : "☆"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data && data.total > data.page_size && (
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10 }}>
                <button className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</button>
                <span className="muted sm">Page {page} of {totalPages} · {data.total} alerts</span>
                <button className="btn" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next →</button>
              </div>
            )}
          </div>
        </>
      )}

      {openId && (
        <Detail id={openId} reloadKey={detailKey} onClose={closeDetail} onAct={act} cfg={cfg} onToggleWatch={toggleWatch} />
      )}
    </div>
  );
}