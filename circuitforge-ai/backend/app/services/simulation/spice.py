"""ngspice batch runner: validated netlist, tempdir isolation, timeout, resource limits. Never fabricates results."""
import re, resource, shutil, subprocess, tempfile
from pathlib import Path
from app.schemas.circuit import Circuit, REG_DROPOUT_V

LED_MODEL = ".model DLED D(IS=1.5e-19 N=2)"
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class SimulationError(Exception):
    pass


MODELS = {"D": ".model DGEN D(IS=1e-14 N=1 RS=0.5)", "Q": ".model QNPN NPN(BF=100 IS=1e-14 VAF=100)", "M": ".model MNMOS NMOS(LEVEL=1 VTO=2 KP=0.5)",
          "QP": ".model QPNP PNP(BF=100 IS=1e-14 VAF=100)", "MP": ".model MPMOS PMOS(LEVEL=1 VTO=-2 KP=0.25)"}


def to_netlist(c: Circuit, ac: bool = False) -> str:
    lines = [f"* {re.sub(r'[^A-Za-z0-9 .]', '', c.name)}"]
    for comp in c.components:
        for net in comp.pins.values():
            if not NAME_RE.match(net):
                raise SimulationError(f"Invalid net name {net!r}")
        p, r = comp.pins, comp.ref
        try:
            if comp.kind == "V":
                src = f"PULSE({' '.join(f'{x:g}' for x in comp.pulse)})" if comp.pulse else f"DC {comp.value:g}"
                lines.append(f"{r} {p['p']} {p['n']} {src}" + (" AC 1" if ac else ""))
            elif comp.kind in ("R", "C", "L"): lines.append(f"{r} {p['1']} {p['2']} {comp.value:.9g}")
            elif comp.kind == "LED": lines.append(f"{r} {p['a']} {p['k']} DLED")
            elif comp.kind == "D": lines.append(f"{r} {p['a']} {p['k']} DGEN")
            elif comp.kind == "Q": lines.append(f"{r} {p['c']} {p['b']} {p['e']} QNPN")
            elif comp.kind == "M": lines.append(f"{r} {p['d']} {p['g']} {p['s']} {p['s']} MNMOS")
            elif comp.kind == "QP": lines.append(f"{r} {p['c']} {p['b']} {p['e']} QPNP")
            elif comp.kind == "MP": lines.append(f"{r} {p['d']} {p['g']} {p['s']} {p['s']} MPMOS")
            elif comp.kind == "REG":
                lines.append(f"B{r} {r}_int {p['gnd']} V=min({comp.value:g}, max(V({p['in']},{p['gnd']})-{REG_DROPOUT_V:g}, 0))")
                lines.append(f"R{r}O {r}_int {p['out']} 0.05")
            elif comp.kind == "OA" and comp.value:   # single-supply rails: output limited to 0..value volts
                lines.append(f"B{r} {p['o']} 0 V=max(0, min({comp.value:g}, 1e5*(V({p['p']})-V({p['n']}))))")
            elif comp.kind == "OA": lines.append(f"E{r} {p['o']} 0 {p['p']} {p['n']} 1e6")
        except (KeyError, TypeError):
            raise SimulationError(f"{comp.ref} is incomplete (unconnected pin or missing value)")
    kinds = {x.kind for x in c.components}
    if "LED" in kinds: lines.append(LED_MODEL)
    lines += [MODELS[k] for k in ("D", "Q", "M", "QP", "MP") if k in kinds]
    return "\n".join(lines)


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))


def engine_version() -> str | None:
    exe = shutil.which("ngspice")
    if not exe: return None
    out = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=10).stdout
    m = re.search(r"ngspice-(\S+)", out)
    return m.group(1) if m else "unknown"


def _run(deck: str, timeout: float) -> str:
    exe = shutil.which("ngspice")
    if not exe: raise SimulationError("ngspice is not installed; simulation unavailable")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "d.cir").write_text(deck)
        try:
            r = subprocess.run([exe, "-b", "d.cir"], cwd=td, capture_output=True, text=True, timeout=timeout, preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            raise SimulationError(f"Simulation timed out after {timeout}s")
        out = r.stdout + r.stderr
        if re.search(r"(?i)(singular matrix|timestep too small|no convergence|fatal|Error:)", out):
            raise SimulationError("ngspice reported an error: " + out[-500:])
        wr = Path(td) / "o.txt"
        return out + ("\n@@WR@@\n" + wr.read_text() if wr.exists() else "")


PROBE = {"R": "@{r}[i]", "LED": "@{r}[id]", "D": "@{r}[id]", "Q": "@{r}[ic]", "M": "@{r}[id]", "L": "@{r}[i]", "QP": "@{r}[ic]", "MP": "@{r}[id]"}


def operating_point(c: Circuit, timeout: float = 15) -> dict:
    nets = sorted(n for n in c.nets() if n != "0")
    probes = [PROBE[x.kind].format(r=x.ref.lower()) for x in c.components if x.kind in PROBE]
    ctl = "\n".join([f"print v({n})" for n in nets if not n.endswith("_int")] + [f"print i({x.ref})" for x in c.components if x.kind == "V"] + [f"print {p}" for p in probes]
                     + [f"print i(b{x.ref.lower()})" for x in c.components if x.kind == "REG"])
    out = _run(f"{to_netlist(c)}\n.op\n.control\nrun\n{ctl}\nquit\n.endc\n.end\n", timeout)
    volts, cur, comp = {}, {}, {}
    for m in re.finditer(r"^v\((\w+)\)\s*=\s*(\S+)", out, re.M | re.I): volts[m.group(1).lower()] = float(m.group(2))
    for m in re.finditer(r"^i\((\w+)\)\s*=\s*(\S+)", out, re.M | re.I): cur[m.group(1).upper()] = float(m.group(2))
    for m in re.finditer(r"^@(\w+)\[\w+\]\s*=\s*(\S+)", out, re.M | re.I): comp[m.group(1).upper()] = float(m.group(2))
    for x in c.components:
        if x.kind == "REG" and ("B" + x.ref) in cur: comp[x.ref] = abs(cur.pop("B" + x.ref))   # regulator output current
    if nets and not volts: raise SimulationError("Could not parse ngspice output")
    expected = {x.ref for x in c.components if x.kind in PROBE or x.kind == "REG"}
    if expected - set(comp): raise SimulationError(f"No current reported for {sorted(expected - set(comp))}")
    return {"analysis": "op", "engine": "ngspice " + str(engine_version()), "node_voltages": volts, "source_currents": cur, "component_currents": comp,
            "note": "DC operating point at t=0 (pulse sources at their initial value); peak transient currents are not covered"}


def transient(c: Circuit, node: str, tstep: float, tstop: float, timeout: float = 20) -> dict:
    if not NAME_RE.match(node) or node not in c.nets(): raise SimulationError(f"Unknown node {node!r}")
    if not (0 < tstep < tstop) or tstop / tstep > 200000: raise SimulationError("Invalid time settings")
    ctl = f"tran {tstep:g} {tstop:g} uic\nwrdata o.txt v({node})\nquit"
    out = _run(f"{to_netlist(c)}\n.control\n{ctl}\n.endc\n.end\n", timeout)
    data = out.split("@@WR@@\n", 1)[-1] if "@@WR@@" in out else ""
    t, v = [], []
    for line in data.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try: t.append(float(parts[0])); v.append(float(parts[1]))
            except ValueError: pass
    if not t: raise SimulationError("Simulation produced no data")
    return {"analysis": "tran", "engine": "ngspice " + str(engine_version()), "node": node, "time": t, "voltage": v}


def ac(c: Circuit, node: str, fstart: float, fstop: float, points: int = 20, timeout: float = 20) -> dict:
    import math
    if not NAME_RE.match(node) or node not in c.nets(): raise SimulationError(f"Unknown node {node!r}")
    if not (0 < fstart < fstop) or not (1 <= points <= 200): raise SimulationError("Invalid frequency settings")
    ctl = f"ac dec {points} {fstart:g} {fstop:g}\nwrdata o.txt v({node})\nquit"
    out = _run(f"{to_netlist(c, ac=True)}\n.control\n{ctl}\n.endc\n.end\n", timeout)
    f, mag = [], []
    for line in (out.split("@@WR@@\n", 1)[-1] if "@@WR@@" in out else "").strip().splitlines():
        a = line.split()
        if len(a) >= 3:
            try: re_, im = float(a[1]), float(a[2]); f.append(float(a[0])); mag.append(20 * math.log10(max(math.hypot(re_, im), 1e-30)))
            except ValueError: pass
    if not f: raise SimulationError("Simulation produced no data")
    return {"analysis": "ac", "engine": "ngspice " + str(engine_version()), "node": node, "freq_hz": f, "magnitude_db": mag,
            "note": "Source AC amplitude 1 V; magnitude is v(node)/1 V"}


def _xy(out: str) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for line in (out.split("@@WR@@\n", 1)[-1] if "@@WR@@" in out else "").strip().splitlines():
        a = line.split()
        if len(a) >= 2:
            try: xs.append(float(a[0])); ys.append(float(a[1]))
            except ValueError: pass
    if not xs: raise SimulationError("Simulation produced no data")
    return xs, ys


def dc_sweep(c: Circuit, source: str, node: str, start: float, stop: float, step: float, timeout: float = 20) -> dict:
    if source not in {x.ref for x in c.components if x.kind == "V"}: raise SimulationError(f"{source!r} is not a voltage source in this design")
    if not NAME_RE.match(node) or node not in c.nets(): raise SimulationError(f"Unknown node {node!r}")
    if step == 0 or (stop - start) / step <= 0 or abs((stop - start) / step) > 2000: raise SimulationError("Invalid sweep settings (need step sign to match direction, <= 2000 points)")
    out = _run(f"{to_netlist(c)}\n.control\ndc {source} {start:g} {stop:g} {step:g}\nwrdata o.txt v({node})\nquit\n.endc\n.end\n", timeout)
    x, y = _xy(out)
    return {"analysis": "dc", "engine": "ngspice " + str(engine_version()), "source": source, "node": node, "x": x, "voltage": y}


def param_sweep(c: Circuit, ref: str, start: float, stop: float, points: int, node: str) -> dict:
    comp = next((x for x in c.components if x.ref == ref), None)
    if comp is None or comp.kind not in ("R", "C", "L", "V"): raise SimulationError(f"{ref!r} is not a sweepable component (R, C, L or V)")
    if not (2 <= points <= 50) or start <= 0 or stop <= start: raise SimulationError("Need 2-50 points and 0 < start < stop")
    if node not in c.nets() or not NAME_RE.match(node): raise SimulationError(f"Unknown node {node!r}")
    vals = [start + (stop - start) * i / (points - 1) for i in range(points)]
    volts = []
    for v in vals:
        cc = c.model_copy(deep=True); next(x for x in cc.components if x.ref == ref).value = v
        volts.append(operating_point(cc)["node_voltages"][node.lower()] if node != "0" else 0.0)
    return {"analysis": "psweep", "engine": "ngspice " + str(engine_version()), "ref": ref, "node": node, "values": vals, "voltage": volts}
