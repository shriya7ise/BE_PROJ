import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchFinancials, sendChat } from "../api";

/* =====================================================================
   Company detection, used for the instant "Focused on" chip.
   The server runs the same detection, so both stay in step.
   ===================================================================== */
const TRAILING = new Set([
  "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
  "holdings", "holding", "group", "com", "llc", "lp", "sa", "nv", "ag", "class", "cl", "a", "b", "and", "the",
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

function detect(text, index) {
  const nt = norm(text);
  const padded = ` ${nt} `;
  const words = nt.split(" ").filter(Boolean);
  const found = new Map();
  const add = (c, score, pos) => {
    const prev = found.get(c.symbol);
    if (!prev || score > prev.score) found.set(c.symbol, { ...c, score, pos });
  };

  for (const c of index) {
    if (c.core.length < 3 && !/\d/.test(c.core)) continue;
    const pos = padded.indexOf(` ${c.core} `);
    if (pos >= 0) add(c, c.core.length, pos);
  }

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
    if (c && (TICKER_CUES.has(words[i - 1]) || TICKER_CUES.has(words[i + 1]))) add(c, 90, i);
  });

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
   Personalisation (the server turns these into instructions)
   ===================================================================== */
const ROLES = ["Risk analyst", "Executive", "Safety / EHS manager", "Investor"];
const STYLES = ["Concise", "Detailed"];
function loadPref(key, fallback, allowed) {
  try {
    const v = localStorage.getItem(key);
    return v && allowed.includes(v) ? v : fallback;
  } catch { return fallback; }
}
function savePref(key, v) {
  try { localStorage.setItem(key, v); } catch { /* ignore */ }
}

/* =====================================================================
   Lightweight rich text (bold, headings, bullets, numbered lists)
   ===================================================================== */
function inline(text) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p
  );
}
function Rich({ text }) {
  const out = [];
  let list = null;
  const flush = () => {
    if (list) {
      const Tag = list.ordered ? "ol" : "ul";
      out.push(<Tag key={`l${out.length}`} style={{ margin: "6px 0 6px 20px", padding: 0 }}>{list.items}</Tag>);
      list = null;
    }
  };
  String(text).split("\n").forEach((ln, i) => {
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

const INTRO = {
  role: "assistant",
  text:
    "I'm your ESG risk analyst. Mention a company by name or ticker (for example “Dollar Tree” or “DLTR”) and I'll use its ESG study, financials, signals, model reasoning and open alerts. I can explain why a score is what it is, recommend measurable actions, compare companies, summarise your alerts, and answer general ESG, OSHA and finance questions.",
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
  const [role, setRole] = useState(() => loadPref("vig.role", "Risk analyst", ROLES));
  const [style, setStyle] = useState(() => loadPref("vig.style", "Concise", STYLES));
  const endRef = useRef(null);
  const askedRef = useRef(false);

  useEffect(() => {
    fetchFinancials(500).then((d) => setCompanies(d.results || [])).catch(() => setCompanies([]));
  }, []);

  const index = useMemo(
    () =>
      companies.filter((r) => r.symbol).map((r) => ({
        symbol: r.symbol,
        name: r.canonical_name || r.symbol,
        core: coreName(r.canonical_name || r.symbol),
      })),
    [companies]
  );
  const company = useMemo(() => index.find((c) => c.symbol === symbol), [index, symbol]);
  const label = company?.name || symbol;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const quick = symbol
    ? [
        `Why is ${label}'s risk score what it is?`,
        `Recommend measurable actions for ${label}`,
        `What alerts are open for ${symbol} and what should we do?`,
        `How does ${symbol}'s financial health compare with peers?`,
        `Brief me on ${label} in 5 bullets`,
      ]
    : [
        "Tell me about Dollar Tree",
        "Which companies have the highest ESG risk?",
        "What are my most urgent open alerts?",
        "Which sector is riskiest and why?",
        "Explain how the composite risk score works",
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
      const history = prior.filter((m) => m !== INTRO).slice(-8).map((m) => ({ role: m.role, text: m.text }));
      const data = await sendChat(text, sym || null, { history, role, style });
      if (data.symbol && data.symbol !== sym) setParams({ symbol: data.symbol }, { replace: true });
      const out = [{ role: "assistant", text: data.reply || JSON.stringify(data) }];
      if (data.also_named?.length) {
        out.push({
          role: "assistant",
          text: `Note: full detail was loaded for ${data.symbol}. For ${data.also_named.join(", ")} I used summary data; ask about them separately for the same depth.`,
        });
      }
      setMessages((m) => [...m, ...out]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Error: ${friendlyError(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  // deep link from the Alerts page: /chat?symbol=DLTR&ask=...
  useEffect(() => {
    const ask = params.get("ask");
    if (ask && !askedRef.current) {
      askedRef.current = true;
      const next = new URLSearchParams(params);
      next.delete("ask");
      setParams(next, { replace: true });
      send(ask);
    }
    // eslint-disable-next-line
  }, []);

  return (
    <div className="chat-layout">
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ fontSize: 18, marginBottom: 8 }}>AI Chat</h2>
          <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "var(--muted)" }}>
            <label>Answer as for</label>
            <select style={selStyle} value={role} onChange={(e) => { setRole(e.target.value); savePref("vig.role", e.target.value); }}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
            <select style={selStyle} value={style} onChange={(e) => { setStyle(e.target.value); savePref("vig.style", e.target.value); }}>
              {STYLES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <button className="btn" type="button" onClick={() => setMessages([INTRO])}>Clear chat</button>
          </div>
        </div>
        {symbol ? (
          <div className="chat-context">
            Focused on: <strong>{label}</strong> ({symbol})
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