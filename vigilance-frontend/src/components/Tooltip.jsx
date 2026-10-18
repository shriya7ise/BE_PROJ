import { useRef, useEffect } from "react";

export function Tooltip({ visible, x, y, content }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!visible || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const spaceRight = window.innerWidth - (x + rect.width);
    const spaceBottom = window.innerHeight - (y + rect.height);
    const newX = spaceRight < 160 ? x - 170 : x + 12;
    const newY = spaceBottom < 180 ? y - 80 : y + 12;
    ref.current.style.left = `${newX}px`;
    ref.current.style.top = `${newY}px`;
  }, [visible, x, y]);

  if (!visible || !content) return null;

  return (
    <div
      ref={ref}
      className="chart-tooltip"
      style={{
        position: "fixed",
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
      <div style={{ fontWeight: "600", color: "#fff", marginBottom: "6px" }}>
        {content.ticker}
      </div>
      {content.name && <div style={{ color: "#a0a0a0", marginBottom: "8px" }}>{content.name}</div>}
      {Object.entries(content.metrics || {}).map(([label, value]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ color: "#a0a0a0" }}>{label}</span>
          <span style={{ fontWeight: "600", color: "#fff" }}>{value}</span>
        </div>
      ))}
    </div>
  );
}