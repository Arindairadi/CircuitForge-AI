let token = sessionStorage.getItem("cf_token") ?? "";
export const setToken = (t: string) => { token = t; t ? sessionStorage.setItem("cf_token", t) : sessionStorage.removeItem("cf_token"); };
export const hasToken = () => !!token;
export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch("/api" + path, { method: opts.method ?? "GET",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(typeof e.detail === "string" ? e.detail : `Request failed (${r.status})`); }
  return r.status === 204 ? (undefined as T) : r.json();
}
export async function downloadBom(pid: number) {
  const r = await fetch(`/api/projects/${pid}/bom?format=csv`, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error("BOM export failed");
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = "bom.csv"; a.click();
}
export async function downloadFile(path: string, name: string) {
  const r = await fetch("/api" + path, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error("Download failed");
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
}
export async function blobUrl(path: string): Promise<string> {
  const r = await fetch("/api" + path, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error("Download failed");
  return URL.createObjectURL(await r.blob());
}
