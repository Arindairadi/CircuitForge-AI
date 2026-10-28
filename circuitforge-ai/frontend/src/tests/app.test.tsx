import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach, afterEach } from "vitest";
import App from "../App";
import { setToken } from "../api";
import Editor from "../Editor";
import Chart from "../Chart";

const circuit = { name: "t", version: 1, assumptions: [], components: [
  { ref: "V1", kind: "V", value: 5, pins: { p: "vcc", n: "0" } }, { ref: "R1", kind: "R", value: 330, pins: { "1": "vcc", "2": "0" } }] };

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
beforeEach(() => { sessionStorage.clear(); setToken(""); });
afterEach(() => vi.restoreAllMocks());

test("login failure shows the server error", async () => {
  vi.stubGlobal("fetch", vi.fn(() => json({ detail: "Invalid credentials" }, 401)));
  render(<App />);
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co"); await userEvent.type(screen.getByLabelText(/password/i), "password1");
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
});

test("login success then empty project list, create-project and navigation", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => { calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/auth/login")) return json({ access_token: "tok" }); if (url.endsWith("/projects") && init?.method === "POST") return json({ id: 1 }, 201);
    if (url.endsWith("/projects")) return json([]); if (url.includes("/learning/")) return json({ purpose: "P", principle: "Q", formula: "F", experiments: ["e1"], safety: ["s1"], glossary: { Vf: "x" } });
    return json({}); }));
  render(<App />);
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co"); await userEvent.type(screen.getByLabelText(/password/i), "password1");
  await userEvent.click(screen.getByRole("button", { name: /log in/i }));
  expect(await screen.findByText(/no projects yet/i)).toBeInTheDocument();
  await userEvent.type(screen.getByPlaceholderText("Name"), "My LED"); await userEvent.click(screen.getByRole("button", { name: "Create" }));
  await waitFor(() => expect(calls).toContain("POST /api/projects"));
  await userEvent.click(screen.getByRole("button", { name: "learn" }));
  expect(await screen.findByText(/Learning center/)).toBeInTheDocument(); expect(await screen.findByText("F")).toBeInTheDocument();
});

test("editor tracks pending changes, supports remove with confirmation, and saves the edited circuit", async () => {
  const onSave = vi.fn(); vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<Editor circuit={circuit} busy={false} onSave={onSave} />);
  expect(screen.getByText(/no pending changes/i)).toBeInTheDocument();
  const v = screen.getByLabelText("value R1"); await userEvent.clear(v); await userEvent.type(v, "470");
  expect(screen.getByText("changed R1")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
  expect(onSave.mock.calls[0][0].components.find((c: any) => c.ref === "R1").value).toBe(470);
  await userEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
  expect(screen.getByText("removed V1")).toBeInTheDocument();
});

test("editor add-part button needs a valid reference", async () => {
  render(<Editor circuit={circuit} busy={false} onSave={vi.fn()} />);
  const add = screen.getByRole("button", { name: "Add part" }); expect(add).toBeDisabled();
  await userEvent.type(screen.getByPlaceholderText(/Ref e.g./), "r9"); expect(add).toBeEnabled();
  await userEvent.click(add); expect(screen.getByText("added R9 (R)")).toBeInTheDocument();
});

test("chart renders an accessible svg for simulation data", () => {
  render(<Chart x={[0, 1, 2]} y={[0, 2.5, 5]} xl="time (s)" yl="V" />);
  expect(screen.getByRole("img", { name: "V vs time (s)" })).toBeInTheDocument();
});

import Schematic from "../Schematic";
import { fireEvent } from "@testing-library/react";

const sch: any = { components: [
  { ref: "V1", kind: "V", value: 5, pins: { p: "vcc", n: "0" } }, { ref: "R1", kind: "R", value: 330, pins: { "1": "vcc", "2": "led_a" } },
  { ref: "D1", kind: "LED", value: null, rating: 0.02, pins: { a: "led_a" } }] };

test("schematic shows parts, ground symbols and nets from the circuit data", () => {
  const { container } = render(<Schematic circuit={sch} />);
  expect(screen.getByRole("button", { name: "V1 V 5V" })).toBeInTheDocument(); expect(screen.getByRole("button", { name: "R1 R 330Ω" })).toBeInTheDocument();
  expect(container.textContent).toContain("GND"); expect(container.textContent).toContain("led_a"); expect(container.textContent).toContain("vcc");
});

test("selecting a part (click or Enter) shows its pins; unconnected pins are flagged; no datasheet is invented", async () => {
  render(<Schematic circuit={sch} />);
  await userEvent.click(screen.getByRole("button", { name: /^D1 LED/ }));
  const region = screen.getByRole("region", { name: "Selected part" });
  expect(region).toHaveTextContent("a→led_a"); expect(region).toHaveTextContent("k→UNCONNECTED"); expect(region).toHaveTextContent(/no manufacturer, datasheet/i);
  await userEvent.click(screen.getByRole("button", { name: "Close" })); expect(screen.queryByRole("region", { name: "Selected part" })).toBeNull();
  const r1 = screen.getByRole("button", { name: /^R1 R/ }); r1.focus(); fireEvent.keyDown(r1, { key: "Enter" });
  expect(screen.getByRole("region", { name: "Selected part" })).toHaveTextContent("R1");
});

test("schematic zoom controls change the view box and reset restores it", async () => {
  render(<Schematic circuit={sch} />);
  const svg = screen.getByRole("img", { name: "Circuit schematic" }); const before = svg.getAttribute("viewBox");
  await userEvent.click(screen.getByRole("button", { name: "Zoom in" })); expect(svg.getAttribute("viewBox")).not.toBe(before);
  await userEvent.click(screen.getByRole("button", { name: "Reset view" })); expect(svg.getAttribute("viewBox")).toBe(before);
});

test("import rejects files over 1 MB without calling the API", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => { calls.push(`${init?.method ?? "GET"} ${url}`); return url.endsWith("/auth/login") ? json({ access_token: "t" }) : url.endsWith("/projects") ? json([]) : json({}); }));
  render(<App />);
  await userEvent.type(screen.getByLabelText(/email/i), "a@b.co"); await userEvent.type(screen.getByLabelText(/password/i), "password1");
  await userEvent.click(screen.getByRole("button", { name: /log in/i })); await screen.findByText(/no projects yet/i);
  const f = new File(["{}"], "big.json", { type: "application/json" }); Object.defineProperty(f, "size", { value: 2_000_000 });
  await userEvent.upload(screen.getByLabelText("Import project file"), f);
  expect(await screen.findByRole("alert")).toHaveTextContent(/too large/i); expect(calls.some(c => c.includes("/projects/import"))).toBe(false);
});

import { useState } from "react";

function Harness({ spy }: { spy?: (c: any[]) => void }) {
  const [d, setD] = useState<any[]>(sch.components);
  return (<><Schematic circuit={{ components: d }} onChange={c => { spy?.(c); setD(c); }} /><Editor circuit={sch} draft={d} setDraft={setD} busy={false} onSave={vi.fn()} /></>);
}

test("wiring on the canvas: pins are inert until wire mode is on", async () => {
  render(<Harness />);
  expect(screen.queryByRole("button", { name: "pin D1.k" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Wire mode: off" }));
  expect(screen.getByRole("button", { name: "pin D1.k" })).toBeInTheDocument();
});

test("click two pins to connect them; the editor shows the pending change", async () => {
  const spy = vi.fn(); render(<Harness spy={spy} />);
  await userEvent.click(screen.getByRole("button", { name: "Wire mode: off" }));
  await userEvent.click(screen.getByRole("button", { name: "pin D1.k" })); expect(screen.getByRole("status")).toHaveTextContent("Selected D1.k");
  await userEvent.click(screen.getByRole("button", { name: "pin R1.2" }));
  const next = spy.mock.calls[0][0]; expect(next.find((c: any) => c.ref === "D1").pins.k).toBe("led_a");   // joined the existing net
  expect(screen.getByRole("status")).toHaveTextContent("Connected D1.k to R1.2 on net led_a");
  expect(screen.getByText("changed D1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /save as new version/i })).toBeEnabled();
});

test("ground and disconnect buttons act on the selected pin and are disabled without one", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "Wire mode: off" }));
  expect(screen.getByRole("button", { name: "Ground selected pin" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "pin D1.k" })); await userEvent.click(screen.getByRole("button", { name: "Ground selected pin" }));
  expect(screen.getByRole("status")).toHaveTextContent("D1.k tied to ground"); expect(screen.getByLabelText("D1 pin k")).toHaveValue("0");
  await userEvent.click(screen.getByRole("button", { name: "pin R1.1" })); await userEvent.click(screen.getByRole("button", { name: "Disconnect selected pin" }));
  expect(screen.getByLabelText("R1 pin 1")).toHaveValue("");
});

test("clicking the same pin twice cancels the selection", async () => {
  const spy = vi.fn(); render(<Harness spy={spy} />);
  await userEvent.click(screen.getByRole("button", { name: "Wire mode: off" }));
  await userEvent.click(screen.getByRole("button", { name: "pin R1.2" })); await userEvent.click(screen.getByRole("button", { name: "pin R1.2" }));
  expect(spy).not.toHaveBeenCalled(); expect(screen.getByRole("button", { name: "Ground selected pin" })).toBeDisabled();
});

test("editor keeps an op-amp's supply-rail value when other parts are edited and saved", async () => {
  const onSave = vi.fn();
  const c = { name: "t", version: 1, assumptions: [], components: [
    { ref: "OA1", kind: "OA", value: 5, pins: { p: "in", n: "inv", o: "out" } }, { ref: "R1", kind: "R", value: 9000, pins: { "1": "out", "2": "inv" } }] };
  render(<Editor circuit={c} busy={false} onSave={onSave} />);
  expect(screen.getByLabelText("value OA1")).toHaveValue("5");
  const v = screen.getByLabelText("value R1"); await userEvent.clear(v); await userEvent.type(v, "4700");
  await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
  const saved = onSave.mock.calls[0][0].components; expect(saved.find((x: any) => x.ref === "OA1").value).toBe(5); expect(saved.find((x: any) => x.ref === "R1").value).toBe(4700);
});

import Pcb3D, { sceneBoxes, HEIGHT } from "../Pcb3D";
import { BomPanel, Datasheets } from "../Parts";

const layout = { board: { x0: 0, y0: -14, x1: 60, y1: 14 }, pitch_mm: 25, parts: [
  { ref: "R1", kind: "R", x: 20, y: 0, w: 12, h: 4 }, { ref: "M1", kind: "M", x: 45, y: 0, w: 10.5, h: 4.7 }, { ref: "Z1", kind: "UNKNOWN", x: 5, y: 0, w: 0, h: 0 }] };

test("3D scene geometry comes from the layout with typical heights and minimum sizes", () => {
  const s = sceneBoxes(layout);
  expect(s.board).toMatchObject({ w: 60, d: 28, cx: 30, cy: 0, t: 1.6 });
  expect(s.boxes.find(b => b.ref === "R1")).toMatchObject({ cx: 20, w: 12, d: 4, height: HEIGHT.R });
  expect(s.boxes.find(b => b.ref === "M1")!.height).toBe(HEIGHT.M);
  expect(s.boxes.find(b => b.ref === "Z1")).toMatchObject({ w: 0.5, d: 0.5, height: 4 });   // unknown kind gets a default, zero size is clamped
});

test("3D view is honest about being approximate and degrades gracefully without WebGL", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(<Pcb3D layout={layout} />);
  expect(screen.getByText(/not the KiCad 3D model view/i)).toBeInTheDocument();
  expect(await screen.findByRole("alert")).toHaveTextContent(/needs WebGL/i);          // jsdom has no WebGL
  expect(screen.getByText(/M1 \(M\): 10\.5×4\.7 mm/)).toBeInTheDocument();
});

test("BOM panel: shows rows, saves an assignment as user-entered, and surfaces server errors", async () => {
  const calls: { m: string; u: string; b?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => { calls.push({ m: init?.method ?? "GET", u: url, b: init?.body as string });
    if (url.endsWith("/bom") ) return json([{ references: "R1", quantity: 1, category: "resistor", value: "330Ω", footprint: "axial", manufacturer: "", mpn: "", notes: "Generic part; select a real MPN before ordering. Price/stock not verified." }]);
    if (url.endsWith("/bom/parts") && init?.method === "PUT") return calls.filter(c => c.m === "PUT").length > 1 ? json({ detail: "R9 is not in the current design" }, 422) : json({ ref: "R1" });
    return json({}); }));
  render(<BomPanel id={7} comps={[{ ref: "R1" }, { ref: "R2" }]} />);
  await userEvent.click(screen.getByRole("button", { name: "Show BOM" }));
  expect(await screen.findByText(/Generic part; select a real MPN/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("mpn"), "AR-330"); await userEvent.click(screen.getByRole("button", { name: "Save assignment" }));
  await waitFor(() => expect(calls.some(c => c.m === "PUT")).toBe(true));
  const put = calls.find(c => c.m === "PUT")!; expect(JSON.parse(put.b!)).toMatchObject({ ref: "R1", mpn: "AR-330", manufacturer: null, price: null });   // empty fields are sent as null, not invented
  expect(await screen.findByRole("status")).toHaveTextContent("Saved R1 (user-entered)");
  await userEvent.click(screen.getByRole("button", { name: "Save assignment" }));
  expect(await screen.findByText(/R9 is not in the current design/)).toBeInTheDocument();
  expect(screen.getByText(/does not verify datasheets, prices or stock/i)).toBeInTheDocument();
});

test("supplier lookup shows the server's honest failure when no API key is configured", async () => {
  vi.stubGlobal("fetch", vi.fn(() => json({ detail: "MOUSER_API_KEY is not configured" }, 503)));
  render(<BomPanel id={1} comps={[{ ref: "R1" }]} />);
  await userEvent.type(screen.getByLabelText("lookup part number"), "AR-330"); await userEvent.click(screen.getByRole("button", { name: "Look up" }));
  expect(await screen.findByRole("status")).toHaveTextContent("MOUSER_API_KEY is not configured");
});

test("datasheet upload rejects oversized files client-side without calling the API", async () => {
  const f = vi.fn(() => json([])); vi.stubGlobal("fetch", f);
  render(<Datasheets id={3} />);
  const big = new File(["%PDF-"], "big.pdf", { type: "application/pdf" }); Object.defineProperty(big, "size", { value: 6 * 1024 * 1024 });
  await userEvent.upload(screen.getByLabelText("Upload datasheet"), big);
  expect(await screen.findByRole("status")).toHaveTextContent(/too large/i); expect(f).not.toHaveBeenCalled();
});
