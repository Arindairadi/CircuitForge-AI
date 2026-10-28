import { useEffect, useRef, useState } from "react";

export type Layout = { board: { x0: number; y0: number; x1: number; y1: number }; parts: { ref: string; kind: string; x: number; y: number; w: number; h: number }[]; pitch_mm: number };
// Typical through-hole package heights in mm (approximate; NOT taken from a datasheet or KiCad 3D models)
export const HEIGHT: Record<string, number> = { R: 2.5, C: 5, L: 5, LED: 9, D: 3, Q: 5, QP: 5, M: 10, MP: 10, REG: 10, V: 8.5, OA: 4 };
export const THICKNESS = 1.6;

export function sceneBoxes(layout: Layout) {
  const { board: b } = layout;
  return { board: { w: b.x1 - b.x0, d: b.y1 - b.y0, cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2, t: THICKNESS },
    boxes: layout.parts.map(p => ({ ref: p.ref, kind: p.kind, cx: p.x, cy: p.y, w: Math.max(p.w, 0.5), d: Math.max(p.h, 0.5), height: HEIGHT[p.kind] ?? 4 })) };
}

export default function Pcb3D({ layout }: { layout: Layout }) {
  const host = useRef<HTMLDivElement>(null), [err, setErr] = useState(""), view = useRef({ theta: 0.7, phi: 0.9, dist: 0 });
  const scene = sceneBoxes(layout);
  useEffect(() => {
    let disposed = false, cleanup = () => {};
    (async () => {
      try {
        const THREE = await import("three");
        if (disposed || !host.current) return;
        const renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setSize(host.current.clientWidth || 640, 360); host.current.appendChild(renderer.domElement);
        const sc = new THREE.Scene(); sc.background = new THREE.Color(0xf4f4f4); sc.add(new THREE.AmbientLight(0xffffff, 0.7)); const sun = new THREE.DirectionalLight(0xffffff, 0.8); sun.position.set(50, 120, 60); sc.add(sun);
        const mk = (w: number, h: number, d: number, color: number, x: number, y: number, z: number) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshLambertMaterial({ color })); m.position.set(x, y, z); sc.add(m); };
        mk(scene.board.w, scene.board.t, scene.board.d, 0x1b5e20, scene.board.cx, -scene.board.t / 2, scene.board.cy);
        scene.boxes.forEach(b => mk(b.w, b.height, b.d, 0x37474f, b.cx, b.height / 2, b.cy));
        const cam = new THREE.PerspectiveCamera(40, (host.current.clientWidth || 640) / 360, 1, 2000), v = view.current; v.dist = Math.max(scene.board.w, scene.board.d) * 1.3;
        const draw = () => { cam.position.set(scene.board.cx + v.dist * Math.sin(v.phi) * Math.sin(v.theta), v.dist * Math.cos(v.phi), scene.board.cy + v.dist * Math.sin(v.phi) * Math.cos(v.theta)); cam.lookAt(scene.board.cx, 0, scene.board.cy); renderer.render(sc, cam); };
        let down = false, lx = 0, ly = 0; const el = renderer.domElement;
        const pd = (e: PointerEvent) => { down = true; lx = e.clientX; ly = e.clientY; }, pu = () => { down = false; };
        const pm = (e: PointerEvent) => { if (!down) return; v.theta -= (e.clientX - lx) * 0.01; v.phi = Math.min(1.5, Math.max(0.15, v.phi - (e.clientY - ly) * 0.01)); lx = e.clientX; ly = e.clientY; draw(); };
        const wh = (e: WheelEvent) => { e.preventDefault(); v.dist = Math.min(1500, Math.max(20, v.dist * (e.deltaY > 0 ? 1.1 : 0.9))); draw(); };
        el.addEventListener("pointerdown", pd); window.addEventListener("pointerup", pu); el.addEventListener("pointermove", pm); el.addEventListener("wheel", wh, { passive: false }); draw();
        cleanup = () => { el.removeEventListener("pointerdown", pd); window.removeEventListener("pointerup", pu); el.removeEventListener("pointermove", pm); el.removeEventListener("wheel", wh); renderer.dispose(); el.remove(); };
      } catch { if (!disposed) setErr("The 3D view needs WebGL, which is not available in this browser."); }
    })();
    return () => { disposed = true; cleanup(); };
  }, [layout]);
  return (<section aria-label="3D board view"><h4>3D board view (approximate)</h4>
    <p style={{ fontSize: 13 }}>Board outline and parts as boxes from the generated layout, with typical package heights. This is not the KiCad 3D model view. Drag to rotate, scroll to zoom.</p>
    {err ? <p role="alert">{err}</p> : <div ref={host} style={{ width: "100%", maxWidth: 800, height: 360, border: "1px solid #ccc" }} />}
    <ul style={{ fontSize: 12 }}>{scene.boxes.map(b => <li key={b.ref}>{b.ref} ({b.kind}): {b.w.toFixed(1)}×{b.d.toFixed(1)} mm, ~{b.height} mm tall</li>)}</ul></section>);
}
