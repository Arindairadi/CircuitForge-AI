"""Structured, presentation-independent circuit model."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator

Kind = Literal["V", "R", "C", "LED", "D", "Q", "M", "L", "OA", "QP", "MP", "REG"]
PINS = {"V": ("p", "n"), "R": ("1", "2"), "C": ("1", "2"), "LED": ("a", "k"), "D": ("a", "k"),
        "Q": ("b", "c", "e"), "M": ("g", "d", "s"), "L": ("1", "2"), "OA": ("p", "n", "o"), "QP": ("b", "c", "e"), "MP": ("g", "d", "s"), "REG": ("in", "gnd", "out")}
REG_DROPOUT_V = 2.0  # generic linear-regulator dropout assumption (not from a datasheet)
GROUND = "0"


class Component(BaseModel):
    ref: str = Field(pattern=r"^[A-Z]{1,3}[0-9]{1,4}$")
    kind: Kind
    value: float | None = None          # SI units: V, ohm, F (None for LED)
    pins: dict[str, str] = Field(default_factory=dict)  # pin -> net name
    rating: float | None = None         # R: watts (default 0.25); LED/D/Q/M: max amps (LED default 0.02; others must be set)
    pulse: list[float] | None = None    # V only: [v1, v2, delay, rise, fall, width, period] (seconds)
    datasheet: str | None = None        # only set when a real source is known

    @model_validator(mode="after")
    def _pins_known(self):
        if self.pulse is not None and (self.kind != "V" or len(self.pulse) != 7):
            raise ValueError(f"{self.ref}: pulse must be 7 numbers on a voltage source")
        bad = set(self.pins) - set(PINS[self.kind])
        if bad:
            raise ValueError(f"{self.ref}: unknown pins {sorted(bad)}")
        return self


class Circuit(BaseModel):
    name: str
    components: list[Component]
    assumptions: list[str] = []
    simulation_status: Literal["not_run", "simulated", "failed"] = "not_run"
    verification_status: Literal["not_run", "run"] = "not_run"
    version: int = 1

    @model_validator(mode="after")
    def _unique_refs(self):
        refs = [c.ref for c in self.components]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate component references")
        return self

    def nets(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {}
        for c in self.components:
            for pin, net in c.pins.items():
                out.setdefault(net, []).append((c.ref, pin))
        return out
