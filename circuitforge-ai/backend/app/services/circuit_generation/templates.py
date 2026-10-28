"""Deterministic circuit templates (no AI key needed). Component values come from calculations."""
from app.schemas.circuit import Circuit, Component
from app.services.engineering_calculations import calc


def led_circuit(vs: float = 5.0, vf: float = 2.0, i_led: float = 0.010) -> Circuit:
    r = calc.led_resistor(vs, vf, i_led)
    return Circuit(name=f"LED indicator {vs:g} V", components=[
        Component(ref="V1", kind="V", value=vs, pins={"p": "vcc", "n": "0"}),
        Component(ref="R1", kind="R", value=r.result, pins={"1": "vcc", "2": "led_a"}),
        Component(ref="D1", kind="LED", pins={"a": "led_a", "k": "0"}, rating=0.020)],
        assumptions=[f"LED Vf ~ {vf} V at {i_led*1e3:g} mA (typical, not from a specific datasheet)", *r.assumptions])


def voltage_divider_circuit(vin: float = 5.0, r1: float = 10e3, r2: float = 10e3) -> Circuit:
    calc.voltage_divider(vin, r1, r2)
    return Circuit(name="Voltage divider", components=[
        Component(ref="V1", kind="V", value=vin, pins={"p": "vin", "n": "0"}),
        Component(ref="R1", kind="R", value=r1, pins={"1": "vin", "2": "out"}),
        Component(ref="R2", kind="R", value=r2, pins={"1": "out", "2": "0"})],
        assumptions=["Output unloaded"])


def rc_lowpass_circuit(vin: float = 5.0, r: float = 1e3, c: float = 1e-6) -> Circuit:
    calc.rc_time_constant(r, c)
    return Circuit(name="RC low-pass", components=[
        Component(ref="V1", kind="V", value=vin, pins={"p": "in", "n": "0"}),
        Component(ref="R1", kind="R", value=r, pins={"1": "in", "2": "out"}),
        Component(ref="C1", kind="C", value=c, pins={"1": "out", "2": "0"})],
        assumptions=["Ideal components; capacitor initially discharged"])


PULSE = lambda v: [0.0, v, 1e-3, 1e-5, 1e-5, 2e-3, 5e-3]  # 0 -> v after 1 ms, 2 ms wide, 5 ms period


def npn_switch_circuit(vcc: float = 5.0, i_led: float = 0.010, vin: float = 5.0, vf: float = 2.0) -> Circuit:
    rl = calc.led_resistor(vcc, vf + 0.2, i_led); rb = calc.bjt_base_resistor(vin, 0.7, i_led)
    return Circuit(name="NPN low-side LED switch", components=[
        Component(ref="V1", kind="V", value=vcc, pins={"p": "vcc", "n": "0"}),
        Component(ref="V2", kind="V", value=vin, pulse=PULSE(vin), pins={"p": "in", "n": "0"}),
        Component(ref="R1", kind="R", value=rl.result, pins={"1": "vcc", "2": "led_a"}),
        Component(ref="D1", kind="LED", pins={"a": "led_a", "k": "col"}, rating=0.020),
        Component(ref="Q1", kind="Q", pins={"b": "base", "c": "col", "e": "0"}, rating=0.100),
        Component(ref="R2", kind="R", value=rb.result, pins={"1": "in", "2": "base"})],
        assumptions=["Generic NPN SPICE model (BF=100); Ic rating 100 mA is a generic assumption, not a specific part", "Vce(sat) ~0.2 V assumed for the LED resistor", *rb.assumptions, *rl.assumptions])


def mosfet_switch_circuit(vcc: float = 12.0, r_load: float = 120.0, vgate: float = 5.0) -> Circuit:
    calc.ohms_law_current(vcc, r_load)
    p = vcc * vcc / r_load
    return Circuit(name="N-MOSFET low-side switch", components=[
        Component(ref="V1", kind="V", value=vcc, pins={"p": "vcc", "n": "0"}),
        Component(ref="V2", kind="V", value=vgate, pulse=PULSE(vgate), pins={"p": "in", "n": "0"}),
        Component(ref="R1", kind="R", value=r_load, rating=max(0.25, 2 * p), pins={"1": "vcc", "2": "drain"}),
        Component(ref="M1", kind="M", pins={"g": "gate", "d": "drain", "s": "0"}, rating=1.0),
        Component(ref="R2", kind="R", value=100.0, pins={"1": "in", "2": "gate"}),
        Component(ref="R3", kind="R", value=100e3, pins={"1": "gate", "2": "0"})],
        assumptions=["Generic logic-level-style NMOS model (VTO=2 V, KP=0.5); Id rating 1 A is a generic assumption", f"Load resistor assumed rated for at least {2*p:.2f} W (2x its dissipation)", "R3 pulls the gate low when the drive is disconnected"])


def relay_driver_circuit(vcc: float = 12.0, r_coil: float = 400.0, l_coil: float = 0.2, vgate: float = 5.0, flyback: float = 1.0) -> Circuit:
    calc.ohms_law_current(vcc, r_coil); calc.rc_time_constant(r_coil, l_coil)  # input validation (positive values)
    comps = [Component(ref="V1", kind="V", value=vcc, pins={"p": "vcc", "n": "0"}),
        Component(ref="V2", kind="V", value=vgate, pulse=[0.0, vgate, 1e-3, 1e-5, 1e-5, 10e-3, 30e-3], pins={"p": "in", "n": "0"}),
        Component(ref="L1", kind="L", value=l_coil, pins={"1": "vcc", "2": "coilx"}),
        Component(ref="R1", kind="R", value=r_coil, rating=max(0.25, 2 * vcc * vcc / r_coil), pins={"1": "coilx", "2": "drain"}),
        Component(ref="M1", kind="M", pins={"g": "gate", "d": "drain", "s": "0"}, rating=1.0),
        Component(ref="R2", kind="R", value=100.0, pins={"1": "in", "2": "gate"}),
        Component(ref="R3", kind="R", value=100e3, pins={"1": "gate", "2": "0"})]
    if flyback:
        comps.insert(4, Component(ref="D1", kind="D", pins={"a": "drain", "k": "vcc"}, rating=1.0))
    return Circuit(name="Relay driver" + ("" if flyback else " (NO flyback diode)"), components=comps,
        assumptions=["Relay coil modelled as ideal inductance in series with its DC resistance", "Generic diode and NMOS models; ratings of 1 A are generic assumptions", "Flyback diode clamps the coil's turn-off voltage spike"
                     if flyback else "WARNING: no flyback diode; turn-off voltage spike is unclamped"])


def opamp_noninverting_circuit(vin: float = 0.1, rf: float = 9e3, rg: float = 1e3, vcc: float = 0.0) -> Circuit:
    calc.voltage_divider(1.0, rf, rg)  # validates positive values
    if vcc < 0: raise ValueError("vcc must be >= 0 (0 = ideal op-amp without rails)")
    return Circuit(name=f"Non-inverting amplifier (gain {1 + rf/rg:g})", components=[
        Component(ref="V1", kind="V", value=vin, pins={"p": "in", "n": "0"}),
        Component(ref="OA1", kind="OA", value=vcc or None, pins={"p": "in", "n": "inv", "o": "out"}),
        Component(ref="R1", kind="R", value=rf, pins={"1": "out", "2": "inv"}),
        Component(ref="R2", kind="R", value=rg, pins={"1": "inv", "2": "0"})],
        assumptions=(["Op-amp with single-supply rails 0..%g V (gain 1e5); no offset, bias current, slew-rate or bandwidth limits, and the output swings fully to the rails (real parts do not)" % vcc] if vcc else ["IDEAL op-amp (open-loop gain 1e6): no supply rails, offset, bias current, slew rate or bandwidth limits"])
        + ["Gain = 1 + Rf/Rg", "Not representative of any real op-amp; pick a real part and re-simulate with its model"])


def pmos_highside_circuit(vcc: float = 12.0, r_load: float = 120.0) -> Circuit:
    calc.ohms_law_current(vcc, r_load); p = vcc * vcc / r_load
    return Circuit(name="P-MOSFET high-side switch", components=[
        Component(ref="V1", kind="V", value=vcc, pins={"p": "vcc", "n": "0"}),
        Component(ref="V2", kind="V", value=vcc, pulse=[vcc, 0.0, 1e-3, 1e-5, 1e-5, 2e-3, 5e-3], pins={"p": "drv", "n": "0"}),
        Component(ref="M1", kind="MP", pins={"g": "gate", "d": "out", "s": "vcc"}, rating=1.0),
        Component(ref="R1", kind="R", value=r_load, rating=max(0.25, 2 * p), pins={"1": "out", "2": "0"}),
        Component(ref="R2", kind="R", value=100.0, pins={"1": "drv", "2": "gate"}),
        Component(ref="R3", kind="R", value=100e3, pins={"1": "gate", "2": "vcc"})],
        assumptions=["Generic PMOS model (VTO=-2 V); the drive source swings between Vcc (off) and 0 V (on), so the gate is driven directly by a logic level referenced to ground", "R3 holds the gate at Vcc (off) when undriven", "Id rating 1 A is a generic assumption", f"Load resistor assumed rated for at least {2*p:.2f} W"])


def ldo_supply_circuit(vin: float = 9.0, vout: float = 5.0, i_load: float = 0.1) -> Circuit:
    p = calc.regulator_dissipation(vin, vout, i_load); calc.ohms_law_current(vout, i_load)
    return Circuit(name=f"Linear regulator {vout:g} V", components=[
        Component(ref="V1", kind="V", value=vin, pins={"p": "vin", "n": "0"}),
        Component(ref="REG1", kind="REG", value=vout, rating=1.0, pins={"in": "vin", "gnd": "0", "out": "vout"}),
        Component(ref="C1", kind="C", value=1e-6, pins={"1": "vin", "2": "0"}),
        Component(ref="C2", kind="C", value=1e-6, pins={"1": "vout", "2": "0"}),
        Component(ref="R1", kind="R", value=vout / i_load, rating=max(0.25, 2 * vout * i_load), pins={"1": "vout", "2": "0"})],
        assumptions=[f"Generic 78xx-style regulator; behavioral model: 2 V dropout, 50 mOhm output resistance, no quiescent current; 1 A output rating is an assumption", f"Estimated regulator dissipation {p.result:.2f} W (junction temperature needs the datasheet theta_JA)",
                     "1 uF input/output capacitors are placeholders; follow the chosen regulator's datasheet", "R1 is the load"])


TEMPLATES = {"led": led_circuit, "voltage_divider": voltage_divider_circuit, "rc_lowpass": rc_lowpass_circuit, "npn_switch": npn_switch_circuit,
             "mosfet_switch": mosfet_switch_circuit, "relay_driver": relay_driver_circuit, "opamp_noninverting": opamp_noninverting_circuit, "pmos_highside": pmos_highside_circuit, "ldo_supply": ldo_supply_circuit}


def generate(template: str, **params) -> Circuit:
    if template not in TEMPLATES:
        raise ValueError(f"Unsupported template '{template}'. Supported: {sorted(TEMPLATES)}")
    return TEMPLATES[template](**params)
