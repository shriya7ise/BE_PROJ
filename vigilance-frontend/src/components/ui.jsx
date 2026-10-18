import { useState } from "react";
import { reportUrl } from "../api";
import { COL } from "./charts";

/* ---------- formatters ---------- */
export function money(v, d = 2) {
  if (v == null || Number.isNaN(Number(v))) return "n/a";
  const n = Number(v), a = Math.abs(n), s = n < 0 ? "-" : "";
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(d)}T`;
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(d)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(d)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`;
  return `${s}$${a.toFixed(0)}`;
}
export const pct = (v, d = 1) => (v == null ? "n/a" : `${(Number(v) * 100).toFixed(d)}%`);
export const fixed = (v, d = 2) => (v == null ? "n/a" : Number(v).toFixed(d));
export const int = (v) => (v == null ? "n/a" : Math.round(Number(v)).toLocaleString());
export function ordinal(n) {
  if (n == null) return "n/a";
  const k = Math.round(n), m = k % 100;
  const suf = m >= 11 && m <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[k % 10] || "th";
  return `${k}${suf}`;
}
export function metric(v, kind) {
  if (v == null) return "n/a";
  if (kind === "pct") return pct(v);
  if (kind === "pp") return `${Number(v).toFixed(0)}%`;
  return `${Number(v).toFixed(2)}x`;
}
export const tierColor = (t) => ({ Critical: COL.red, Watchlist: COL.amber, Neutral: COL.grey, Stable: COL.green }[t] || COL.mute);
export const sevColor = (s) => (s >= 9 ? COL.red : s >= 7 ? COL.orange : s >= 5 ? COL.amber : COL.mute);

/* ---------- layout bits ---------- */
export function Section({ title, sub, children, right, id }) {
  return (
    <section className="panel sec" id={id}>
      <div className="panel-h">
        <div>
          <h3 style={{ textTransform: "none", letterSpacing: 0, fontSize: 15, color: "var(--text)" }}>{title}</h3>
          {sub && <p className="sec-sub">{sub}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function Kpis({ items }) {
  return (
    <div className="kpi-row k5">
      {items.map((k) => (
        <div className="kpi" key={k.label} title={k.hint}>
          <label>{k.label}</label>
          <div className="val" style={{ color: k.color }}>{k.value}</div>
          {k.sub && <div className="sub">{k.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function Narrative({ sections, open = true }) {
  return (
    <div className="narr">
      {sections.map((s) => (
        <div key={s.title} className="narr-item">
          <div className="narr-t">{s.title}</div>
          <p>{s.text}</p>
        </div>
      ))}
    </div>
  );
}

export function Callout({ children, color = COL.teal }) {
  return <div className="callout" style={{ borderLeftColor: color }}>{children}</div>;
}

export function Chip({ children, color }) {
  return <span className="chip" style={{ color, borderColor: color }}>{children}</span>;
}

export function Skeleton({ label = "Loading…" }) {
  return (
    <div className="panel skeleton">
      <div className="sk-line w60" /><div className="sk-line w90" /><div className="sk-line w75" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  return (
    <div className="panel" style={{ borderColor: "#5a2030", color: "var(--red)" }}>
      Failed to load: {error}
      <div style={{ color: "var(--muted)", marginTop: 8 }}>
        Is the API running on http://127.0.0.1:8000? Check the uvicorn terminal for the traceback.
      </div>
      {onRetry && <button className="btn" style={{ marginTop: 10 }} onClick={onRetry}>Retry</button>}
    </div>
  );
}

/* ---------- PDF download ---------- */
export function ExportButton({ symbol, kind, label }) {
  const [state, setState] = useState("idle");
  const [err, setErr] = useState("");
  async function go() {
    setState("working"); setErr("");
    try {
      const res = await fetch(reportUrl(symbol, kind));
      if (!res.ok) {
        let msg = res.statusText;
        try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${symbol}_${kind}_report.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      setState("done");
      setTimeout(() => setState("idle"), 2500);
    } catch (e) {
      setErr(String(e.message || e)); setState("error");
    }
  }
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-end" }}>
      <button className="btn primary" type="button" onClick={go} disabled={state === "working"}>
        {state === "working" ? "Generating PDF…" : state === "done" ? "✓ Downloaded" : `⬇ ${label}`}
      </button>
      {state === "error" && <small style={{ color: "var(--red)", maxWidth: 280, textAlign: "right", marginTop: 4 }}>{err}</small>}
    </span>
  );
}
