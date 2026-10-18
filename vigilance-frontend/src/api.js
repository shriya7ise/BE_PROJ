const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function getJson(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

export async function fetchCompanies({ page = 1, pageSize = 50, tier, sector, search } = {}) {
  const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (tier) q.set("tier", tier);
  if (search) q.set("q", search);
  if (sector) q.set("sector", sector);
  return getJson(`/api/companies?${q}`);
}

export async function fetchOverview() {
  return getJson("/api/overview");
}

export async function fetchCompany(symbol) {
  return getJson(`/api/companies/${encodeURIComponent(symbol)}`);
}

export async function fetchReasoning(symbol, refresh = false) {
  const suffix = refresh ? "?refresh=1" : "";
  return getJson(`/api/companies/${encodeURIComponent(symbol)}/reasoning${suffix}`);
}

export async function fetchSources() {
  return getJson("/api/sources");
}

export async function fetchSignals({ page = 1, pageSize = 25, category, minSeverity, search } = {}) {
  const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) q.set("q", search);
  if (category) q.set("category", category);
  if (minSeverity != null) q.set("min_severity", String(minSeverity));
  return getJson(`/api/signals?${q}`);
}

export async function fetchFinancials(limit = 100) {
  return getJson(`/api/financials?limit=${limit}`);
}

export async function sendChat(message, symbol, extra = {}) {
  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, symbol: symbol || null, ...extra }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
/* ---- deep-dive endpoints ---- */
export { API };

export async function fetchEsg(symbol) {
  return getJson(`/api/companies/${encodeURIComponent(symbol)}/esg`);
}
export async function fetchFinancialStudy(symbol) {
  return getJson(`/api/companies/${encodeURIComponent(symbol)}/financials`);
}
export async function fetchCompanySignals(symbol) {
  return getJson(`/api/companies/${encodeURIComponent(symbol)}/signals`);
}
export function reportUrl(symbol, kind) {
  return `${API}/api/companies/${encodeURIComponent(symbol)}/report/${kind}.pdf`;
}
