import { useEffect, useState } from "react";
import { api, setToken, hasToken, downloadBom, downloadFile, blobUrl } from "./api";
import Chart from "./Chart";
import Editor from "./Editor";
import Schematic from "./Schematic";
import Pcb3D from "./Pcb3D";
import { BomPanel, Datasheets } from "./Parts";

type Proj = { id: number; name: string; versions: number; owned?: boolean };
const TEMPLATES = ["led", "voltage_divider", "rc_lowpass", "npn_switch", "mosfet_switch", "relay_driver", "opamp_noninverting", "pmos_highside", "ldo_supply"];

function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const go = async (register: boolean) => { setBusy(true); setErr("");
    try { if (register) await api("/auth/register", { method: "POST", body: { email, password } });
      setToken((await api("/auth/login", { method: "POST", body: { email, password } })).access_token); onDone(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  return (<main style={{ maxWidth: 360, margin: "4rem auto" }}><h1>CircuitForge AI</h1>
    <label>Email <input value={email} onChange={e => setEmail(e.target.value)} type="email" /></label><br />
    <label>Password (8+ chars) <input value={password} onChange={e => setPassword(e.target.value)} type="password" /></label><br />
    <button disabled={busy} onClick={() => go(false)}>Log in</button> <button disabled={busy} onClick={() => go(true)}>Register</button>
    {err && <p role="alert" style={{ color: "#b00" }}>{err}</p>}</main>);
}

function Notes({ id, initial }: { id: number; initial: string }) {
  const [t, setT] = useState(initial), [st, setSt] = useState("");
  return (<div><h3>Notes</h3><textarea aria-label="Project notes" rows={3} style={{ width: "100%", maxWidth: 800 }} value={t} maxLength={10000} onChange={e => { setT(e.target.value); setSt(""); }} />
    <br /><button onClick={async () => { try { await api(`/projects/${id}/notes`, { method: "PUT", body: { notes: t } }); setSt("Saved"); } catch (e) { setSt((e as Error).message); } }}>Save notes</button> <span role="status">{st}</span></div>);
}

function Workspace({ id, onBack }: { id: number; onBack: () => void }) {
  const [p, setP] = useState<any>(null), [msg, setMsg] = useState(""), [findings, setFindings] = useState<any[] | null>(null), [sim, setSim] = useState<any>(null), [busy, setBusy] = useState(false), [instr, setInstr] = useState(""), [prop, setProp] = useState<any>(null), [rev, setRev] = useState<any>(null), [kc, setKc] = useState<any>(null), [opt, setOpt] = useState<any>(null), [vers, setVers] = useState<any>(null), [pcb, setPcb] = useState<any>(null), [svg, setSvg] = useState(""), [audit, setAudit] = useState<any[] | null>(null), [mem, setMem] = useState<any[] | null>(null), [memEmail, setMemEmail] = useState(""), [job, setJob] = useState<any>(null), [tv, setTv] = useState("3.3"), [show3d, setShow3d] = useState(false), [draft, setDraft] = useState<any[] | null>(null);
  const load = () => api(`/projects/${id}`).then(setP).catch(e => setMsg(e.message));
  useEffect(() => { load(); }, [id]);
  useEffect(() => { setDraft(null); }, [p?.circuit?.version]);
  const run = async (fn: () => Promise<void>) => { setBusy(true); setMsg(""); try { await fn(); await load(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); } };
  if (!p) return <p>{msg || "Loading…"}</p>;
  const out = p.circuit.components.find((c: any) => c.kind === "C")?.pins["1"] ?? Object.keys(p.circuit.components.flatMap((c: any) => Object.values(c.pins)).reduce((a: any, n: any) => ({ ...a, [n]: 1 }), {})).find(n => n !== "0");
  return (<main style={{ maxWidth: 800, margin: "1rem auto" }}><button onClick={onBack}>← Projects</button><h2>{p.name} (v{p.circuit.version})</h2>
    <p>Simulation: <b>{p.circuit.simulation_status}</b> · Verification: <b>{p.circuit.verification_status}</b> — a design is only "simulated" after a successful run; nothing here is safety certification.</p>
    <table border={1} cellPadding={4}><thead><tr><th>Ref</th><th>Kind</th><th>Value</th><th>Pins → nets</th></tr></thead><tbody>
      {p.circuit.components.map((c: any) => <tr key={c.ref}><td>{c.ref}</td><td>{c.kind}</td><td>{c.value ?? "—"}</td><td>{Object.entries(c.pins).map(([k, v]) => `${k}→${v}`).join(", ")}</td></tr>)}</tbody></table>
    <Schematic key={`s${p.circuit.version}`} circuit={{ components: draft ?? p.circuit.components }} onChange={setDraft} />
    <Editor key={p.circuit.version} circuit={p.circuit} draft={draft ?? p.circuit.components} setDraft={(f: any) => setDraft(prev => (typeof f === "function" ? f(prev ?? p.circuit.components) : f))} busy={busy} onSave={c => run(async () => { await api(`/projects/${id}/circuit`, { method: "PUT", body: c }); setSim(null); setFindings(null); })} />
    <Notes key={`n${id}`} id={id} initial={p.notes ?? ""} />
    <p><button onClick={async () => { try { const d = await api(`/projects/${id}/duplicate`, { method: "POST" }); setMsg(`Duplicated as project #${d.id} (see Projects)`); } catch (e) { setMsg((e as Error).message); } }}>Duplicate project</button>{" "}
      <button onClick={() => downloadFile(`/projects/${id}/export`, `${p.name.replace(/[^A-Za-z0-9_-]+/g, "_")}.json`).catch(e => setMsg(e.message))}>Export project (JSON)</button></p>
    <h3>Assumptions</h3><ul>{p.circuit.assumptions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul>
    <div><button disabled={busy} onClick={() => run(async () => setFindings((await api(`/projects/${id}/verify`, { method: "POST" })).findings))}>Verify</button>{" "}
      <button disabled={busy} onClick={() => run(async () => setSim(await api(`/projects/${id}/simulate`, { method: "POST", body: { analysis: "op" } })))}>Simulate (operating point)</button>{" "}
      <button disabled={busy} onClick={() => run(async () => setSim(await api(`/projects/${id}/simulate`, { method: "POST", body: { analysis: "tran", node: out, tstep: 1e-5, tstop: 5e-3 } })))}>Simulate (transient, node {out})</button>{" "}
      <button disabled={busy} onClick={() => run(async () => setSim(await api(`/projects/${id}/simulate`, { method: "POST", body: { analysis: "ac", node: out, fstart: 1, fstop: 10000 } })))}>Simulate (AC sweep 1 Hz–10 kHz)</button>{" "}
      <button disabled={busy} onClick={() => { const v = p.circuit.components.find((c: any) => c.kind === "V"); if (!v) return setMsg("No voltage source to sweep"); const stop = Math.max(2 * (v.value ?? 5), 1); run(async () => setSim(await api(`/projects/${id}/simulate`, { method: "POST", body: { analysis: "dc", source: v.ref, node: out, start: 0, stop, step: stop / 20 } }))); }}>DC sweep (0–2× source)</button>{" "}
      <button disabled={busy} onClick={() => { const r = p.circuit.components.find((c: any) => c.kind === "R"); if (!r) return setMsg("No resistor to sweep"); run(async () => setSim(await api(`/projects/${id}/sweep`, { method: "POST", body: { ref: r.ref, node: out, start: r.value * 0.1, stop: r.value * 10, points: 20 } }))); }}>Sweep first resistor ×0.1–×10</button>{" "}
      <button onClick={() => downloadBom(id).catch(e => setMsg(e.message))}>Download BOM (CSV)</button></div>
    <h3>Ask AI to modify (try: “change the input voltage to 12 V”)</h3>
    <input style={{ width: "60%" }} value={instr} onChange={e => setInstr(e.target.value)} />{" "}
    <button disabled={busy || instr.length < 3} onClick={() => run(async () => setProp(await api(`/projects/${id}/ai/propose`, { method: "POST", body: { instruction: instr } })))}>Preview change</button>
    {prop && <div style={{ border: "1px solid #999", padding: 8, marginTop: 8 }}><p>{prop.message}</p>
      {prop.changes.length > 0 && <><ul>{prop.changes.map((c: string, i: number) => <li key={i}><code>{c}</code></li>)}</ul>
      <button disabled={busy} onClick={() => run(async () => { await api(`/projects/${id}/circuit`, { method: "PUT", body: prop.circuit }); setProp(null); setSim(null); setFindings(null); })}>Approve &amp; apply (new version)</button>{" "}</>}
      <button onClick={() => setProp(null)}>Dismiss</button></div>}
    <p><button disabled={busy} onClick={() => run(async () => setRev(await api(`/projects/${id}/review`, { method: "POST" })))}>Design review</button></p>
    {rev && <div><p><b>{rev.summary}</b></p><p>Verified: {rev.verified_facts.join("; ") || "nothing yet (run a simulation)"}</p><p>Unverified assumptions: {rev.unverified_assumptions.join("; ")}</p>
      <p>Tests still required: {rev.tests_required.join("; ")}</p><p>Issues: {rev.critical_issues.length ? rev.critical_issues.map((f: any) => f.explanation).join("; ") : "none found by automated checks"}</p></div>}
    {busy && <p>Working…</p>}{msg && <p role="alert" style={{ color: "#b00" }}>{msg}</p>}
    {sim?.analysis === "op" && <><h3>Operating point ({sim.engine})</h3><pre>{JSON.stringify(sim.node_voltages, null, 1)}{"\n"}{JSON.stringify(sim.source_currents)}</pre></>}
    {sim?.analysis === "tran" && <><h3>Transient v({sim.node}) ({sim.engine})</h3><Chart x={sim.time} y={sim.voltage} xl="time (s)" yl="V" /></>}
    {sim?.analysis === "dc" && <><h3>DC sweep of {sim.source}: v({sim.node}) ({sim.engine})</h3><Chart x={sim.x} y={sim.voltage} xl={`${sim.source} (V)`} yl="V" /></>}
    {sim?.analysis === "psweep" && <><h3>v({sim.node}) while sweeping {sim.ref} ({sim.engine})</h3><Chart x={sim.values} y={sim.voltage} xl={`${sim.ref} (SI units)`} yl="V" /></>}
    {sim?.analysis === "ac" && <><h3>AC magnitude of v({sim.node}) in dB ({sim.engine})</h3><Chart x={sim.freq_hz.map((f: number) => Math.log10(f))} y={sim.magnitude_db} xl="log10 frequency (Hz)" yl="dB" /></>}
    <h3>KiCad export</h3><button disabled={busy} onClick={() => run(async () => setKc(await api(`/projects/${id}/export/kicad`, { method: "POST" })))}>Export KiCad schematic</button>
    {kc && <div><p>KiCad {kc.kicad}: netlist round-trip <b>{kc.netlist_roundtrip_ok ? "matches" : "MISMATCH"}</b>. {kc.kicad_erc}</p>{kc.mismatches.map((m: string, i: number) => <p key={i}>{m}</p>)}
      {kc.files.map((f: string) => <button key={f} onClick={() => downloadFile(`/projects/${id}/export/kicad/${f}?version=${kc.version}`, f).catch(e => setMsg(e.message))}>{f}</button>)}<p><i>{kc.note}</i></p></div>}
    <h3>PCB (KiCad 7)</h3><button disabled={busy} onClick={() => run(async () => { const r = await api(`/projects/${id}/pcb/generate`, { method: "POST" }); setPcb(r); setSvg(await blobUrl(`/projects/${id}/export/kicad/design.svg?version=${r.version}`)); })}>Generate PCB &amp; fabrication files</button>
    {pcb && <div><p>Board {pcb.board_mm[0]}×{pcb.board_mm[1]} mm · KiCad DRC: <b>{pcb.drc.unconnected} unconnected, {pcb.drc.errors} errors</b>, {pcb.drc.violations.length} total findings (warnings included).</p>
      <p><b>Not ready for fabrication.</b> Open items: {[...pcb.manufacturing_readiness.known_open_issues, ...pcb.manufacturing_readiness.unresolved].join("; ")}</p><p>3D view: {pcb["3d_view"]}</p>{pcb.layout && <><button onClick={() => setShow3d(v => !v)}>{show3d ? "Hide" : "Show"} 3D view</button>{show3d && <Pcb3D layout={pcb.layout} />}</>}
      {svg && <img alt="PCB preview" src={svg} style={{ maxWidth: "100%", background: "#fff", border: "1px solid #ccc" }} />}
      <div>{pcb.files.map((f: string) => <button key={f} onClick={() => downloadFile(`/projects/${id}/export/kicad/${f}?version=${pcb.version}`, f).catch(e => setMsg(e.message))}>{f}</button>)}</div></div>}
    <p><button disabled={busy} onClick={async () => { setMsg(""); try { let j = await api(`/projects/${id}/jobs`, { method: "POST", body: { kind: "pcb" } }); setJob(j);
      for (let i = 0; i < 120 && !["done", "failed"].includes(j.status); i++) { await new Promise(r => setTimeout(r, 1000)); j = await api(`/jobs/${j.id}`); setJob(j); }
      if (j.status === "done") { setPcb({ ...j.result, version: p.circuit.version }); } await load(); } catch (e) { setMsg((e as Error).message); } }}>Generate PCB as background job</button>
      {job && <span> job #{job.id}: <b>{job.status}</b>{job.error && ` — ${job.error}`}</span>}</p>
    <BomPanel key={`b${id}`} id={id} comps={p.circuit.components} />
    <Datasheets key={`d${id}`} id={id} />
    <h3>Optimization</h3><button disabled={busy} onClick={() => run(async () => setOpt(await api(`/projects/${id}/optimize`, { method: "POST", body: { objective: "smaller_pcb_area" } })))}>Smaller PCB area (runs ~8 KiCad DRC checks, ~20 s)</button>{" "}<button disabled={busy} onClick={() => run(async () => setOpt(await api(`/projects/${id}/optimize`, { method: "POST", body: { objective: "lower_power", target_led_current_ma: 5, min_led_current_ma: 2 } })))}>Lower power (LED 5 mA, min 2 mA)</button>
    {" "}<input aria-label="target voltage" size={4} value={tv} onChange={e => setTv(e.target.value)} /> V <button disabled={busy} onClick={() => run(async () => setOpt(await api(`/projects/${id}/optimize`, { method: "POST", body: { objective: "hit_target_voltage", target_v: Number(tv), tolerance_pct: 1 } })))}>Hit target voltage (divider, 1%)</button>
    {opt && (!opt.supported ? <p>{opt.message}</p> : <div style={{ border: "1px solid #999", padding: 8 }}>{opt.objective === "smaller_pcb_area" ? <div><p>Original: {opt.original.board_mm.join(" × ")} mm ({opt.original.area_mm2} mm²) at {opt.original.pitch_mm} mm pitch<br />Alternative: {opt.alternative.board_mm.join(" × ")} mm ({opt.alternative.area_mm2} mm²) at {opt.alternative.pitch_mm} mm pitch — <b>{opt.reduction_pct}% smaller</b><br />Constraint ({opt.constraint}): <b>{opt.constraint_satisfied ? "met" : "NOT met"}</b></p>
          <table border={1} cellPadding={3}><thead><tr><th>Pitch (mm)</th><th>Area (mm²)</th><th>KiCad DRC</th></tr></thead><tbody>{opt.tried.map((t: any) => <tr key={t.pitch_mm}><td>{t.pitch_mm}</td><td>{t.area_mm2}</td><td>{t.drc_clean ? "clean" : `${t.drc_errors} errors, ${t.drc_unconnected} unconnected`}</td></tr>)}</tbody></table>
          <button disabled={busy} onClick={() => run(async () => { const r = await api(`/projects/${id}/pcb/generate?pitch_mm=${opt.alternative.pitch_mm}`, { method: "POST" }); setPcb(r); setSvg(await blobUrl(`/projects/${id}/export/kicad/design.svg?version=${r.version}`)); })}>Generate PCB at this pitch</button></div>
        : opt.objective === "hit_target_voltage" ? <p>Original Vout {opt.original.vout.toFixed(3)} V (error {opt.original.error_pct.toFixed(2)}%, {opt.original.method})<br />Alternative R2 = {opt.chosen_r2_e24_ohm} Ω (E24): Vout {opt.alternative.vout.toFixed(3)} V (error {opt.alternative.error_pct.toFixed(2)}%, {opt.alternative.method})<br />Constraint ({opt.constraint}): <b>{opt.constraint_satisfied ? "met" : "NOT met"}</b> — {opt.action}</p>
        : <p>Original: {(opt.original.supply_power_w * 1e3).toFixed(2)} mW ({opt.original.method})<br />Alternative: {(opt.alternative.supply_power_w * 1e3).toFixed(2)} mW ({opt.alternative.method})<br />Reduction: {opt.reduction_pct}% · Constraint ({opt.constraint}): <b>{opt.constraint_satisfied ? "met" : "NOT met"}</b></p>}
      <p>Trade-off: {opt.tradeoff}</p>
      {opt.constraint_satisfied && opt.alternative.circuit && <button disabled={busy} onClick={() => run(async () => { await api(`/projects/${id}/circuit`, { method: "PUT", body: opt.alternative.circuit }); setOpt(null); setSim(null); setFindings(null); })}>Approve &amp; apply (new version)</button>}</div>)}
    <h3>Version history</h3><button onClick={async () => { try { const v = await api(`/projects/${id}/versions`); const n = v.length; setVers({ v, diff: n > 1 ? (await api(`/projects/${id}/versions/${n - 1}/diff/${n}`)).changes : [] }); } catch (e) { setMsg((e as Error).message); } }}>Show versions</button>
    {vers && <><ul>{vers.v.map((x: any) => <li key={x.number}>v{x.number} · {x.components} components · {x.created_at}</li>)}</ul>{vers.diff.length > 0 && <><p>Latest change:</p><ul>{vers.diff.map((d: string, i: number) => <li key={i}><code>{d}</code></li>)}</ul></>}</>}
    <h3>Sharing</h3><button onClick={() => api(`/projects/${id}/members`).then(setMem).catch(e => setMsg(e.message))}>Show members</button>{" "}
    <input placeholder="user email" value={memEmail} onChange={e => setMemEmail(e.target.value)} />{" "}
    {["viewer", "editor"].map(r => <button key={r} disabled={!memEmail} onClick={() => run(async () => { await api(`/projects/${id}/members`, { method: "POST", body: { email: memEmail, role: r } }); setMem(await api(`/projects/${id}/members`)); })}>Share as {r}</button>)}
    {mem && <ul>{mem.map(m => <li key={m.email}>{m.email} — {m.role} <button onClick={() => run(async () => { await api(`/projects/${id}/members/${encodeURIComponent(m.email)}`, { method: "DELETE" }); setMem(await api(`/projects/${id}/members`)); })}>Remove</button></li>)}</ul>}
    <h3>Audit log</h3><button onClick={() => api(`/projects/${id}/audit`).then(setAudit).catch(e => setMsg(e.message))}>Show audit log</button>
    {audit && <ul>{audit.map((a, i) => <li key={i}>{a.at} · {a.by} · <b>{a.action}</b> {a.detail}</li>)}</ul>}
    {findings && <><h3>Findings</h3><ul>{findings.map((f, i) => <li key={i}><b>{f.severity}</b> [{f.check}] {f.target}: {f.explanation} — {f.executed ? f.evidence : "NOT EXECUTED"}. Fix: {f.suggested_fix}</li>)}</ul></>}
  </main>);
}

function Learn() {
  const [t, setT] = useState("led"), [l, setL] = useState<any>(null), [err, setErr] = useState("");
  useEffect(() => { setL(null); setErr(""); api(`/learning/${t}`).then(setL).catch(e => setErr(e.message)); }, [t]);
  return (<section><h2>Learning center</h2><select aria-label="lesson" value={t} onChange={e => setT(e.target.value)}>{["led", "voltage_divider", "rc_lowpass", "npn_switch", "mosfet_switch", "relay_driver", "opamp_noninverting", "pmos_highside", "ldo_supply"].map(x => <option key={x}>{x}</option>)}</select>
    {err && <p role="alert">{err}</p>}{l && <div><p><b>Purpose:</b> {l.purpose}</p><p><b>How it works:</b> {l.principle}</p><p><b>Key formula:</b> <code>{l.formula}</code></p>
      <h4>Experiments</h4><ul>{l.experiments.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul><h4>Safety</h4><ul>{l.safety.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
      <h4>Glossary</h4><dl>{Object.entries(l.glossary).map(([k, v]) => <div key={k}><dt><b>{k}</b></dt><dd>{v as string}</dd></div>)}</dl></div>}
    <h3>Help</h3><ul><li>Create a project from a template or describe a circuit; open it to verify, simulate (op / transient / AC), export KiCad files, generate a PCB, and download the BOM.</li>
      <li>“Simulated” appears only after a successful ngspice run. Passing checks is not safety or production certification.</li><li>Parts are generic models; choose real parts and check datasheets before building.</li></ul></section>);
}

function Settings({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState(""), [cur, setCur] = useState(""), [nw, setNw] = useState(""), [msg, setMsg] = useState("");
  useEffect(() => { api("/me").then(m => setMe(m.email)).catch(() => {}); }, []);
  return (<section><h2>Settings</h2><p>Signed in as <b>{me}</b></p><h3>Change password</h3>
    <input type="password" placeholder="current" value={cur} onChange={e => setCur(e.target.value)} /> <input type="password" placeholder="new (8+ chars)" value={nw} onChange={e => setNw(e.target.value)} />{" "}
    <button disabled={!cur || nw.length < 8} onClick={async () => { try { await api("/me/password", { method: "PUT", body: { current_password: cur, new_password: nw } }); setMsg("Password changed; all sessions were signed out."); setTimeout(onLogout, 1500); } catch (e) { setMsg((e as Error).message); } }}>Change</button>
    <p><button onClick={async () => { try { await api("/auth/logout", { method: "POST" }); } catch { /* token may already be invalid */ } onLogout(); }}>Log out</button></p>{msg && <p role="status">{msg}</p>}</section>);
}

export default function App() {
  const [authed, setAuthed] = useState(hasToken()), [projects, setProjects] = useState<Proj[]>([]), [sel, setSel] = useState<number | null>(null), [name, setName] = useState(""), [tpl, setTpl] = useState("led"), [err, setErr] = useState(""), [desc, setDesc] = useState(""), [note, setNote] = useState("");
  const refresh = () => api<Proj[]>("/projects").then(setProjects).catch(e => { setErr(e.message); if (/token/i.test(e.message)) { setToken(""); setAuthed(false); } });
  useEffect(() => { if (authed) refresh(); }, [authed]);
  const [view, setView] = useState("projects");
  const logout = () => { setToken(""); setAuthed(false); setView("projects"); };
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  const nav = (<nav style={{ maxWidth: 800, margin: "0.5rem auto" }}>{["projects", "learn", "settings"].map(v => <button key={v} aria-pressed={view === v} onClick={() => { setView(v); setSel(null); }} style={{ marginRight: 6, fontWeight: view === v ? "bold" : "normal" }}>{v}</button>)}</nav>);
  if (view === "learn") return <>{nav}<main style={{ maxWidth: 800, margin: "auto" }}><Learn /></main></>;
  if (view === "settings") return <>{nav}<main style={{ maxWidth: 800, margin: "auto" }}><Settings onLogout={logout} /></main></>;
  if (sel !== null) return <>{nav}<Workspace id={sel} onBack={() => { setSel(null); refresh(); }} /></>;
  return (<>{nav}<main style={{ maxWidth: 700, margin: "2rem auto" }}><h1>Projects</h1>
    <h3>New project</h3><input placeholder="Name" value={name} onChange={e => setName(e.target.value)} />{" "}
    <select value={tpl} onChange={e => setTpl(e.target.value)}>{TEMPLATES.map(t => <option key={t}>{t}</option>)}</select>{" "}
    <button disabled={!name} onClick={async () => { try { await api("/projects", { method: "POST", body: { name, template: tpl } }); setName(""); refresh(); } catch (e) { setErr((e as Error).message); } }}>Create</button>
    <h3>Import project</h3><input type="file" accept="application/json,.json" aria-label="Import project file" onChange={async e => { const f = e.target.files?.[0]; if (!f) return; setErr(""); try {
      if (f.size > 1_000_000) throw new Error("File too large (max 1 MB)"); await api("/projects/import", { method: "POST", body: JSON.parse(await f.text()) }); refresh(); } catch (x) { setErr((x as Error).message); } e.target.value = ""; }} />
    <h3>Or describe a circuit</h3><input style={{ width: "60%" }} placeholder="e.g. a 9 V LED indicator" value={desc} onChange={e => setDesc(e.target.value)} />{" "}
    <button disabled={desc.length < 3} onClick={async () => { setErr(""); setNote(""); try {
      const pr = await api("/ai/parse", { method: "POST", body: { prompt: desc } });
      if (!pr.template) { setNote(pr.notes.join(" ")); return; }
      await api("/projects", { method: "POST", body: { name: desc.slice(0, 60), template: pr.template, params: pr.params } });
      setNote([...pr.questions, ...pr.notes, `(parsed by: ${pr.source})`].join(" ")); setDesc(""); refresh();
    } catch (e) { setErr((e as Error).message); } }}>Generate</button>{note && <p>{note}</p>}
    {err && <p role="alert" style={{ color: "#b00" }}>{err}</p>}
    {projects.length === 0 ? <p>No projects yet.</p> : <ul>{projects.map(p => <li key={p.id}><a href="#" onClick={e => { e.preventDefault(); setSel(p.id); }}>{p.name}</a>{p.owned === false && " (shared)"}{" "}
      {p.owned !== false && <button onClick={async () => { if (confirm(`Delete "${p.name}"? This cannot be undone.`)) { await api(`/projects/${p.id}`, { method: "DELETE" }); refresh(); } }}>Delete</button>}</li>)}</ul>}</main></>);
}
