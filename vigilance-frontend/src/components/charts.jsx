import { useEffect, useRef, useState } from "react";

/* Dependency-free SVG charts styled for the Vigilance dark theme. */
export const COL = {
  teal: "#2ee6a8",
  red: "#ff5c7a",
  amber: "#f5c542",
  green: "#3dd68c",
  grey: "#6b7280",
  blue: "#5aa9ff",
  orange: "#ff8a4c",
  mute: "#8b93a7",
  grid: "#1e2430",
  text: "#e8eaed",
};

function nice(max) {
  if (max <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(max)));
  const f = max / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

const short = (n) => {
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
};

/* ---------- Column chart ---------- */
export function ComboChart({
  labels,
  bars,
  barLabel = "Value",
  barColor = COL.teal,
  barFmt = short,
  lines = [],
  height = 230,
  yFmt,
  signed = false,
}) {
  const [hover, setHover] = useState(null);
  const W = 640,
    H = height,
    L = 46,
    R = lines.length ? 40 : 12,
    T = 14,
    B = 26;
  const n = labels.length;
  if (!n) return <Empty />;

  const bmax = nice(Math.max(...bars, 0));
  const bmin = signed ? -nice(Math.abs(Math.min(...bars, 0))) : 0;
  const lmax = lines.length ? nice(Math.max(...lines.flatMap((l) => l.values), 1)) : 1;

  const iw = W - L - R,
    ih = H - T - B;
  const y = (v) => T + ih - ((v - bmin) / (bmax - bmin || 1)) * ih;
  const yl = (v) => T + ih - (v / lmax) * ih;
  const bw = iw / n;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => bmin + (bmax - bmin) * t);
  const fmt = yFmt || barFmt;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" onMouseLeave={() => setHover(null)}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke={COL.grid} />
          <text x={L - 6} y={y(t) + 3} fontSize="9" fill={COL.mute} textAnchor="end">
            {fmt(t)}
          </text>
        </g>
      ))}
      {lines.length > 0 &&
        [0, 0.5, 1].map((t, i) => (
          <text key={i} x={W - R + 6} y={yl(lmax * t) + 3} fontSize="9" fill={COL.mute}>
            {short(lmax * t)}
          </text>
        ))}
      {bars.map((v, i) => (
        <rect
          key={i}
          x={L + i * bw + bw * 0.18}
          width={bw * 0.64}
          y={Math.min(y(v), y(0))}
          height={Math.abs(y(v) - y(0))}
          fill={
            Array.isArray(barColor)
              ? barColor[i]
              : signed && v < 0
              ? COL.red
              : barColor
          }
          opacity={hover === i ? 1 : 0.85}
          rx="2"
        />
      ))}
      {lines.map((ln, i) => (
        <g key={i}>
          <polyline
            fill="none"
            stroke={ln.color}
            strokeWidth="2"
            strokeDasharray={ln.dash}
            points={ln.values.map((v, ii) => `${L + ii * bw + bw / 2},${yl(v)}`).join(" ")}
          />
          {ln.values.map((v, ii) => (
            <circle key={ii} cx={L + ii * bw + bw / 2} cy={yl(v)} r="2.6" fill={ln.color} />
          ))}
        </g>
      ))}
      {labels.map((l, i) => (
        (n <= 14 || i % Math.ceil(n / 14) === 0) && (
          <text
            key={i}
            x={L + i * bw + bw / 2}
            y={H - 8}
            fontSize="9"
            fill={COL.mute}
            textAnchor="middle"
          >
            {l}
          </text>
        )
      ))}
      {labels.map((_, i) => (
        <rect
          key={i}
          x={L + i * bw}
          y={T}
          width={bw}
          height={ih}
          fill="transparent"
          onMouseEnter={() => setHover(i)}
        />
      ))}
      {hover != null && (() => {
        const tx = Math.min(Math.max(L + hover * bw + bw / 2, L + 70), W - R - 70);
        const rows = [
          [barLabel, barFmt(bars[hover]), barColor && !Array.isArray(barColor) ? barColor : COL.teal],
          ...lines.map((l) => [l.label, l.fmt ? l.fmt(l.values[hover]) : short(l.values[hover]), l.color]),
        ];
        return (
          <g pointerEvents="none">
            <rect x={tx - 68} y={T} width="136" height={16 + rows.length * 13} rx="5" fill="#0b0d11" stroke="#2a3344" />
            <text x={tx} y={T + 12} fontSize="10" fontWeight="600" fill={COL.text} textAnchor="middle">
              {labels[hover]}
            </text>
            {rows.map((r, i) => (
              <g key={i}>
                <circle cx={tx - 58} cy={T + 22 + i * 13} r="3" fill={r[2]} />
                <text x={tx - 51} y={T + 25 + i * 13} fontSize="9.5" fill={COL.mute}>
                  {r[0]}
                </text>
                <text x={tx + 62} y={T + 25 + i * 13} fontSize="9.5" fill={COL.text} textAnchor="end">
                  {r[1]}
                </text>
              </g>
            ))}
          </g>
        );
      })()}
    </svg>
  );
}

/* ---------- Line / area chart ---------- */
export function LineChart({
  data,
  color = COL.teal,
  height = 240,
  area = true,
  yFmt = short,
  xFmt,
  baseline,
  negativeFill = false,
}) {
  const ref = useRef(null);
  const [hover, setHover] = useState(null);
  if (!data || data.length < 2) return <Empty />;

  const W = 640,
    H = height,
    L = 48,
    R = 12,
    T = 12,
    B = 24;
  const ys = data.map((d) => d.y);
  let lo = Math.min(...ys, baseline ?? Infinity),
    hi = Math.max(...ys, baseline ?? -Infinity);
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad;
  hi += pad;

  const iw = W - L - R,
    ih = H - T - B;
  const px = (i) => L + (i / (data.length - 1)) * iw;
  const py = (v) => T + ih - ((v - lo) / (hi - lo)) * ih;

  const path = data.map((d, i) => `${i ? "L" : "M"}${px(i).toFixed(1)},${py(d.y).toFixed(1)}`).join(" ");

  const base = baseline != null ? py(baseline) : T + ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => lo + (hi - lo) * t);
  const xt = [0, 0.25, 0.5, 0.75, 1].map((t) => Math.round(t * (data.length - 1)));
  const fx = xFmt || ((x) => String(x).slice(0, 7));

  function move(e) {
    if (!ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(data.length - 1, Math.round(((rel - L) / iw) * (data.length - 1)))));
  }

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="chart" onMouseMove={move} onMouseLeave={() => setHover(null)}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={L} x2={W - R} y1={py(t)} y2={py(t)} stroke={COL.grid} />
          <text x={L - 6} y={py(t) + 3} fontSize="9" fill={COL.mute} textAnchor="end">
            {yFmt(t)}
          </text>
        </g>
      ))}
      {baseline != null && <line x1={L} x2={W - R} y1={base} y2={base} stroke="#3a4458" strokeDasharray="3 3" />}
      {area && <path d={`${path} L${px(data.length - 1)},${base} L${px(0)},${base} Z`} fill={color} opacity="0.13" />}
      <path d={path} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" />
      {xt.map((i) => (
        <text key={i} x={px(i)} y={H - 6} fontSize="9" fill={COL.mute} textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}>
          {fx(data[i].x)}
        </text>
      ))}
      {hover != null && data[hover] && (
        <g pointerEvents="none">
          <line x1={px(hover)} x2={px(hover)} y1={T} y2={T + ih} stroke="#3a4458" />
          <circle cx={px(hover)} cy={py(data[hover].y)} r="4" fill={color} stroke="#0b0d11" strokeWidth="2" />
          <g transform={`translate(${Math.min(Math.max(px(hover), L + 60), W - R - 60)},${T + 4})`}>
            <rect x="-58" width="116" height="32" rx="5" fill="#0b0d11" stroke="#2a3344" />
            <text y="13" fontSize="9.5" fill={COL.mute} textAnchor="middle">{data[hover].x}</text>
            <text y="26" fontSize="11" fontWeight="600" fill={COL.text} textAnchor="middle">
              {yFmt(data[hover].y)}
            </text>
          </g>
        </g>
      )}
    </svg>
  );
}

/* ---------- Donut ---------- */
export function Donut({ parts, center, sub, size = 150 }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  let acc = 0;
  const r = 52,
    c = 2 * Math.PI * r;

  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 140 140" width={size} height={size}>
        <circle cx="70" cy="70" r={r} fill="none" stroke={COL.grid} strokeWidth="18" />
        {parts.map((p, i) => {
          const len = (p.value / total) * c;
          const el = (
            <circle
              key={i}
              cx="70"
              cy="70"
              r={r}
              fill="none"
              stroke={p.color}
              strokeWidth="18"
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-acc}
              transform="rotate(-90 70 70)"
            >
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
          acc += len;
          return el;
        })}
        <text x="70" y="68" textAnchor="middle" fontSize="19" fontWeight="700" fill={COL.text}>
          {center}
        </text>
        {sub && <text x="70" y="83" textAnchor="middle" fontSize="8.5" fill={COL.mute}>{sub}</text>}
      </svg>
      <div className="legend">
        {parts.map((p) => (
          <div key={p.label}>
            <i style={{ background: p.color }} />
            {p.label}
            <b>{p.display ?? p.value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Gauge ---------- */
export function Gauge({ value, label, color }) {
  const a = (v) => Math.PI * (1 - v / 100);
  const pt = (v, r) => [70 + r * Math.cos(a(v)), 70 - r * Math.sin(a(v))];
  const arc = (v0, v1, col) => {
    const [x0, y0] = pt(v0, 56);
    const [x1, y1] = pt(v1, 56);
    return <path key={v0} d={`M${x0},${y0} A56,56 0 0 1 ${x1},${y1}`} stroke={col} strokeWidth="13" fill="none" />;
  };
  const [nx, ny] = pt(Math.max(0, Math.min(100, value)), 42);
  return (
    <svg viewBox="0 0 140 92" width="190">
      {arc(0, 20, COL.green)}
      {arc(20, 40, "#7fcfa3")}
      {arc(40, 70, COL.amber)}
      {arc(70, 100, COL.red)}
      <line x1="70" y1="70" x2={nx} y2={ny} stroke={COL.text} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="70" cy="70" r="4.5" fill={COL.text} />
      <text x="70" y="88" textAnchor="middle" fontSize="15" fontWeight="700" fill={color || COL.text}>
        {Number(value).toFixed(0)}
      </text>
      {label && <text x="70" y="12" textAnchor="middle" fontSize="0">{label}</text>}
    </svg>
  );
}

/* ---------- Radar ---------- */
export function Radar({ axes, series, size = 300 }) {
  const n = axes.length;
  if (n < 3) return <Empty />;
  const cx = 150,
    cy = 150,
    R = 100;
  const pt = (i, v) => {
    const a = -Math.PI / 2 + (i / n) * 2 * Math.PI;
    return [cx + (R * v / 100) * Math.cos(a), cy + (R * v / 100) * Math.sin(a)];
  };
  return (
    <div>
      <svg viewBox="0 0 300 300" width="100%" style={{ maxWidth: size }}>
        {[25, 50, 75, 100].map((r) => (
          <polygon
            key={r}
            fill="none"
            stroke={COL.grid}
            points={axes.map((_, i) => pt(i, r).join(",")).join(" ")}
          />
        ))}
        {axes.map((a, i) => {
          const [x, y] = pt(i, 100);
          const [lx, ly] = pt(i, 118);
          return (
            <g key={a}>
              <line x1={cx} y1={cy} x2={x} y2={y} stroke={COL.grid} />
              <text x={lx} y={ly + 3} fontSize="10" fill={COL.mute} textAnchor={lx < cx - 5 ? "end" : lx > cx + 5 ? "start" : "middle"}>
                {a}
              </text>
            </g>
          );
        })}
        {series.map((s) => (
          <g key={s.name}>
            <polygon
              points={s.values.map((v, i) => pt(i, v ?? 0).join(",")).join(" ")}
              fill={s.color}
              fillOpacity="0.18"
              stroke={s.color}
              strokeWidth="2"
              strokeDasharray={s.dash}
            />
            {s.values.map((v, i) => {
              const [x, y] = pt(i, v ?? 0);
              return <circle key={i} cx={x} cy={y} r="3" fill={s.color} />;
            })}
          </g>
        ))}
      </svg>
      <div className="legend row">
        {series.map((s) => (
          <div key={s.name}>
            <i style={{ background: s.color }} />
            {s.name}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- Horizontal bars ---------- */
export function HBar({ rows, fmt = short, max, color = COL.teal, labelWidth = 150 }) {
  if (!rows?.length) return <Empty />;
  const m = max ?? Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  return (
    <div className="hbar">
      {rows.map((r) => (
        <div className="hbar-row" key={r.label} title={r.title || r.label}>
          <span className="hbar-l" style={{ width: labelWidth }}>
            {r.label}
            {r.sub && <small>{r.sub}</small>}
          </span>
          <span className="hbar-t">
            <span style={{ width: `${Math.max(1, (Math.abs(r.value) / m) * 100)}%`, background: r.color || color }} />
          </span>
          <span className="hbar-v">{r.display ?? fmt(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- Percentile strip ---------- */
export function PercentileStrip({ pct, label, color, good }) {
  if (pct == null) return <span className="strip-na">n/a</span>;
  const c = color || (good === true ? (pct >= 60 ? COL.green : pct >= 35 ? COL.amber : COL.red)
    : good === false ? (pct >= 75 ? COL.red : pct >= 40 ? COL.amber : COL.green) : COL.teal);
  return (
    <div className="strip" title={`${pct.toFixed(0)}th percentile`}>
      <div className="strip-track">
        <span className="strip-mid" />
        <span className="strip-fill" style={{ width: `${pct}%`, background: c, opacity: 0.35 }} />
        <span className="strip-dot" style={{ left: `${pct}%`, background: c }} />
      </div>
      {label !== false && <span className="strip-n" style={{ color: c }}>{pct.toFixed(0)}</span>}
    </div>
  );
}

/* ---------- Empty chart ---------- */
export function Empty({ text = "No data available" }) {
  return <div className="empty-chart">{text}</div>;
}

/* ---------- Shared Tooltip (used by all charts) ---------- */
export function Tooltip({ visible, x, y, content }) {
  const ref = useRef(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });

  useEffect(() => {
    if (!visible || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const spaceRight = window.innerWidth - (x + rect.width);
    const spaceBottom = window.innerHeight - (y + rect.height);

    const newX = spaceRight < 160 ? x - 170 : x + 12;
    const newY = spaceBottom < 180 ? y - 80 : y + 12;

    setPosition({ left: newX, top: newY });
  }, [visible, x, y]);

  if (!visible || !content) return null;

  return (
    <div
      ref={ref}
      className="chart-tooltip"
      style={{
        position: "fixed",
        left: position.left,
        top: position.top,
        background: "#0b0d11",
        border: "1px solid #2a3344",
        borderRadius: "8px",
        padding: "12px 14px",
        fontSize: "13px",
        color: "#e8eaed",
        boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
        pointerEvents: "none",
        zIndex: 9999,
        whiteSpace: "nowrap",
        maxWidth: "260px",
        lineHeight: "1.4",
      }}
    >
      <div style={{ fontWeight: "600", color: "#fff", marginBottom: "6px" }}>{content.ticker}</div>
      {content.name && <div style={{ color: "#a0a0a0", marginBottom: "8px" }}>{content.name}</div>}
      {Object.entries(content.metrics || {}).map(([label, value]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
          <span style={{ color: "#a0a0a0" }}>{label}</span>
          <span style={{ fontWeight: "600", color: "#fff" }}>{value}</span>
        </div>
      ))}
    </div>
  );
}