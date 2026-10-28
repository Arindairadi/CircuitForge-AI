"""Local seed component library. Values are GENERIC TYPICAL values, not manufacturer-verified.
No datasheet URLs, prices or stock are included because none were verified."""
from pydantic import BaseModel


class ComponentRecord(BaseModel):
    id: str
    category: str
    description: str
    manufacturer: str | None = None
    part_number: str | None = None
    package: str | None = None
    specs: dict[str, float | str] = {}
    datasheet_url: str | None = None
    spice_model: bool = False
    source: str = "generic typical values; not manufacturer-verified"
    last_verified: str | None = None


SEED = [
    ComponentRecord(id="res-generic-0.25w", category="resistor", description="Generic 1/4 W carbon/metal-film resistor, E24",
                    package="axial THT", specs={"power_w": 0.25, "tolerance_pct": 5}, spice_model=True),
    ComponentRecord(id="cap-generic-ceramic", category="capacitor", description="Generic ceramic capacitor",
                    package="radial/0805", specs={"voltage_v": 50}, spice_model=True),
    ComponentRecord(id="led-generic-red-5mm", category="led", description="Generic 5 mm red LED",
                    package="5mm THT", specs={"vf_typ_v": 2.0, "if_max_a": 0.02}, spice_model=True),
    ComponentRecord(id="led-generic-green-5mm", category="led", description="Generic 5 mm green LED",
                    package="5mm THT", specs={"vf_typ_v": 2.1, "if_max_a": 0.02}, spice_model=False),
    ComponentRecord(id="diode-generic", category="diode", description="Generic small-signal/rectifier diode (SPICE: IS=1e-14, N=1, RS=0.5)", package="DO-35 THT", spice_model=True),
    ComponentRecord(id="npn-generic", category="transistor", description="Generic NPN BJT (SPICE: BF=100, IS=1e-14); pinout must be checked against the chosen real part", package="TO-92 THT", spice_model=True),
    ComponentRecord(id="nmos-generic", category="mosfet", description="Generic N-MOSFET (SPICE level 1: VTO=2 V, KP=0.5); real Rds(on)/Vth must come from a datasheet", package="TO-220 THT", spice_model=True),
    ComponentRecord(id="pnp-generic", category="transistor", description="Generic PNP BJT (SPICE: BF=100, IS=1e-14); pinout must be checked against the chosen real part", package="TO-92 THT", spice_model=True),
    ComponentRecord(id="pmos-generic", category="mosfet", description="Generic P-MOSFET (SPICE level 1: VTO=-2 V, KP=0.25); real Rds(on)/Vth must come from a datasheet", package="TO-220 THT", spice_model=True),
    ComponentRecord(id="reg-generic-78xx", category="regulator", description="Generic fixed linear regulator, 78xx-style pinout (IN, GND, OUT); behavioral SPICE model with assumed 2 V dropout, 50 mOhm output resistance, no quiescent current", package="TO-220 THT", spice_model=True),
    ComponentRecord(id="inductor-generic", category="inductor", description="Generic axial inductor / relay coil inductance", package="axial THT", spice_model=True),
    ComponentRecord(id="opamp-ideal", category="ic", description="Ideal op-amp (gain 1e6, no rails or bandwidth limits); simulation only, NOT a real part", spice_model=True),
    ComponentRecord(id="src-dc", category="source", description="Ideal DC voltage source (simulation only)", spice_model=True),
]


def search(q: str = "", category: str | None = None) -> list[ComponentRecord]:
    q = q.lower().strip()
    return [c for c in SEED if (not category or c.category == category)
            and (not q or q in c.description.lower() or q in c.id or q in c.category)]
