export const KPIS = {
  entities: 47,
  entitiesDelta: "+2 THIS WEEK",
  criticalAlerts: 4,
  modelAuc: "0.942",
  modelAucDelta: "σ 0.011",
  ingestionSla: "99.8%",
  latency: "LATENCY 42MS",
};

export const HISTOGRAM = [
  { tier: "Stable", range: "SCORE 0 – 20", count: 3, color: "#3dd68c", height: 45 },
  { tier: "Neutral", range: "SCORE 20 – 40", count: 2, color: "#4b5563", height: 30 },
  { tier: "Watchlist", range: "SCORE 40 – 70", count: 6, color: "#f5c542", height: 90 },
  { tier: "Critical", range: "SCORE 70 – 100", count: 4, color: "#ff5c7a", height: 60 },
];

export const MODELS = [
  { name: "Fused (News+Report+Env)", desc: "Embedding+Env · MLP", auc: "0.942" },
  { name: "Fused (News+Report+Env)", desc: "Embedding+Env · RandomForest", auc: "0.933" },
  { name: "Fused (News+Report+Env)", desc: "Embedding+Env · LogisticRegression", auc: "0.921" },
  { name: "News", desc: "MiniLM Embedding · MLP", auc: "0.902" },
  { name: "News", desc: "MiniLM Embedding · LogisticRegression", auc: "0.881" },
];

export const COMPANIES = [
  {
    id: "C0002",
    symbol: "APTV",
    name: "Aptiv PLC",
    sector: "Consumer Cyclical / Auto Parts",
    score: 98.2,
    corroboration: 30,
    tier: "Critical",
    status: "Critical",
  },
  {
    id: "C0101",
    symbol: "GPC.L",
    name: "Global Petrochemical Ltd.",
    sector: "Energy / Petrochem",
    score: 84.2,
    corroboration: 12,
    tier: "Critical",
    status: "Critical",
  },
  {
    id: "C0102",
    symbol: "TMC.T0",
    name: "Titan Mining Corp.",
    sector: "Metals & Mining",
    score: 62.1,
    corroboration: 8,
    tier: "Watchlist",
    status: "Watchlist",
  },
  {
    id: "C0103",
    symbol: "AZL",
    name: "Azure Logistics",
    sector: "Transportation",
    score: 12.5,
    corroboration: 3,
    tier: "Stable",
    status: "Stable",
  },
  {
    id: "C0001",
    symbol: "ABNB",
    name: "Airbnb, Inc.",
    sector: "Consumer Cyclical / Travel",
    score: 18.0,
    corroboration: 4,
    tier: "Stable",
    status: "Stable",
  },
  {
    id: "C0003",
    symbol: "AZO",
    name: "AutoZone, Inc.",
    sector: "Consumer Cyclical / Auto Parts",
    score: 71.4,
    corroboration: 15,
    tier: "Critical",
    status: "Critical",
  },
];

export const ALERTS = [
  {
    sev: "SEV_10 · ENVIRONMENTAL",
    text: "Anomalous NDVI collapse detected at Amazon Basin Sector 4 (Asset PDR-04).",
    tags: ["TIER_1", "TIER_2"],
    ago: "2m ago",
    corr: "4 corroborated",
  },
  {
    sev: "SEV_09 · REGULATORY",
    text: "EPA notice of violation filed re: runoff levels at facility sector 09.",
    tags: ["TIER_1"],
    ago: "8m ago",
    corr: "2 corroborated",
  },
];

/** Matches real reasoning-engine output shape for APTV */
export const REASONING = {
  APTV: {
    composite_score: 98.2,
    risk_tier: "Critical",
    model_probability: 0.991,
    predicted_class: 1,
    top_drivers: [
      { feature: "sector_yf_Industrials", importance: 0.0626 },
      { feature: "ebitda_margins", importance: 0.0588 },
      { feature: "Water_pct", importance: 0.0413 },
      { feature: "Mean_NDVI", importance: 0.0388 },
      { feature: "free_cashflow", importance: 0.0362 },
      { feature: "fifty_two_week_high", importance: 0.0358 },
      { feature: "gross_margins", importance: 0.0341 },
      { feature: "average_volume", importance: 0.0329 },
    ],
    explanation:
      "The model predicts a 0.991 probability of elevated OSHA enforcement risk, driven by sector (Industrials), EBITDA margins, Water_pct, Mean_NDVI, free cashflow, fifty_two_week_high, gross margins, and average volume. Aptiv has a history of OSHA violations, including a recent Serious violation with a $8,066 penalty issued on 2025-01-13 [E38654]. On the same date, a Repeat violation resulted in a $25,350 penalty [E38655]. Another Serious violation was issued with a penalty of $1,362 for 10 instances [E38658]. Earlier, in 2023, a Willful violation occurred with a $13,500 penalty [E38638]. The company's 10-K disclosure mentions labor strikes adversely impacting financial condition and cash flows [E52532], and notes exposure to environmental, health, and safety regulations without assurance of complete compliance [E52535], [E52536].",
    recommendation:
      "Flag for immediate review due to very high model probability and a pattern of recent and recurring high-severity OSHA violations, including Repeat and Serious violations with significant penalties. Request details on corrective actions for the 2025 violations.",
    corroboration_count: 30,
    evidence_ids: [38654, 38655, 38658, 38638, 52532, 52535, 52536],
  },
  default: {
    composite_score: 45.0,
    risk_tier: "Watchlist",
    model_probability: 0.52,
    predicted_class: 1,
    top_drivers: [
      { feature: "ebitda_margins", importance: 0.05 },
      { feature: "word_count", importance: 0.03 },
    ],
    explanation:
      "Model probability is moderate. Limited high-severity enforcement evidence in the current window. Review disclosure language and recent inspection activity before escalating.",
    recommendation:
      "Maintain standard monitoring cadence. Re-run reasoning after next quarterly filing or any new OSHA notice.",
    corroboration_count: 5,
    evidence_ids: [],
  },
};

export function getReasoning(symbol) {
  return REASONING[symbol] || {
    ...REASONING.default,
    composite_score: COMPANIES.find((c) => c.symbol === symbol)?.score ?? 40,
    risk_tier: COMPANIES.find((c) => c.symbol === symbol)?.tier ?? "Neutral",
  };
}
