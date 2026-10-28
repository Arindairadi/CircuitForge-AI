"""Constraint-aware optimization (currently: LED indicator supply power). Alternatives are measured, not asserted:
both designs are simulated in ngspice when available; otherwise values are labelled 'calculated'."""
from app.schemas.circuit import Circuit
from app.services.engineering_calculations import calc
from app.services.simulation import spice


def _supply_power(c: Circuit) -> tuple[float, str]:
    vs = next(x.value for x in c.components if x.kind == "V")
    try:
        i = abs(next(iter(spice.operating_point(c)["source_currents"].values())))
        return vs * i, "simulated (ngspice)"
    except spice.SimulationError:
        r = next(x.value for x in c.components if x.ref == "R1")
        return vs * (vs - 2.0) / r, "calculated (assumes Vf=2.0 V)"


def optimize_led_power(c: Circuit, target_ma: float, min_ma: float) -> dict:
    refs = {x.ref: x for x in c.components}
    if not ({"V1", "R1", "D1"} <= set(refs) and refs["D1"].kind == "LED" and len(c.components) == 3):
        return {"supported": False, "message": "Power optimization is implemented only for the 3-part LED indicator template"}
    if not (0 < min_ma <= target_ma <= 20): return {"supported": False, "message": "Need 0 < min_led_current_ma <= target_ma <= 20"}
    vs = refs["V1"].value
    alt = c.model_copy(deep=True)
    try: alt.components[[x.ref for x in alt.components].index("R1")].value = calc.led_resistor(vs, 2.0, target_ma / 1e3).result
    except ValueError as e: return {"supported": False, "message": str(e)}
    alt.simulation_status = alt.verification_status = "not_run"
    p0, m0 = _supply_power(c); p1, m1 = _supply_power(alt)
    i1 = p1 / vs
    ok = i1 * 1e3 >= min_ma
    return {"supported": True, "objective": "lower_power", "constraint": f"LED current >= {min_ma} mA (brightness requirement)",
            "original": {"supply_power_w": p0, "method": m0}, "alternative": {"supply_power_w": p1, "method": m1, "circuit": alt},
            "reduction_pct": round(100 * (p0 - p1) / p0, 1) if p0 else None, "constraint_satisfied": ok,
            "tradeoff": "Lower LED current means a dimmer LED; check visibility on the real part",
            "action": "Apply with PUT /projects/{id}/circuit after approval" if ok else "Alternative violates the constraint; do not apply"}


def _node_v(c: Circuit, node: str) -> tuple[float, str]:
    try: return spice.operating_point(c)["node_voltages"][node], "simulated (ngspice)"
    except spice.SimulationError:
        v1, r1, r2 = (next(x.value for x in c.components if x.ref == r) for r in ("V1", "R1", "R2"))
        return v1 * r2 / (r1 + r2), "calculated (unloaded divider)"


def optimize_divider_target(c: Circuit, target_v: float, tolerance_pct: float) -> dict:
    refs = {x.ref: x for x in c.components}
    if not ({"V1", "R1", "R2"} <= set(refs) and len(c.components) == 3 and refs["R2"].kind == "R"):
        return {"supported": False, "message": "Target-voltage optimization is implemented only for the 3-part voltage divider template"}
    vin, r1 = refs["V1"].value, refs["R1"].value
    if not (0 < target_v < vin) or tolerance_pct <= 0: return {"supported": False, "message": "Need 0 < target_v < supply and tolerance_pct > 0"}
    cands = [m * 10 ** e for e in range(1, 7) for m in calc.E24]
    best = min(cands, key=lambda r: abs(vin * r / (r1 + r) - target_v))
    alt = c.model_copy(deep=True); next(x for x in alt.components if x.ref == "R2").value = best
    alt.simulation_status = alt.verification_status = "not_run"
    v0, m0 = _node_v(c, "out"); v1, m1 = _node_v(alt, "out")
    e0, e1 = abs(v0 - target_v) / target_v * 100, abs(v1 - target_v) / target_v * 100
    return {"supported": True, "objective": "hit_target_voltage", "constraint": f"|Vout - {target_v} V| <= {tolerance_pct}% (unloaded output, ideal resistors)",
            "ideal_r2_ohm": r1 * target_v / (vin - target_v), "chosen_r2_e24_ohm": best,
            "original": {"vout": v0, "error_pct": e0, "method": m0}, "alternative": {"vout": v1, "error_pct": e1, "method": m1, "circuit": alt},
            "constraint_satisfied": e1 <= tolerance_pct, "tradeoff": "Resistor tolerance (e.g. 1-5%) adds error not modelled here; a load on the output shifts the voltage",
            "action": "Apply with PUT /projects/{id}/circuit after approval" if e1 <= tolerance_pct else "Closest E24 value still misses the tolerance; use E96 or a trimmer"}
