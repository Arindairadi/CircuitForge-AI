import { useMemo, useRef, useState } from "react";
import { connectPins, disconnectPin, groundPin } from "./netlist";
import type { Comp as NComp, PinRef } from "./netlist";

type Comp = { ref: string; kind: string; value: number | null; rating?: number | null; pins: Record<string, string> };
const ORDER: Record<string, string[]> = { V: ["p", "n"], R: ["1", "2"], C: ["1", "2"], L: ["1", "2"], LED: ["a", "k"], D: ["a", "k"], Q: ["b", "c", "e"], QP: ["b", "c", "e"], M: ["g", "d", "s"], MP: ["g", "d", "s"], OA: ["p", "n", "o"] };
const OFFS: Record<number, [number, number][]> = { 2: [[-40, 0], [40, 0]], 3: [[-40, 0], [0, -30], [0, 30]] };
const UNIT: Record<string, string> = { V: "V", R: "Ω", C: "F", L: "H", REG: "V", OA: "V" };
const fmt = (k: string, v: number | null) => { if (v == null) return ""; const u = UNIT[k] ?? ""; for (const [s, p] of [[1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]] as [number, string][]) if (Math.abs(v) >= s) return `${+(v / s).toPrecision(3)}${p}${u}`; return `${v}${u}`; };

export default function Schematic({ circuit, onChange }: { circuit: { components: Comp[] }; onChange?: (c: NComp[]) => void }) {
  const comps = circuit.components;
  const init = useMemo(() => Object.fromEntries(comps.map((c, i) => [c.ref, { x: 110 + (i % 4) * 190, y: 80 + Math.floor(i / 4) * 130 }])), [comps]);
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>(init);
  const [view, setView] = useState({ x: 0, y: 0, w: 800, h: 420 }), [sel, setSel] = useState<string | null>(null);
  const [wire, setWire] = useState(false), [from, setFrom] = useState<PinRef | null>(null), [note, setNote] = useState("");
  const edit = (next: NComp[], msg: string) => { onChange?.(next); setNote(msg); setFrom(null); };
  const clickPin = (ref: string, pin: string) => { if (!wire || !onChange) return; if (!from) { setFrom({ ref, pin }); setNote(`Selected ${ref}.${pin}; click another pin to connect`); return; }
    if (from.ref === ref && from.pin === pin) { setFrom(null); setNote(""); return; }
    const r = connectPins(comps as NComp[], from, { ref, pin }); edit(r.comps, `Connected ${from.ref}.${from.pin} to ${ref}.${pin} on net ${r.net}. Review and save as a new version below.`); };
  const drag = useRef<{ ref: string | null; sx: number; sy: number; moved: boolean } | null>(null), svg = useRef<SVGSVGElement>(null);
  const P = (ref: string) => pos[ref] ?? init[ref] ?? { x: 100, y: 100 };
  const pinXY = (c: Comp, pin: string) => { const o = OFFS[ORDER[c.kind].length][ORDER[c.kind].indexOf(pin)]; return { x: P(c.ref).x + o[0], y: P(c.ref).y + o[1] }; };
  const nets: Record<string, { x: number; y: number }[]> = {};
  comps.forEach(c => ORDER[c.kind].forEach(p => { const n = c.pins[p]; if (n) (nets[n] ||= []).push(pinXY(c, p)); }));
  const scale = () => (svg.current ? view.w / svg.current.getBoundingClientRect().width || 1 : 1);
  const down = (e: React.PointerEvent, ref: string | null) => { e.stopPropagation(); (e.target as Element).setPointerCapture?.(e.pointerId); drag.current = { ref, sx: e.clientX, sy: e.clientY, moved: false }; };
  const move = (e: React.PointerEvent) => { const d = drag.current; if (!d) return; const dx = (e.clientX - d.sx) * scale(), dy = (e.clientY - d.sy) * scale(); if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true; d.sx = e.clientX; d.sy = e.clientY;
    if (d.ref) setPos(p => ({ ...p, [d.ref!]: { x: P(d.ref!).x + dx, y: P(d.ref!).y + dy } })); else setView(v => ({ ...v, x: v.x - dx, y: v.y - dy })); };
  const up = (ref: string | null) => { if (drag.current && !drag.current.moved && ref) setSel(ref); drag.current = null; };
  const zoom = (f: number) => setView(v => ({ x: v.x + (v.w - v.w * f) / 2, y: v.y + (v.h - v.h * f) / 2, w: v.w * f, h: v.h * f }));
  const s = comps.find(c => c.ref === sel);
  return (<section aria-label="Schematic view"><h3>Schematic view</h3>
    <p style={{ fontSize: 13 }}>Drag parts to rearrange, drag the background to pan, click or press Enter on a part to inspect it. Positions are for viewing only; connectivity comes from the circuit data (change it with the editor below). Net “0” is ground.</p>
    {onChange && <p><button aria-pressed={wire} onClick={() => { setWire(w => !w); setFrom(null); setNote(""); }}>{wire ? "Wire mode: ON" : "Wire mode: off"}</button>{" "}
      <button disabled={!from} onClick={() => from && edit(groundPin(comps as NComp[], from), `${from.ref}.${from.pin} tied to ground (net 0)`)}>Ground selected pin</button>{" "}
      <button disabled={!from} onClick={() => from && edit(disconnectPin(comps as NComp[], from), `${from.ref}.${from.pin} disconnected`)}>Disconnect selected pin</button> <span role="status">{note}</span></p>}
    <button onClick={() => zoom(0.8)}>Zoom in</button> <button onClick={() => zoom(1.25)}>Zoom out</button> <button onClick={() => { setView({ x: 0, y: 0, w: 800, h: 420 }); setPos(init); }}>Reset view</button>
    <svg ref={svg} role="img" aria-label="Circuit schematic" viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} style={{ width: "100%", maxWidth: 800, height: 420, background: "#fff", border: "1px solid #ccc", touchAction: "none" }}
      onPointerDown={e => down(e, null)} onPointerMove={move} onPointerUp={() => up(null)}>
      {Object.entries(nets).map(([n, pts]) => { if (n === "0") return pts.map((p, i) => <g key={n + i}><line x1={p.x} y1={p.y} x2={p.x} y2={p.y + 12} stroke="#333" /><line x1={p.x - 8} y1={p.y + 12} x2={p.x + 8} y2={p.y + 12} stroke="#333" strokeWidth="2" /><text x={p.x} y={p.y + 26} fontSize="9" textAnchor="middle">GND</text></g>);
        const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length, cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
        return <g key={n}>{pts.length > 1 && pts.map((p, i) => <polyline key={i} fill="none" points={`${p.x},${p.y} ${cx},${p.y} ${cx},${cy}`} stroke="#0a6" strokeWidth="1.5" />)}<circle cx={cx} cy={cy} r="3" fill="#0a6" /><text x={cx + 5} y={cy - 5} fontSize="10" fill="#075">{n}</text></g>; })}
      {comps.map(c => { const p = P(c.ref), on = sel === c.ref; return (
        <g key={c.ref} role="button" tabIndex={0} aria-label={`${c.ref} ${c.kind} ${fmt(c.kind, c.value)}`} style={{ cursor: "grab" }} onPointerDown={e => down(e, c.ref)} onPointerUp={e => { e.stopPropagation(); up(c.ref); }} onKeyDown={e => { if (e.key === "Enter") setSel(c.ref); }}>
          <rect x={p.x - 40} y={p.y - 18} width="80" height="36" rx="4" fill={on ? "#e6f4ff" : "#fafafa"} stroke={on ? "#06c" : "#333"} strokeWidth={on ? 2 : 1} />
          <text x={p.x} y={p.y - 3} fontSize="11" textAnchor="middle" fontWeight="bold">{c.ref}</text><text x={p.x} y={p.y + 11} fontSize="10" textAnchor="middle">{c.kind === "LED" || c.kind === "D" ? c.kind : fmt(c.kind, c.value) || c.kind}</text>
          {ORDER[c.kind].map(pin => { const q = pinXY(c, pin); return <g key={pin}><circle cx={q.x} cy={q.y} r="3" fill={c.pins[pin] ? "#333" : "#c00"} />{wire && <circle role="button" aria-label={`pin ${c.ref}.${pin}`} cx={q.x} cy={q.y} r="8" fill={from?.ref === c.ref && from.pin === pin ? "#fc0" : "#06c"} fillOpacity="0.25" stroke={from?.ref === c.ref && from.pin === pin ? "#c60" : "none"} style={{ cursor: "crosshair" }} onPointerDown={e => e.stopPropagation()} onPointerUp={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); clickPin(c.ref, pin); }} />}<text x={q.x + (q.x < p.x ? -4 : 4)} y={q.y - 4} fontSize="8" textAnchor={q.x < p.x ? "end" : "start"} fill="#666">{pin}</text></g>; })}
        </g>); })}
    </svg>
    {s && <div role="region" aria-label="Selected part" style={{ border: "1px solid #999", padding: 8, maxWidth: 800 }}><b>{s.ref}</b> — kind {s.kind}{s.value != null && <>, value {fmt(s.kind, s.value)}</>}{s.rating != null && <>, rating {s.rating}</>}
      <br />Pins: {ORDER[s.kind].map(p => `${p}→${s.pins[p] ?? "UNCONNECTED"}`).join(", ")}<br /><i>Generic part: no manufacturer, datasheet or verified ratings are recorded; pick a real part and check its datasheet.</i> <button onClick={() => setSel(null)}>Close</button></div>}
  </section>);
}
