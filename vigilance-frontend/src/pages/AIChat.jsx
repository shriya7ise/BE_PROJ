import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  API,
  fetchCompanySignals,
  fetchEsg,
  fetchFinancialStudy,
  fetchFinancials,
  fetchReasoning,
  sendChat,
} from "../api";

/* =====================================================================
   Company detection (names, tickers, light typo tolerance)
   ===================================================================== */
const TRAILING = new Set([
  "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
  "holdings", "holding", "group", "com", "llc", "lp", "sa", "nv", "ag", "class", "cl", "a", "b",
]);
const NOT_TICKERS = new Set([
  "ESG", "OSHA", "AI", "API", "CEO", "CFO", "USA", "US", "UK", "EU", "GDP", "ETF", "IPO",
  "PE", "ROE", "ROI", "FAQ", "PDF", "AND", "THE", "FOR", "ARE", "WHAT", "WHY", "HOW",
]);
const COMMON_WORDS = new Set([
  "all", "now", "are", "can", "has", "was", "one", "any", "new", "see", "key", "low", "run",
  "big", "well", "real", "good", "best", "top", "for", "the", "and",
]);
const TICKER_CUES = new Set(["company", "details", "detail", "stock", "ticker", "about", "risk", "esg", "score"]);

const norm = (s) =>
  String(s || "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();

function coreName(name) {
  const t = norm(name).split(" ").filter(Boolean);
  if (t[0] === "the" && t.length > 1) t.shift();
  while (t.length > 1 && TRAILING.has(t[t.length - 1])) t.pop();
  return t.join(" ");
}

function lev(a, b) {
  const m = a.length, n = b.length;
  if (Math.abs(m - n) > 1) return 2;
  const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 0; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return d[m][n];
}

/* distinct matched companies, best first */
function detect(text, index) {
  const nt = norm(text);
  const padded = ` ${nt} `;
  const words = nt.split(" ").filter(Boolean);
  const found = new Map();
  const add = (c, score, pos) => {
    const prev = found.get(c.symbol);
    if (!prev || score > prev.score) found.set(c.symbol, { ...c, score, pos });
  };

  // full or core name ("dollar tree", "Dollar Tree Inc")
  for (const c of index) {
    if (c.core.length < 3 && !/\d/.test(c.core)) continue;
    const pos = padded.indexOf(` ${c.core} `);
    if (pos >= 0) add(c, c.core.length, pos);
  }

  // tickers: UPPERCASE word, $tsla, or lowercase next to a cue word ("lly company details")
  const bySymbol = new Map(index.map((c) => [c.symbol.toUpperCase(), c]));
  const re = /\$([A-Za-z]{1,5}(?:[.-][A-Za-z])?)\b|\b([A-Z]{2,5}(?:[.-][A-Z])?)\b/g;
  let m;
  while ((m = re.exec(text))) {
    const tk = (m[1] || m[2]).toUpperCase();
    if (m[2] && NOT_TICKERS.has(tk)) continue;
    const c = bySymbol.get(tk);
    if (c) add(c, 100, m.index);
  }
  words.forEach((w, i) => {
    if (w.length < 3 || COMMON_WORDS.has(w)) return;
    const c = bySymbol.get(w.toUpperCase());
    if (!c) return;
    if (TICKER_CUES.has(words[i - 1]) || TICKER_CUES.has(words[i + 1])) add(c, 90, i);
  });

  // typo tolerance on single-word company names ("walmrat" -> Walmart)
  if (!found.size) {
    for (const w of words) {
      if (w.length < 5) continue;
      for (const c of index) {
        if (c.core.includes(" ") || c.core.length < 5 || c.core[0] !== w[0]) continue;
        if (lev(w, c.core) <= 1) add(c, 3, 0);
      }
    }
  }
  return [...found.values()].sort((a, b) => b.score - a.score || a.pos - b.pos);
}

/* =====================================================================
   Context builders
   ===================================================================== */
const SKIP_KEYS = new Set(["series", "drawdown", "rolling_vol", "embedding", "embeddings"]);

function compact(v, depth = 0) {
  if (v == null) return v;
  if (depth > 7) return "…";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? Math.round(v) : Math.round(v * 1000) / 1000;
  if (typeof v === "string") return v.length > 400 ? `${v.slice(0, 400)}…` : v;
  if (Array.isArray(v)) {
    const lim = depth <= 1 ? 14 : 6;
    const out = v.slice(0, lim).map((x) => compact(x, depth + 1));
    if (v.length > lim) out.push(`…(+${v.length - lim} more)`);
    return out;
  }
  if (typeof v === "object") {
    const o = {};
    for (const [k, val] of Object.entries(v)) if (!SKIP_KEYS.has(k)) o[k] = compact(val, depth + 1);
    return o;
  }
  return v;
}
const clip = (s, n) => (s.length > n ? `${s.slice(0, n)}…[truncated]` : s);

function registerContext(reg, hits) {
  const rows = reg.filter((r) => r.composite_score != null).sort((a, b) => b.composite_score - a.composite_score);
  const line = (r, i) =>
    `${i != null ? `${i + 1}. ` : "- "}${r.symbol} (${r.canonical_name}), sector ${r.gics_sector || "n/a"}, ` +
    `score ${r.composite_score}, tier ${r.risk_tier}, status ${r.status || "n/a"}`;
  const tiers = {};
  const sectors = {};
  rows.forEach((r) => {
    const t = r.risk_tier || "Unknown";
    tiers[t] = (tiers[t] || 0) + 1;
    const sc = r.gics_sector || "Unknown";
    if (!sectors[sc]) sectors[sc] = { n: 0, sum: 0, crit: 0 };
    sectors[sc].n += 1;
    sectors[sc].sum += r.composite_score;
    if (r.risk_tier === "Critical") sectors[sc].crit += 1;
  });
  const estimated = rows.filter((r) => r.score_is_estimated).length;
  const parts = [
    `Companies covered: ${rows.length}. By tier: ${Object.entries(tiers).map(([k, v]) => `${k} ${v}`).join(", ")}. Estimated scores: ${estimated}.`,
    `Top 15 by composite risk score:\n${rows.slice(0, 15).map((r, i) => line(r, i)).join("\n")}`,
    `Lowest 5:\n${rows.slice(-5).reverse().map((r) => line(r)).join("\n")}`,
    `Sectors by average score:\n${Object.entries(sectors)
      .sort((a, b) => b[1].sum / b[1].n - a[1].sum / a[1].n)
      .map(([k, v]) => `- ${k}: avg ${(v.sum / v.n).toFixed(1)} (${v.n} companies, ${v.crit} critical)`)
      .join("\n")}`,
  ];
  const named = hits.map((h) => rows.find((r) => r.symbol === h.symbol)).filter(Boolean);
  if (named.length) {
    const rank = (r) => rows.findIndex((x) => x.symbol === r.symbol) + 1;
    parts.push(`Companies named in the question:\n${named.map((r) => `${line(r)} (rank ${rank(r)} of ${rows.length})`).join("\n")}`);
  }
  return parts.join("\n\n");
}

function friendlyError(e) {
  let msg = String(e?.message || e);
  try {
    const j = JSON.parse(msg);
    msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
  } catch { /* not JSON */ }
  if (/GEMINI_API_KEY/i.test(msg)) return "The AI service isn't configured yet: the server is missing its API key.";
  if (/failed to fetch|networkerror|load failed/i.test(msg)) return "I can't reach the API on port 8000. Is the backend running?";
  return msg;
}

/* =====================================================================
   Personalisation
   ===================================================================== */
const ROLES = {
  "Risk analyst": "a risk analyst who wants evidence, drivers and the reasoning behind each score",
  "Executive": "a senior executive who wants the bottom line, business impact and decisions to make",
  "Safety / EHS manager": "a workplace-safety (EHS) manager who wants OSHA-related causes and concrete corrective actions",
  "Investor": "an investor who wants financial materiality, downside risk and how peers compare",
};
const STYLES = {
  Concise: "Keep answers short: under 150 words, using tight bullets.",
  Detailed: "Give a thorough answer with clear sections: Answer, Reasoning, Evidence, Recommendations.",
};
function loadPref(key, fallback, allowed) {
  try {
    const v = localStorage.getItem(key);
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
function savePref(key, v) {
  try { localStorage.setItem(key, v); } catch { /* ignore */ }
}

function buildPrompt({ question, role, style, focusLabel, dossier, register, history }) {
  return [
    `You are "Vigilance Analyst", the assistant inside an ESG-risk and financial-health dashboard. The reader is ${ROLES[role]}.`,
    "RULES:",
    "1. Use the DATA sections below as your primary source and quote the actual figures (scores, tiers, penalties, citations, margins, ranks). Never say a company is missing if it appears in the DATA.",
    "2. Reasoning questions (why, how, explain): walk through the drivers step by step, e.g. composite score, corroboration count, OSHA citations and penalties, escalation status, and financial materiality. Say which facts support each point.",
    "3. Recommendation questions: give measurable actions. For each: the action, KPI/metric, target value, timeframe, owner, and the evidence it addresses. Order by priority.",
    "4. General questions (ESG concepts, OSHA, finance, how scores work, definitions): answer from general knowledge and label that part as general knowledge.",
    "5. If a needed figure is not in the DATA, say so plainly instead of guessing. Mention when a score is marked as estimated. This is analysis for information, not investment or legal advice.",
    `6. ${STYLES[style]}`,
    focusLabel
      ? `\nFOCUSED COMPANY: ${focusLabel}\n\nDATA: COMPANY DOSSIER\n${dossier || "(company detail data could not be loaded; rely on the register below)"}`
      : "\nNo single company is focused.",
    register ? `\nDATA: RISK REGISTER (composite score 0-100, higher = riskier)\n${register}` : "",
    history ? `\nCONVERSATION SO FAR\n${history}` : "",
    `\nUSER QUESTION:\n${question}`,
  ].join("\n");
}

/* =====================================================================
   Lightweight rich-text renderer (bold, bullets, numbered lists)
   ===================================================================== */
function inline(text) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p
  );
}
function Rich({ text }) {
  const lines = String(text).split("\n");
  const out = [];
  let list = null;
  const flush = () => {
    if (list) {
      const Tag = list.ordered ? "ol" : "ul";
      out.push(<Tag key={`l${out.length}`} style={{ margin: "6px 0 6px 20px", padding: 0 }}>{list.items}</Tag>);
      list = null;
    }
  };
  lines.forEach((ln, i) => {
    const mOl = ln.match(/^\s*\d+[.)]\s+(.*)/);
    const mUl = ln.match(/^\s*[-*•]\s+(.*)/);
    const mH = ln.match(/^\s*#{1,4}\s+(.*)/);
    if (mOl || mUl) {
      const ordered = !!mOl;
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push(<li key={i} style={{ marginBottom: 3 }}>{inline((mOl || mUl)[1])}</li>);
    } else {
      flush();
      if (mH) out.push(<div key={i} style={{ fontWeight: 700, margin: "8px 0 2px" }}>{inline(mH[1])}</div>);
      else if (ln.trim()) out.push(<p key={i} style={{ margin: "4px 0" }}>{inline(ln)}</p>);
    }
  });
  flush();
  return <div>{out}</div>;
}

/* =====================================================================
   Page
   ===================================================================== */
const INTRO = {
  role: "assistant",
  text:
    "I'm your ESG risk analyst. Mention a company by name or ticker (for example “Dollar Tree” or “DLTR”) and I'll pull its ESG study, financials, signals and AI reasoning. I can explain why a score is what it is, recommend measurable actions, compare companies, and answer general ESG, OSHA and finance questions.",
};

const selStyle = {
  background: "var(--panel-2)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: "5px 8px",
  fontSize: 12,
};

export default function AIChat() {
  const [params, setParams] = useSearchParams();
  const symbol = params.get("symbol") || "";
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [companies, setCompanies] = useState([]);
  const [messages, setMessages] = useState([INTRO]);
  const [dossierState, setDossierState] = useState("idle"); // idle | loading | ready | none
  const [role, setRole] = useState(() => loadPref("vig.role", "Risk analyst", Object.keys(ROLES)));
  const [style, setStyle] = useState(() => loadPref("vig.style", "Concise", Object.keys(STYLES)));

  const endRef = useRef(null);
  const registerRef = useRef(null);
  const dossierRef = useRef({});

  useEffect(() => {
    fetchFinancials(500).then((d) => setCompanies(d.results || [])).catch(() => setCompanies([]));
  }, []);

  const index = useMemo(
    () =>
      companies
        .filter((r) => r.symbol)
        .map((r) => ({
          symbol: r.symbol,
          name: r.canonical_name || r.symbol,
          core: coreName(r.canonical_name || r.symbol),
        })),
    [companies]
  );
  const company = useMemo(() => index.find((c) => c.symbol === symbol), [index, symbol]);
  const label = company?.name || symbol;

  async function loadRegister() {
    if (registerRef.current) return registerRef.current;
    try {
      const res = await fetch(`${API}/api/companies?limit=500`);
      if (!res.ok) return [];
      const d = await res.json();
      registerRef.current = d.results || [];
      return registerRef.current;
    } catch {
      return [];
    }
  }

  async function loadDossier(sym) {
    if (dossierRef.current[sym]) return dossierRef.current[sym];
    const jobs = [
      ["ESG STUDY", fetchEsg],
      ["FINANCIAL STUDY", fetchFinancialStudy],
      ["SIGNALS", fetchCompanySignals],
      ["AI REASONING", (s) => fetchReasoning(s, false)],
    ];
    const res = await Promise.allSettled(jobs.map(([, fn]) => fn(sym)));
    const parts = res
      .map((r, i) => (r.status === "fulfilled" && r.value ? `### ${jobs[i][0]}\n${clip(JSON.stringify(compact(r.value)), 6500)}` : null))
      .filter(Boolean);
    const text = parts.join("\n\n");
    if (text) dossierRef.current[sym] = text;
    return text;
  }

  // warm the company dossier as soon as a company is focused
  useEffect(() => {
    if (!symbol) { setDossierState("idle"); return; }
    let live = true;
    setDossierState("loading");
    loadDossier(symbol).then((t) => live && setDossierState(t ? "ready" : "none"));
    return () => { live = false; };
    // eslint-disable-next-line
  }, [symbol]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const quick = symbol
    ? [
        `Why is ${label}'s risk score what it is?`,
        `Recommend measurable actions for ${label}`,
        `Explain the OSHA evidence for ${symbol}`,
        `How does ${symbol}'s financial health compare with peers?`,
        `Brief me on ${label} in 5 bullets`,
      ]
    : [
        "Tell me about Dollar Tree",
        "Which companies have the highest ESG risk?",
        "Which sector is riskiest and why?",
        "Explain how the composite risk score works",
        "What is OSHA and why does it matter for ESG?",
      ];

  async function send(override) {
    const text = (override ?? input).trim();
    if (!text || busy) return;
    setInput("");
    const prior = messages;
    setMessages((m) => [...m, { role: "user", text }]);
    setBusy(true);

    const hits = detect(text, index);
    let sym = symbol;
    if (hits.length && hits[0].symbol !== symbol) {
      sym = hits[0].symbol;
      setParams({ symbol: sym }, { replace: true });
    }

    try {
      const [reg, dossier] = await Promise.all([loadRegister(), sym ? loadDossier(sym) : Promise.resolve("")]);
      const focusName = index.find((c) => c.symbol === sym)?.name || sym;
      const history = prior
        .filter((m) => m !== INTRO)
        .slice(-6)
        .map((m) => `${m.role === "user" ? "User" : "Assistant"}: ${clip(m.text, 700)}`)
        .join("\n");

      const prompt = buildPrompt({
        question: text,
        role,
        style,
        focusLabel: sym ? `${focusName} (${sym})` : "",
        dossier,
        register: reg.length ? registerContext(reg, hits.slice(0, 4)) : "",
        history,
      });

      const data = await sendChat(prompt, sym || null);
      const out = [{ role: "assistant", text: data.reply || JSON.stringify(data) }];
      if (hits.length > 1) {
        const others = hits.slice(1, 4).map((h) => `${h.name} (${h.symbol})`).join(", ");
        out.push({
          role: "assistant",
          text: `Note: I loaded the full dossier for ${hits[0].name} only. I used register-level scores for ${others}; ask about them separately for the same depth.`,
        });
      }
      setMessages((m) => [...m, ...out]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Error: ${friendlyError(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-layout">
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ fontSize: 18, marginBottom: 8 }}>AI Chat</h2>
          <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
            <label>Answer as for</label>
            <select style={selStyle} value={role} onChange={(e) => { setRole(e.target.value); savePref("vig.role", e.target.value); }}>
              {Object.keys(ROLES).map((r) => <option key={r}>{r}</option>)}
            </select>
            <select style={selStyle} value={style} onChange={(e) => { setStyle(e.target.value); savePref("vig.style", e.target.value); }}>
              {Object.keys(STYLES).map((s) => <option key={s}>{s}</option>)}
            </select>
            <button className="btn" type="button" onClick={() => setMessages([INTRO])}>Clear chat</button>
          </div>
        </div>
        {symbol ? (
          <div className="chat-context">
            Focused on: <strong>{label}</strong> ({symbol})
            <span style={{ marginLeft: 8, fontSize: 11, color: "var(--muted)" }}>
              {dossierState === "loading" && "loading company data…"}
              {dossierState === "ready" && "company data loaded"}
              {dossierState === "none" && "company detail unavailable, using register only"}
            </span>
            <button
              type="button"
              onClick={() => { const next = new URLSearchParams(params); next.delete("symbol"); setParams(next); }}
              title="Clear context"
            >
              ×
            </button>
          </div>
        ) : (
          <p style={{ color: "var(--muted)", marginBottom: 12 }}>
            No company focused yet. Mention a company or ticker in your question and I'll focus on it automatically.
          </p>
        )}
      </div>

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div className="who">{m.role === "user" ? "You" : "Assistant"}</div>
            {m.role === "assistant" ? <Rich text={m.text} /> : m.text}
          </div>
        ))}
        {busy && (
          <div className="bubble assistant">
            <div className="who">Assistant</div>
            Analysing {symbol ? label : "the register"}…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
        {quick.map((s) => (
          <button key={s} type="button" className="btn" style={{ fontSize: 12 }} onClick={() => send(s)} disabled={busy}>
            {s}
          </button>
        ))}
      </div>

      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask why, what to do, compare companies, or any ESG question…"
          disabled={busy}
        />
        <button className="btn primary" type="button" onClick={() => send()} disabled={busy}>
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}