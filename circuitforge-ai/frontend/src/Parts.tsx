import { useState } from "react";
import { api, downloadFile } from "./api";

export function BomPanel({ id, comps }: { id: number; comps: { ref: string }[] }) {
  const [rows, setRows] = useState<any[] | null>(null), [msg, setMsg] = useState(""), [f, setF] = useState({ ref: comps[0]?.ref ?? "", manufacturer: "", mpn: "", datasheet_url: "", price: "", availability: "", notes: "" });
  const [mpn, setMpn] = useState(""), [found, setFound] = useState<any[] | null>(null), [mine, setMine] = useState<any[] | null>(null);
  const load = () => api(`/projects/${id}/bom`).then(setRows).catch(e => setMsg(e.message));
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF(s => ({ ...s, [k]: e.target.value }));
  const body = () => Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" && k !== "notes" ? null : v]));
  return (<section aria-label="Bill of materials"><h3>Bill of materials</h3><button onClick={load}>Show BOM</button>
    {rows && <table border={1} cellPadding={3}><thead><tr><th>Refs</th><th>Qty</th><th>Value</th><th>Footprint</th><th>Manufacturer</th><th>MPN</th><th>Notes</th></tr></thead><tbody>
      {rows.map((r, i) => <tr key={i}><td>{r.references}</td><td>{r.quantity}</td><td>{r.value}</td><td>{r.footprint}</td><td>{r.manufacturer}</td><td>{r.mpn}</td><td style={{ fontSize: 12 }}>{r.notes}</td></tr>)}</tbody></table>}
    <h4>Assign a real part to a reference</h4><p style={{ fontSize: 13 }}>What you enter is stored as <b>user-entered</b> and shown as such. CircuitForge does not verify datasheets, prices or stock.</p>
    <select aria-label="reference" value={f.ref} onChange={set("ref")}>{comps.map(c => <option key={c.ref}>{c.ref}</option>)}</select>{" "}
    <input placeholder="manufacturer" value={f.manufacturer} onChange={set("manufacturer")} /> <input aria-label="mpn" placeholder="part number" value={f.mpn} onChange={set("mpn")} /> <input placeholder="datasheet https://…" value={f.datasheet_url} onChange={set("datasheet_url")} /> <input placeholder="price e.g. 0.02 USD" value={f.price} onChange={set("price")} /> <input placeholder="availability" value={f.availability} onChange={set("availability")} /> <input placeholder="notes" value={f.notes} onChange={set("notes")} />{" "}
    <button disabled={!f.ref} onClick={async () => { setMsg(""); try { await api(`/projects/${id}/bom/parts`, { method: "PUT", body: body() }); setMsg(`Saved ${f.ref} (user-entered)`); load(); } catch (e) { setMsg((e as Error).message); } }}>Save assignment</button>{" "}
    <button disabled={!f.ref} onClick={async () => { try { await api(`/projects/${id}/bom/parts/${f.ref}`, { method: "DELETE" }); setMsg(`Cleared ${f.ref}`); load(); } catch (e) { setMsg((e as Error).message); } }}>Clear</button>
    <h4>Look up a part number (needs a distributor API key on the server)</h4><input aria-label="lookup part number" value={mpn} onChange={e => setMpn(e.target.value)} />{" "}
    <button disabled={!mpn} onClick={async () => { setMsg(""); setFound(null); try { setFound((await api(`/components/lookup?mpn=${encodeURIComponent(mpn)}`)).results); } catch (e) { setMsg((e as Error).message); } }}>Look up</button>
    {found && (found.length === 0 ? <p>No results.</p> : <ul>{found.map((r, i) => <li key={i}>{r.manufacturer} {r.mpn} — {r.description} <i>({r.source}, retrieved {r.retrieved}; unverified)</i></li>)}</ul>)}
    <h4>My library parts</h4><button onClick={() => api("/components/mine").then(setMine).catch(e => setMsg(e.message))}>Show my parts</button>
    {mine && (mine.length === 0 ? <p>None yet (add via POST /components/manual).</p> : <ul>{mine.map(m => <li key={m.id}>{m.category}: {m.description} {m.part_number ?? ""} — {m.source}</li>)}</ul>)}
    {msg && <p role="status">{msg}</p>}</section>);
}

export function Datasheets({ id }: { id: number }) {
  const [list, setList] = useState<any[] | null>(null), [msg, setMsg] = useState("");
  const load = () => api(`/projects/${id}/datasheets`).then(setList).catch(e => setMsg(e.message));
  return (<section aria-label="Datasheets"><h3>Datasheets (PDF, max 5 MB)</h3><button onClick={load}>Show datasheets</button>{" "}
    <input type="file" accept="application/pdf,.pdf" aria-label="Upload datasheet" onChange={async e => { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; setMsg("");
      if (file.size > 5 * 1024 * 1024) return setMsg("File too large (max 5 MB)");
      try { const fd = new FormData(); fd.append("file", file); const r = await fetch(`/api/projects/${id}/datasheets`, { method: "POST", headers: { Authorization: `Bearer ${sessionStorage.getItem("cf_token") ?? ""}` }, body: fd });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `Upload failed (${r.status})`); setMsg("Uploaded"); load(); } catch (x) { setMsg((x as Error).message); } }} />
    {list && (list.length === 0 ? <p>No datasheets uploaded.</p> : <ul>{list.map(d => <li key={d.id}>{d.name} ({Math.round(d.size / 1024)} KB, sha256 {d.sha256.slice(0, 12)}…) <button onClick={() => downloadFile(`/projects/${id}/datasheets/${d.id}`, d.name).catch(e => setMsg(e.message))}>Download</button> <button onClick={async () => { if (confirm(`Delete ${d.name}?`)) { try { await api(`/projects/${id}/datasheets/${d.id}`, { method: "DELETE" }); load(); } catch (e) { setMsg((e as Error).message); } } }}>Delete</button></li>)}</ul>)}
    {msg && <p role="status">{msg}</p>}</section>);
}
