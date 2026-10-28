"""KiCad 7 schematic generation + validation through kicad-cli (version 7.0.x). Symbols come from KiCad's standard libraries;
nets are applied with labels placed exactly on pin endpoints. The result is round-trip checked via a kicad-cli netlist export."""
import re, shutil, subprocess, tempfile, uuid
from pathlib import Path
from app.schemas.circuit import Circuit

SYMDIR = Path("/usr/share/kicad/symbols")
# our kind -> (library, symbol, {our pin -> KiCad pin number})
MAP = {"R": ("Device", "R", {"1": "1", "2": "2"}), "C": ("Device", "C", {"1": "1", "2": "2"}),
       "LED": ("Device", "LED", {"k": "1", "a": "2"}), "V": ("Simulation_SPICE", "VDC", {"p": "1", "n": "2"}),
       "D": ("Device", "D", {"k": "1", "a": "2"}), "Q": ("Device", "Q_NPN_BCE", {"b": "1", "c": "2", "e": "3"}),
       "M": ("Device", "Q_NMOS_GSD", {"g": "1", "s": "2", "d": "3"}), "L": ("Device", "L", {"1": "1", "2": "2"}),
       "OA": ("Simulation_SPICE", "OPAMP", {"p": "1", "n": "2", "o": "5"}),
       "QP": ("Device", "Q_PNP_BCE", {"b": "1", "c": "2", "e": "3"}), "MP": ("Device", "Q_PMOS_GSD", {"g": "1", "s": "2", "d": "3"}),
       "REG": ("Regulator_Linear", "LM7805_TO220", {"in": "1", "gnd": "2", "out": "3"})}


class KicadError(Exception):
    pass


def available() -> str | None:
    exe = shutil.which("kicad-cli")
    if not exe: return None
    return subprocess.run([exe, "version"], capture_output=True, text=True, timeout=20).stdout.strip()


def _symbol(lib: str, name: str) -> tuple[str, dict[str, tuple[float, float]]]:
    f = SYMDIR / f"{lib}.kicad_sym"
    if not f.exists(): raise KicadError(f"KiCad symbol library {lib} not found at {f}")
    t = f.read_text(); i = t.find(f'(symbol "{name}"')
    if i < 0: raise KicadError(f"Symbol {lib}:{name} not found")
    d = 0
    for j in range(i, len(t)):
        d += (t[j] == "(") - (t[j] == ")")
        if d == 0: break
    s = t[i:j + 1]
    pins = {m.group(4): (float(m.group(1)), float(m.group(2))) for m in
            re.finditer(r'\(pin \w+ \w+\s+\(at ([-\d.]+) ([-\d.]+) (\d+)\).*?\(number "(\w+)"', s, re.S)}
    return s.replace(f'(symbol "{name}"', f'(symbol "{lib}:{name}"', 1), pins


def _val(kind: str, v: float | None) -> str:
    from app.services.reporting.bom import _fmt
    return _fmt(kind, v).replace("ohm", "")


def build_schematic(c: Circuit) -> str:
    libs, body, labels, used = {}, [], [], set()
    for idx, comp in enumerate(c.components):
        lib, name, pinmap = MAP[comp.kind]
        sym, pins = _symbol(lib, name); libs[f"{lib}:{name}"] = sym
        x, y = round(50.8 + idx * 25.4, 2), 101.6
        pin_lines = "".join(f'(pin "{n}" (uuid {uuid.uuid4()}))' for n in pins)
        body.append(f'(symbol (lib_id "{lib}:{name}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid {uuid.uuid4()}) '
                    f'(property "Reference" "{comp.ref}" (at {x + 3} {y - 5} 0) (effects (font (size 1.27 1.27)))) '
                    f'(property "Value" "{_val(comp.kind, comp.value)}" (at {x + 3} {y + 5} 0) (effects (font (size 1.27 1.27)))) '
                    f'(property "Footprint" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide)) {pin_lines})')
        for ours, num in pinmap.items():
            net = comp.pins.get(ours)
            if net is None: raise KicadError(f"{comp.ref}.{ours} is unconnected; fix the design before export")
            px, py = pins[num]
            labels.append(f'(label "{net}" (at {round(x + px, 2)} {round(y - py, 2)} 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid {uuid.uuid4()}))')
    return (f'(kicad_sch (version 20230121) (generator circuitforge) (uuid {uuid.uuid4()}) (paper "A4") (lib_symbols {" ".join(libs.values())}) '
            + " ".join(body + labels) + ' (sheet_instances (path "/" (page "1"))))')


def _cli(*args: str, timeout=90):
    exe = shutil.which("kicad-cli")
    if not exe: raise KicadError("kicad-cli is not installed")
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise KicadError(f"kicad-cli failed: {(r.stdout + r.stderr)[-400:]}")
    return r


def export_and_validate(c: Circuit, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    sch = outdir / "design.kicad_sch"; sch.write_text(build_schematic(c))
    net, pdf = outdir / "design.net", outdir / "design.pdf"
    _cli("sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(net), str(sch))
    got = {}
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)(?=\n\s*\(net \(code|\Z)', net.read_text(), re.S):
        for n in re.finditer(r'\(node \(ref "(\w+)"\) \(pin "(\w+)"\)', m.group(2)):
            got[(n.group(1), n.group(2))] = m.group(1).lstrip("/")
    mismatches = []
    for comp in c.components:
        for ours, num in MAP[comp.kind][2].items():
            if got.get((comp.ref, num)) != comp.pins[ours]:
                mismatches.append(f"{comp.ref}.{ours}: expected net {comp.pins[ours]!r}, KiCad has {got.get((comp.ref, num))!r}")
    _cli("sch", "export", "pdf", "-o", str(pdf), str(sch))
    pdf_ok = pdf.exists() and pdf.stat().st_size > 0 and pdf.read_bytes()[:4] == b"%PDF"
    return {"kicad": available(), "files": ["design.kicad_sch", "design.net"] + (["design.pdf"] if pdf_ok else []),
            "netlist_roundtrip_ok": not mismatches, "mismatches": mismatches, "kicad_erc": "NOT EXECUTED: kicad-cli 7.0 has no `sch erc` (added in KiCad 8); CircuitForge verification checks still apply",
            "note": "ERC output is KiCad's own; a clean ERC or successful export does not mean the design is correct or manufacturable."}
