export type Comp = { ref: string; kind: string; value: number | null; pins: Record<string, string>; rating?: number | null; pulse?: number[] | null; datasheet?: string | null };
export type PinRef = { ref: string; pin: string };

const clone = (cs: Comp[]): Comp[] => cs.map(c => ({ ...c, pins: { ...c.pins } }));
const netOf = (cs: Comp[], p: PinRef) => cs.find(c => c.ref === p.ref)?.pins[p.pin];

export function newNetName(cs: Comp[]): string {
  const used = new Set(cs.flatMap(c => Object.values(c.pins)));
  let i = 1; while (used.has(`N${i}`)) i++;
  return `N${i}`;
}

/** Connect two pins. Existing nets are reused; two different nets are merged (ground "0" always wins). Returns a new array. */
export function connectPins(cs: Comp[], a: PinRef, b: PinRef): { comps: Comp[]; net: string } {
  const out = clone(cs), na = netOf(out, a), nb = netOf(out, b);
  const set = (p: PinRef, n: string) => { const c = out.find(x => x.ref === p.ref); if (c) c.pins[p.pin] = n; };
  let net: string;
  if (na && nb && na !== nb) {
    net = na === "0" || nb === "0" ? "0" : na; const drop = net === na ? nb : na;
    out.forEach(c => Object.keys(c.pins).forEach(k => { if (c.pins[k] === drop) c.pins[k] = net; }));
  } else net = na ?? nb ?? newNetName(out);
  set(a, net); set(b, net);
  return { comps: out, net };
}

export function disconnectPin(cs: Comp[], p: PinRef): Comp[] {
  const out = clone(cs); const c = out.find(x => x.ref === p.ref); if (c) delete c.pins[p.pin]; return out;
}

/** Tie just this pin to ground (net "0"), leaving the rest of its former net intact. */
export function groundPin(cs: Comp[], p: PinRef): Comp[] {
  const out = clone(cs); const c = out.find(x => x.ref === p.ref); if (c) c.pins[p.pin] = "0"; return out;
}
