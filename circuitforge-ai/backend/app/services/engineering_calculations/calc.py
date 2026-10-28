"""Unit-aware calculations. Every result carries formula, substitution, assumptions, warnings."""
import math
from pydantic import BaseModel


class CalcResult(BaseModel):
    name: str
    inputs: dict[str, str]
    formula: str
    substitution: str
    result: float
    unit: str
    assumptions: list[str] = []
    warnings: list[str] = []


def _pos(**kw):
    for k, v in kw.items():
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            raise ValueError(f"{k} must be a positive finite number, got {v!r}")


E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]


def nearest_e24(r: float, round_up: bool = True) -> float:
    dec = 10 ** math.floor(math.log10(r))
    cands = [m * dec * k for k in (1, 10) for m in E24]
    if round_up:
        return min(c for c in cands if c >= r * (1 - 1e-9))
    return min(cands, key=lambda c: abs(c - r))


def ohms_law_current(v: float, r: float) -> CalcResult:
    _pos(v=v, r=r)
    return CalcResult(name="Ohm's law (current)", inputs={"V": f"{v} V", "R": f"{r} ohm"}, formula="I = V / R",
                      substitution=f"I = {v} / {r}", result=v / r, unit="A")


def led_resistor(vs: float, vf: float, i_led: float, resistor_power_rating: float = 0.25) -> CalcResult:
    _pos(vs=vs, vf=vf, i_led=i_led)
    if vs <= vf:
        raise ValueError("Supply voltage must exceed LED forward voltage")
    r_exact = (vs - vf) / i_led
    r_std = nearest_e24(r_exact, round_up=True)
    p = (vs - vf) ** 2 / r_std
    warn = []
    if p > 0.5 * resistor_power_rating:
        warn.append(f"Resistor dissipates {p*1e3:.1f} mW, above 50% of its {resistor_power_rating*1e3:.0f} mW rating")
    return CalcResult(name="LED series resistor", inputs={"Vs": f"{vs} V", "Vf": f"{vf} V", "I": f"{i_led} A"},
                      formula="R = (Vs - Vf) / I, rounded up to E24",
                      substitution=f"R = ({vs} - {vf}) / {i_led} = {r_exact:.2f} ohm -> {r_std:g} ohm",
                      result=r_std, unit="ohm",
                      assumptions=["Vf is a typical value; check the LED datasheet", "E24 series, rounded up so current <= target"],
                      warnings=warn)


def voltage_divider(vin: float, r1: float, r2: float) -> CalcResult:
    _pos(vin=vin, r1=r1, r2=r2)
    return CalcResult(name="Voltage divider", inputs={"Vin": f"{vin} V", "R1": f"{r1} ohm", "R2": f"{r2} ohm"},
                      formula="Vout = Vin * R2 / (R1 + R2)", substitution=f"Vout = {vin} * {r2} / ({r1} + {r2})",
                      result=vin * r2 / (r1 + r2), unit="V",
                      assumptions=["Unloaded output (load resistance >> R2)"])


def power_dissipation(v: float, i: float) -> CalcResult:
    _pos(v=v, i=i)
    return CalcResult(name="Power", inputs={"V": f"{v} V", "I": f"{i} A"}, formula="P = V * I",
                      substitution=f"P = {v} * {i}", result=v * i, unit="W")


def rc_time_constant(r: float, c: float) -> CalcResult:
    _pos(r=r, c=c)
    return CalcResult(name="RC time constant", inputs={"R": f"{r} ohm", "C": f"{c} F"}, formula="tau = R * C",
                      substitution=f"tau = {r} * {c}", result=r * c, unit="s",
                      assumptions=["Ideal components, zero source resistance"])


def rc_cutoff(r: float, c: float) -> CalcResult:
    _pos(r=r, c=c)
    return CalcResult(name="RC cutoff frequency", inputs={"R": f"{r} ohm", "C": f"{c} F"}, formula="fc = 1 / (2*pi*R*C)",
                      substitution=f"fc = 1 / (2*pi*{r}*{c})", result=1 / (2 * math.pi * r * c), unit="Hz",
                      assumptions=["First-order passive filter, unloaded"])


def series_resistance(*rs: float) -> float:
    for r in rs: _pos(r=r)
    return sum(rs)


def parallel_resistance(*rs: float) -> float:
    for r in rs: _pos(r=r)
    return 1 / sum(1 / r for r in rs)


def e24_floor(r: float) -> float:
    dec = 10 ** math.floor(math.log10(r))
    return max(c for c in [m * dec * k for k in (0.1, 1, 10) for m in E24] if c <= r * (1 + 1e-9))


def bjt_base_resistor(vin: float, vbe: float, ic: float, forced_beta: float = 10.0) -> CalcResult:
    _pos(vin=vin, vbe=vbe, ic=ic, forced_beta=forced_beta)
    if vin <= vbe: raise ValueError("Drive voltage must exceed Vbe")
    ib = ic / forced_beta; r = (vin - vbe) / ib; rs = e24_floor(r)
    return CalcResult(name="BJT switch base resistor", inputs={"Vin": f"{vin} V", "Vbe": f"{vbe} V", "Ic": f"{ic} A", "forced beta": f"{forced_beta}"},
                      formula="Ib = Ic / beta_forced; Rb = (Vin - Vbe) / Ib, rounded DOWN to E24", substitution=f"Ib = {ic}/{forced_beta} = {ib:.6g} A; Rb = ({vin}-{vbe})/{ib:.6g} = {r:.1f} ohm -> {rs:g} ohm",
                      result=rs, unit="ohm", assumptions=["Vbe ~ 0.7 V assumed", "Forced beta 10 is a common saturation rule of thumb; real hFE must be checked on the datasheet"],
                      warnings=[] if ib < 0.005 else ["Base current above 5 mA; check the driver can supply it"])


def regulator_dissipation(vin: float, vout: float, i_load: float, theta_ja: float | None = None, ambient_c: float = 25.0) -> CalcResult:
    _pos(vin=vin, vout=vout, i_load=i_load)
    if vin <= vout: raise ValueError("A linear regulator needs Vin > Vout")
    p = (vin - vout) * i_load; warn = []; sub = f"P = ({vin} - {vout}) * {i_load}"
    if theta_ja is not None:
        _pos(theta_ja=theta_ja); tj = ambient_c + p * theta_ja; sub += f"; Tj = {ambient_c} + {p:.4g}*{theta_ja} = {tj:.1f} C"
        warn.append(f"Estimated junction temperature {tj:.1f} C; compare with the part's datasheet limit")
    return CalcResult(name="Linear regulator dissipation", inputs={"Vin": f"{vin} V", "Vout": f"{vout} V", "I": f"{i_load} A"}, formula="P = (Vin - Vout) * Iload; Tj = Ta + P * theta_JA",
                      substitution=sub, result=p, unit="W", assumptions=["Quiescent current ignored", "Steady state, still air; theta_JA must come from the datasheet/PCB"], warnings=warn)


def battery_runtime(capacity_mah: float, load_ma: float, usable_fraction: float = 0.8) -> CalcResult:
    _pos(capacity_mah=capacity_mah, load_ma=load_ma)
    if not (0 < usable_fraction <= 1): raise ValueError("usable_fraction must be in (0, 1]")
    h = capacity_mah * usable_fraction / load_ma
    return CalcResult(name="Battery runtime estimate", inputs={"capacity": f"{capacity_mah} mAh", "load": f"{load_ma} mA", "usable": f"{usable_fraction}"},
                      formula="t = capacity * usable_fraction / load", substitution=f"t = {capacity_mah} * {usable_fraction} / {load_ma}", result=h, unit="h",
                      assumptions=["Constant load current", "Ignores temperature, aging, discharge-rate (Peukert) effects and cutoff voltage"])


def capacitor_energy(c: float, v: float) -> CalcResult:
    _pos(c=c, v=v)
    return CalcResult(name="Capacitor stored energy", inputs={"C": f"{c} F", "V": f"{v} V"}, formula="E = 1/2 * C * V^2", substitution=f"E = 0.5 * {c} * {v}^2", result=0.5 * c * v * v, unit="J")


def mosfet_switch_check(vcc: float, r_load: float, vgs: float, vth: float, id_max: float) -> CalcResult:
    _pos(vcc=vcc, r_load=r_load, vgs=vgs, vth=vth, id_max=id_max)
    i = vcc / r_load; warn = []
    if vgs < vth + 1.0: warn.append("Vgs is less than 1 V above the (typical) threshold; the MOSFET may not be fully on. Check Rds(on) at this Vgs in the datasheet")
    if i > id_max: warn.append(f"Load current {i:.3g} A exceeds the Id limit {id_max} A")
    return CalcResult(name="MOSFET low-side switch check", inputs={"Vcc": f"{vcc} V", "Rload": f"{r_load} ohm", "Vgs": f"{vgs} V", "Vth": f"{vth} V", "Id_max": f"{id_max} A"},
                      formula="Iload = Vcc / Rload (Rds(on) neglected)", substitution=f"I = {vcc}/{r_load}", result=i, unit="A",
                      assumptions=["Rds(on) assumed small vs load; threshold is a typical value, not guaranteed minimum"], warnings=warn)
