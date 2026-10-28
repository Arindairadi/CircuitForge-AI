import csv, io
from app.schemas.circuit import Circuit

CATEGORY = {"R": "resistor", "C": "capacitor", "LED": "led", "V": "source", "D": "diode", "Q": "transistor", "M": "mosfet", "L": "inductor", "OA": "op-amp (ideal model)", "QP": "transistor", "MP": "mosfet", "REG": "regulator"}
FOOT = {"R": "axial THT (assumed)", "C": "disc THT (assumed)", "LED": "5mm THT (assumed)", "V": "2-pin header (assumed)", "D": "DO-35 (assumed)", "Q": "TO-92 (assumed)", "M": "TO-220 (assumed)", "L": "axial THT (assumed)", "OA": "none (ideal model, not a real part)", "QP": "TO-92 (assumed)", "MP": "TO-220 (assumed)", "REG": "TO-220 (assumed)"}


def _fmt(kind: str, v: float | None) -> str:
    if v is None: return {"Q": "NPN", "M": "NMOS", "D": "DIODE", "OA": "IDEAL-OA", "LED": "LED", "QP": "PNP", "MP": "PMOS"}.get(kind, "")
    unit = {"R": "ohm", "C": "F", "V": "V", "L": "H", "REG": "V", "OA": "V"}[kind]
    for scale, p in ((1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= scale: return f"{v/scale:g}{p}{unit}"
    return f"{v:g}{unit}"


def build_bom(c: Circuit, overrides: dict[str, dict] | None = None) -> list[dict]:
    """Rows are grouped by kind/value and, when the user assigned real parts, by the assigned part too.
    Assigned data is USER-ENTERED and labelled as such; nothing is looked up or invented."""
    ov = overrides or {}
    groups: dict[tuple, list[str]] = {}
    for comp in c.components:
        o = ov.get(comp.ref, {})
        groups.setdefault((comp.kind, _fmt(comp.kind, comp.value), o.get("mpn") or "", o.get("manufacturer") or "", o.get("datasheet_url") or "", o.get("price") or "", o.get("availability") or ""), []).append(comp.ref)
    rows = []
    for (k, v, mpn, mfr, ds, price, avail), refs in groups.items():
        note = (f"User-entered part data (not verified by CircuitForge): {ov[refs[0]].get('notes', '')}".strip() if mpn or mfr or ds or price or avail
                else "Generic part; select a real MPN before ordering. Price/stock not verified.")
        rows.append({"references": ", ".join(sorted(refs)), "quantity": len(refs), "category": CATEGORY[k], "value": v, "footprint": FOOT[k],
                     "manufacturer": mfr, "mpn": mpn, "datasheet": ds, "price": price, "availability": avail, "notes": note})
    return rows


def to_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["references"])
    w.writeheader(); w.writerows(rows)
    return out.getvalue()
