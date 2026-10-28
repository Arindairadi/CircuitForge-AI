"""PCB generation + manufacturing outputs via KiCad 7 (pcbnew subprocess + kicad-cli). Every output file is verified to exist and be non-empty."""
import json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path
from app.schemas.circuit import Circuit
from app.services.reporting.bom import _fmt
from app.integrations.kicad.schematic import KicadError, _cli, available

BUILDER = Path(__file__).with_name("pcb_builder.py")
PCB_PYTHON = os.environ.get("PCBNEW_PYTHON", sys.executable)  # interpreter that can `import pcbnew`


def pcbnew_available() -> bool:
    try: return subprocess.run([PCB_PYTHON, "-c", "import pcbnew"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False


def _parse_drc(text: str) -> dict:
    items = []
    for m in re.finditer(r"\[(\w+)\]: (.*?)\n\s+(?:.*?Severity: (\w+))", text, re.S):
        items.append({"type": m.group(1), "description": m.group(2).strip(), "severity": m.group(3)})
    unc = re.search(r"Found (\d+) unconnected", text)
    return {"violations": items, "unconnected": int(unc.group(1)) if unc else None,
            "errors": sum(1 for i in items if i["severity"] == "error")}


def generate_pcb(c: Circuit, outdir: Path, pitch: float = 25.0, export: bool = True) -> dict:
    if not pcbnew_available(): raise KicadError("KiCad's pcbnew Python module is not available to the server (set PCBNEW_PYTHON)")
    for comp in c.components:
        if comp.kind == "OA": raise KicadError("The ideal op-amp is a simulation model with no footprint; replace it with a real part before PCB generation")
        for pin in {"V": "pn", "R": "12", "C": "12", "LED": "ak", "D": "ak", "Q": "bce", "M": "gds", "L": "12", "QP": "bce", "MP": "gds", "REG": ("in", "gnd", "out")}[comp.kind]:
            if pin not in comp.pins: raise KicadError(f"{comp.ref}.{pin} is unconnected; fix the design before PCB generation")
    outdir.mkdir(parents=True, exist_ok=True)
    if not (8.0 <= pitch <= 40.0): raise KicadError("pitch_mm must be between 8 and 40")
    spec = {"outdir": str(outdir), "pitch": pitch, "components": [{"ref": x.ref, "kind": x.kind, "pins": x.pins,
            "value_text": "LED" if x.kind == "LED" else _fmt(x.kind, x.value)} for x in c.components]}
    r = subprocess.run([PCB_PYTHON, str(BUILDER)], input=json.dumps(spec), capture_output=True, text=True, timeout=90)
    try: built = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError): raise KicadError("PCB builder failed: " + (r.stderr or r.stdout)[-300:])
    if "error" in built: raise KicadError(built["error"])
    pcb = outdir / "design.kicad_pcb"
    drc = _parse_drc((outdir / "drc.rpt").read_text())
    if not export:  # used by the area optimizer: layout + DRC only
        return {"kicad": built["kicad"], "board_mm": built["board_mm"], "drc": drc, "layout": built["layout"]}
    gdir = outdir / "gerbers"; gdir.mkdir(exist_ok=True)
    _cli("pcb", "export", "gerbers", "-o", str(gdir) + "/", str(pcb))
    _cli("pcb", "export", "drill", "-o", str(gdir) + "/", str(pcb))
    _cli("pcb", "export", "pos", "--format", "csv", "--units", "mm", "-o", str(outdir / "positions.csv"), str(pcb))
    _cli("pcb", "export", "svg", "--layers", "F.Cu,B.Cu,Edge.Cuts,F.Silkscreen", "--black-and-white", "-o", str(outdir / "design.svg"), str(pcb))
    files = [p for p in gdir.iterdir() if p.is_file()]
    if not any(p.suffix in (".gtl", ".gbr") for p in files) or not any(p.suffix == ".drl" for p in files):
        raise KicadError("Gerber/drill output incomplete")
    with zipfile.ZipFile(outdir / "fabrication.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p, p.name)
    present = [n for n in ("design.kicad_pcb", "drc.rpt", "positions.csv", "design.svg", "fabrication.zip") if (outdir / n).is_file() and (outdir / n).stat().st_size > 0]
    if len(present) != 5: raise KicadError(f"Missing outputs: {set(['design.kicad_pcb','drc.rpt','positions.csv','design.svg','fabrication.zip']) - set(present)}")
    (outdir / "layout.json").write_text(json.dumps(built["layout"]))
    open_issues = []
    if drc["unconnected"]: open_issues.append(f"{drc['unconnected']} unconnected pads")
    if drc["errors"]: open_issues.append(f"{drc['errors']} DRC errors")
    return {"kicad": built["kicad"], "board_mm": built["board_mm"], "routed_nets": built["routed_nets"], "files": present + ["layout.json"], "layout": built["layout"], "gerber_files": sorted(p.name for p in files),
            "drc": drc, "3d_view": "Approximate 3D view built from part bounding boxes and typical package heights (layout.json); KiCad 3D component models are not used",
            "manufacturing_readiness": {"ready_for_fabrication": False, "known_open_issues": open_issues,
              "unresolved": ["Footprints are generic through-hole assumptions chosen by CircuitForge (voltage source -> 2-pin header; transistor pad numbers follow the symbol BCE/GSD numbering, so verify against the real part pinout)",
                             "No design-rule set tuned to a fabricator; KiCad defaults used", "No current-capacity, thermal or return-path analysis performed",
                             "Gerbers not reviewed in a viewer or by a fabricator", "Manual engineering review required"]},
            "note": "Export success and a clean DRC do not mean the board is manufacturable or correct."}


def optimize_pcb_area(c: Circuit, workdir: Path, pitches=(25.0, 22.0, 20.0, 18.0, 16.0, 14.0, 12.0, 10.0)) -> dict:
    """Measured, not asserted: every candidate layout is built and run through KiCad's DRC; only DRC-clean ones are eligible."""
    tried = []
    for pt in pitches:
        r = generate_pcb(c, workdir / f"p{int(pt)}", pitch=pt, export=False)
        ok = r["drc"]["unconnected"] == 0 and r["drc"]["errors"] == 0
        tried.append({"pitch_mm": pt, "board_mm": r["board_mm"], "area_mm2": round(r["board_mm"][0] * r["board_mm"][1], 1), "drc_clean": ok,
                      "drc_errors": r["drc"]["errors"], "drc_unconnected": r["drc"]["unconnected"]})
    base = next((t for t in tried if t["pitch_mm"] == 25.0), None)
    clean = [t for t in tried if t["drc_clean"]]
    if not base or not base["drc_clean"] or not clean:
        return {"supported": True, "objective": "smaller_pcb_area", "constraint_satisfied": False, "tried": tried, "action": "The reference layout itself is not DRC clean; nothing to compare"}
    best = min(clean, key=lambda t: t["area_mm2"])
    return {"supported": True, "objective": "smaller_pcb_area", "constraint": "KiCad DRC: 0 unconnected pads and 0 errors (courtyard overlaps included)",
            "original": {"pitch_mm": 25.0, "board_mm": base["board_mm"], "area_mm2": base["area_mm2"], "method": "KiCad DRC (pcbnew)"},
            "alternative": {**best, "method": "KiCad DRC (pcbnew)"}, "reduction_pct": round(100 * (base["area_mm2"] - best["area_mm2"]) / base["area_mm2"], 1),
            "constraint_satisfied": True, "tried": tried,
            "tradeoff": "Tighter spacing makes assembly and rework harder; fabricator-specific rules, thermal and current limits are not evaluated",
            "action": f"Apply by generating the PCB with pitch_mm={best['pitch_mm']:g}"}
