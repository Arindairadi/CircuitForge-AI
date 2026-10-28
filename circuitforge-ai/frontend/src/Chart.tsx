export default function Chart({ x, y, xl, yl }: { x: number[]; y: number[]; xl: string; yl: string }) {
  const W = 520, H = 240, m = 40;
  const [x0, x1] = [Math.min(...x), Math.max(...x)], [y0, y1] = [Math.min(...y, 0), Math.max(...y) || 1];
  const px = (v: number) => m + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * m), py = (v: number) => H - m - ((v - y0) / (y1 - y0 || 1)) * (H - 2 * m);
  const pts = x.map((v, i) => `${px(v).toFixed(1)},${py(y[i]).toFixed(1)}`).join(" ");
  return (<svg role="img" aria-label={`${yl} vs ${xl}`} viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: "100%", background: "#fff", border: "1px solid #ccc" }}>
    <line x1={m} y1={H - m} x2={W - m} y2={H - m} stroke="#333" /><line x1={m} y1={m} x2={m} y2={H - m} stroke="#333" />
    <polyline points={pts} fill="none" stroke="#0a6" strokeWidth="2" />
    <text x={W / 2} y={H - 8} fontSize="11" textAnchor="middle">{xl}: {x0.toExponential(1)} … {x1.toExponential(1)}</text>
    <text x={4} y={m} fontSize="11">{y1.toFixed(2)}</text><text x={4} y={H - m} fontSize="11">{y0.toFixed(2)}</text></svg>);
}
