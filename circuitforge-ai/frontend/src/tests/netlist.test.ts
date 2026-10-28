import { connectPins, disconnectPin, groundPin, newNetName, type Comp } from "../netlist";

const base = (): Comp[] => [
  { ref: "V1", kind: "V", value: 5, pins: { p: "vcc", n: "0" } },
  { ref: "R1", kind: "R", value: 330, pins: { "1": "vcc" } },
  { ref: "R2", kind: "R", value: 1000, pins: {} },
  { ref: "R3", kind: "R", value: 1000, pins: { "1": "a", "2": "b" } },
];

test("connecting two unconnected pins creates a fresh net and does not mutate the input", () => {
  const cs = base(), r = connectPins(cs, { ref: "R2", pin: "1" }, { ref: "R2", pin: "2" });
  expect(r.net).toBe("N1"); expect(r.comps[2].pins).toEqual({ "1": "N1", "2": "N1" }); expect(cs[2].pins).toEqual({});
});

test("connecting to an existing net reuses it", () => {
  const r = connectPins(base(), { ref: "R1", pin: "1" }, { ref: "R1", pin: "2" });
  expect(r.net).toBe("vcc"); expect(r.comps[1].pins).toEqual({ "1": "vcc", "2": "vcc" });
});

test("two different nets are merged everywhere, and ground wins", () => {
  const m = connectPins(base(), { ref: "R3", pin: "1" }, { ref: "R3", pin: "2" });
  expect(m.net).toBe("a"); expect(m.comps[3].pins).toEqual({ "1": "a", "2": "a" });
  const g = connectPins(base(), { ref: "V1", pin: "n" }, { ref: "R3", pin: "1" });
  expect(g.net).toBe("0"); expect(g.comps[3].pins["1"]).toBe("0");
  const merged = connectPins([{ ref: "R3", kind: "R", value: 1, pins: { "1": "a", "2": "b" } }, { ref: "R4", kind: "R", value: 1, pins: { "1": "b", "2": "a" } }], { ref: "R3", pin: "1" }, { ref: "R3", pin: "2" });
  expect(merged.comps[1].pins).toEqual({ "1": "a", "2": "a" });   // every pin on the dropped net was renamed
});

test("net names never collide, disconnect removes a single pin, ground ties only that pin", () => {
  expect(newNetName([{ ref: "R1", kind: "R", value: 1, pins: { "1": "N1", "2": "N2" } }])).toBe("N3");
  expect(disconnectPin(base(), { ref: "R3", pin: "1" })[3].pins).toEqual({ "2": "b" });
  const g = groundPin(base(), { ref: "R1", pin: "1" }); expect(g[1].pins["1"]).toBe("0"); expect(g[0].pins.p).toBe("vcc");
});
