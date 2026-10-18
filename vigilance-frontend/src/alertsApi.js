// NEW FILE: vigilance-frontend/src/alertsApi.js
import { API } from "./api";

async function req(path, { method = "GET", body } = {}) {
  const res = await fetch(`${API}/api/alerts${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

const qs = (o = {}) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const alertsApi = {
  list: (f) => req(qs(f)),
  summary: () => req("/summary"),
  get: (id) => req(`/${id}`),
  act: (id, body) => req(`/${id}/action`, { method: "POST", body }),
  bulk: (body) => req("/bulk", { method: "POST", body }),
  settings: () => req("/settings"),
  saveSettings: (patch) => req("/settings", { method: "PUT", body: patch }),
  refresh: (reload = true) => req("/refresh", { method: "POST", body: { reload } }),
  testNotify: () => req("/notify/test", { method: "POST" }),
  exportUrl: (f) => `${API}/api/alerts/export.csv${qs(f)}`,
  companies: async () => {
    const res = await fetch(`${API}/api/companies?page_size=500`);
    if (!res.ok) return [];
    return (await res.json()).results || [];
  },
};