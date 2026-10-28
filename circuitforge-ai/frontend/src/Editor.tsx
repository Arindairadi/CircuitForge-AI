import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";

const PINS: Record<string, string[]> = { V: ["p", "n"], R: ["1", "2"], C: ["1", "2"], LED: ["a", "k"], D: ["a", "k"], Q: ["b", "c", "e"], M: ["g", "d", "s"], L: ["1", "2"], OA: ["p", "n", "o"], QP: ["b", "c", "e"], MP: ["g", "d", "s"], REG: ["in", "gnd", "out"] };
const HAS_VALUE = ["V", "R", "C", "L", "REG"], EDIT_VALUE = [...HAS_VALUE, "OA"];   // OA value = supply rail in volts (empty = ideal)
type Comp = { ref: string; kind: string; value: number | null; pins: Record<string, string>; rating?: number | null; pulse?: number[] | null; datasheet?: string | null };

function describe(a: Comp[], b: Comp[]): string[] {
  const A = new Map(a.map(c => [c.ref, c])), B = new Map(b.map(c => [c.ref, c])), out: string[] = [];
  b.forEach(c => { if (!A.has(c.ref)) out.push(`added ${c.ref} (${c.kind})`); else if (JSON.stringify(A.get(c.ref)) !== JSON.stringify(c)) out.push(`changed ${c.ref}`); });
  a.forEach(c => { if (!B.has(c.ref)) out.push(`removed ${c.ref}`); });
  return out;
}

export default function Editor({ circuit, draft: draftProp, setDraft: setDraftProp, busy, onSave }: { circuit: any; draft?: Comp[]; setDraft?: Dispatch<SetStateAction<Comp[]>>; busy: boolean; onSave: (c: any) => void }) {
  const [local, setLocal] = useState<Comp[]>(circuit.components), [kind, setKind] = useState("R"), [ref, setRef] = useState("");
  const draft = draftProp ?? local, setDraft = setDraftProp ?? setLocal;
  const set = (i: number, patch: Partial<Comp>) => setDraft(d => d.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const changes = describe(circuit.components, draft);
  const add = () => { if (!ref) return; setDraft(d => [...d, { ref, kind, value: HAS_VALUE.includes(kind) ? 1000 : null, pins: {} }]); setRef(""); };
  return (<section aria-label="Circuit editor"><h3>Structured editor</h3>
    <p style={{ fontSize: 13 }}>Edit values, references and which net each pin connects to (net “0” is ground). Nothing is saved until you review the change list and save; the server validates the circuit and creates a new version. This is a form-based editor, not a drag-and-drop canvas.</p>
    <table border={1} cellPadding={3}><thead><tr><th>Ref</th><th>Kind</th><th>Value (SI)</th><th>Pin → net</th><th /></tr></thead><tbody>
      {draft.map((c, i) => <tr key={i}>
        <td><input size={5} aria-label={`reference ${i}`} value={c.ref} onChange={e => set(i, { ref: e.target.value.toUpperCase() })} /></td><td>{c.kind}</td>
        <td>{EDIT_VALUE.includes(c.kind) ? <input size={9} placeholder={c.kind === "OA" ? "rail V / ideal" : undefined} aria-label={`value ${c.ref}`} value={c.value ?? ""} onChange={e => set(i, { value: e.target.value === "" ? null : Number(e.target.value) })} /> : "—"}</td>
        <td>{PINS[c.kind].map(p => <label key={p} style={{ marginRight: 6 }}>{p}→<input size={7} aria-label={`${c.ref} pin ${p}`} value={c.pins[p] ?? ""} onChange={e => { const pins = { ...c.pins }; if (e.target.value) pins[p] = e.target.value; else delete pins[p]; set(i, { pins }); }} /></label>)}</td>
        <td><button onClick={() => { if (confirm(`Remove ${c.ref}?`)) setDraft(d => d.filter((_, j) => j !== i)); }}>Remove</button></td></tr>)}
    </tbody></table>
    <p>Add: <select value={kind} onChange={e => setKind(e.target.value)}>{Object.keys(PINS).map(k => <option key={k}>{k}</option>)}</select>{" "}
      <input placeholder="Ref e.g. R9" size={6} value={ref} onChange={e => setRef(e.target.value.toUpperCase())} /> <button disabled={!/^[A-Z]{1,3}[0-9]{1,4}$/.test(ref)} onClick={add}>Add part</button></p>
    {changes.length > 0 ? <div><b>Pending changes:</b><ul>{changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
      <button disabled={busy} onClick={() => onSave({ ...circuit, components: draft.map(c => ({ ...c, value: EDIT_VALUE.includes(c.kind) ? c.value : null })) })}>Save as new version</button>{" "}
      <button onClick={() => setDraft(circuit.components)}>Discard</button></div> : <p><i>No pending changes.</i></p>}</section>);
}
