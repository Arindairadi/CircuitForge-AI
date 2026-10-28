"""Deterministic verification. Rating checks need simulated DC currents; otherwise they are reported as NOT executed."""
from pydantic import BaseModel
from app.schemas.circuit import Circuit, PINS, GROUND, REG_DROPOUT_V


class Finding(BaseModel):
    check: str
    severity: str  # error | warning | info
    target: str
    explanation: str
    evidence: str
    suggested_fix: str
    executed: bool = True
    resolved: bool = False


def verify(c: Circuit, dc_currents: dict[str, float] | None = None, node_voltages: dict[str, float] | None = None) -> list[Finding]:
    f: list[Finding] = []
    nets = c.nets()
    for comp in c.components:
        for pin in PINS[comp.kind]:
            if pin not in comp.pins:
                f.append(Finding(check="connectivity.unconnected_pin", severity="error", target=f"{comp.ref}.{pin}",
                                 explanation="Pin is not connected to any net", evidence=f"{comp.ref} pins: {comp.pins}",
                                 suggested_fix="Connect the pin to a net"))
        if comp.kind in ("V", "R", "C", "L", "REG") and comp.value is None:
            f.append(Finding(check="values.missing", severity="error", target=comp.ref, explanation="Missing value",
                             evidence="value is None", suggested_fix="Set a component value"))
        elif comp.kind in ("V", "R", "C", "L", "REG") and comp.value is not None and comp.value <= 0:
            f.append(Finding(check="values.invalid", severity="error", target=comp.ref, explanation="Non-positive value",
                             evidence=f"value={comp.value}", suggested_fix="Use a positive value"))
        if comp.kind == "V" and "p" in comp.pins and comp.pins.get("p") == comp.pins.get("n"):
            f.append(Finding(check="connectivity.short", severity="error", target=comp.ref,
                             explanation="Voltage source terminals shorted", evidence=f"both on net {comp.pins['p']}",
                             suggested_fix="Separate the terminals"))
    if GROUND not in nets:
        f.append(Finding(check="connectivity.no_ground", severity="error", target="net 0",
                         explanation="No ground reference (net '0')", evidence=f"nets: {sorted(nets)}",
                         suggested_fix="Connect a reference node to net 0"))
    for net, conns in nets.items():
        if len(conns) < 2 and net != GROUND:
            f.append(Finding(check="connectivity.dangling_net", severity="warning", target=f"net {net}",
                             explanation="Net has a single connection", evidence=str(conns),
                             suggested_fix="Connect the net to another pin or remove it"))
    if dc_currents is None:
        f.append(Finding(check="ratings.dc_current", severity="info", target="design", executed=False,
                         explanation="Component rating checks need DC currents (run an operating-point simulation first)",
                         evidence="no simulation data", suggested_fix="Run simulation, then re-verify"))
    else:
        for comp in c.components:
            i = abs(dc_currents.get(comp.ref, 0.0))
            if comp.kind == "R" and comp.value:
                p, lim = i * i * comp.value, comp.rating or 0.25
                if p > lim:
                    f.append(Finding(check="ratings.resistor_power", severity="error", target=comp.ref,
                                     explanation="Resistor power exceeds rating", evidence=f"P={p*1e3:.1f} mW > {lim*1e3:.0f} mW",
                                     suggested_fix="Increase resistance or use a higher-power part"))
            names = {"LED": ("ratings.led_current", "LED current"), "D": ("ratings.diode_current", "Diode current"),
                     "Q": ("ratings.bjt_ic", "Collector current"), "M": ("ratings.mosfet_id", "Drain current"),
                     "QP": ("ratings.bjt_ic", "Collector current"), "MP": ("ratings.mosfet_id", "Drain current"),
                     "REG": ("ratings.regulator_iout", "Regulator output current")}
            if comp.kind in names:
                chk, label = names[comp.kind]
                lim = comp.rating if comp.rating is not None else (0.020 if comp.kind == "LED" else None)
                if lim is None:
                    f.append(Finding(check=chk, severity="info", target=comp.ref, executed=False, explanation=f"{label} limit not set for this part",
                                     evidence="rating is None", suggested_fix="Set the rating from the part's datasheet"))
                elif i > lim:
                    f.append(Finding(check=chk, severity="error", target=comp.ref, explanation=f"{label} exceeds the rating",
                                     evidence=f"I={i*1e3:.1f} mA > {lim*1e3:.0f} mA", suggested_fix="Reduce the current or use a higher-rated part"))
        if node_voltages is not None:
            vv = lambda net: 0.0 if net == "0" else node_voltages.get(net.lower())
            for comp in c.components:
                if comp.kind != "REG": continue
                vin, vout, i = vv(comp.pins.get("in", "")), vv(comp.pins.get("out", "")), abs(dc_currents.get(comp.ref, 0.0))
                if vin is None or vout is None: continue
                if vin - comp.value < REG_DROPOUT_V:
                    f.append(Finding(check="regulator.dropout", severity="warning", target=comp.ref, explanation="Input is too low for regulation (assumed dropout 2 V)",
                                     evidence=f"Vin={vin:.2f} V, Vset={comp.value:g} V, Vout={vout:.2f} V", suggested_fix="Raise the input voltage or use a low-dropout regulator"))
                p = (vin - vout) * i
                if p > 0.5:
                    f.append(Finding(check="regulator.dissipation", severity="warning", target=comp.ref, explanation="Significant linear-regulator dissipation",
                                     evidence=f"P=(Vin-Vout)*I={p:.2f} W; junction temperature NOT computed (needs theta_JA from the datasheet)", suggested_fix="Check the thermal limit, add a heatsink or use a switching regulator"))
        if node_voltages is not None:
            for comp in c.components:
                if comp.kind == "OA" and comp.value:
                    vout = 0.0 if comp.pins.get("o") == "0" else node_voltages.get(comp.pins.get("o", "").lower())
                    if vout is not None and vout >= comp.value - 0.05:
                        f.append(Finding(check="opamp.saturated", severity="warning", target=comp.ref, explanation="Output is at the positive supply rail; the amplifier is saturated and the closed-loop gain no longer applies",
                                         evidence=f"Vout={vout:.3f} V, rail={comp.value:g} V", suggested_fix="Reduce the input or the gain, or raise the supply"))
        if any(x.pulse for x in c.components if x.kind == "V"):
            f.append(Finding(check="ratings.transient_peaks", severity="info", target="design", executed=False,
                             explanation="Ratings were checked at the DC operating point only; switching peaks (inrush, turn-off spikes) are not checked",
                             evidence="pulse source present", suggested_fix="Run a transient simulation and inspect peaks against ratings"))
    f.append(Finding(check="manual.engineering_review", severity="info", target="design", executed=False,
                     explanation="Passing automated checks is not safety or production certification",
                     evidence="n/a", suggested_fix="Perform manual review and physical testing"))
    return f
