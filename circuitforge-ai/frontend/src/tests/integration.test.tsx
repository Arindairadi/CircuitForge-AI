// Frontend <-> real backend integration (jsdom + real HTTP). Skipped unless CF_API is set; run via scripts/integration.sh
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "../App";
import { setToken } from "../api";

const API = process.env.CF_API ?? "";
const realFetch = globalThis.fetch;

describe.skipIf(!API)("UI against a live backend", () => {
  beforeAll(() => { vi.stubGlobal("fetch", (u: any, i: any) => realFetch(API + String(u).replace(/^\/api/, ""), i)); sessionStorage.clear(); setToken(""); });
  afterAll(() => vi.unstubAllGlobals());

  test("register, create a divider, simulate, verify, sweep, edit a value, re-simulate, read the audit log", async () => {
    const long = { timeout: 20000 };
    render(<App />);
    await userEvent.type(screen.getByLabelText(/email/i), `ui${Date.now()}@example.com`); await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-1");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    expect(await screen.findByText(/no projects yet/i, undefined, long)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Name"), "Divider"); await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "voltage_divider");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await userEvent.click(await screen.findByRole("link", { name: "Divider" }, long));
    expect(await screen.findByText(/Simulation:/, undefined, long)).toBeInTheDocument();
    expect(screen.getByText(/nothing here is safety certification/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Simulate (operating point)" }));
    expect(await screen.findByText(/"out": 2\.5/, undefined, long)).toBeInTheDocument();               // real ngspice result rendered by the UI
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/Passing automated checks is not safety/, undefined, long)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /DC sweep/ }));
    expect(await screen.findByRole("img", { name: "V vs V1 (V)" }, long)).toBeInTheDocument();

    const r2 = screen.getByLabelText("value R2"); await userEvent.clear(r2); await userEvent.type(r2, "20000");
    await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
    expect(await screen.findByText(/\(v2\)/, undefined, long)).toBeInTheDocument();
    expect(screen.queryByText(/"out": 2\.5/)).toBeNull();                                                  // old results are not carried over to the new version
    await userEvent.click(screen.getByRole("button", { name: "Simulate (operating point)" }));
    expect(await screen.findByText(/"out": 3\.33/, undefined, long)).toBeInTheDocument();                  // 5 V * 20k / 30k
    await userEvent.click(screen.getByRole("button", { name: "Show audit log" }));
    expect(await screen.findByText(/circuit\.update/, undefined, long)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText(/project\.create/).length).toBeGreaterThan(0));
  }, 90000);
});
