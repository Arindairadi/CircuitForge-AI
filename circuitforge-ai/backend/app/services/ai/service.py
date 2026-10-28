"""Provider-independent AI layer. Output is untrusted: always schema-validated, then validated again by the circuit model.
Uses an OpenAI-compatible endpoint if AI_BASE_URL and AI_API_KEY are set; otherwise (or on any failure) a deterministic parser."""
import json, os, re
import httpx
from typing import Literal
from pydantic import BaseModel, ValidationError
from app.schemas.circuit import Circuit, Component, PINS
from app.services.circuit_generation.templates import TEMPLATES
from app.services.engineering_calculations import calc


class ParsedRequest(BaseModel):
    template: str | None = None
    params: dict[str, float] = {}
    questions: list[str] = []
    notes: list[str] = []
    source: str = "deterministic"


def _complete(prompt: str) -> str:  # patched in tests; real endpoint path is untested here
    base, key = os.environ["AI_BASE_URL"].rstrip("/"), os.environ["AI_API_KEY"]
    r = httpx.post(f"{base}/chat/completions", timeout=30, headers={"Authorization": f"Bearer {key}"}, json={
        "model": os.environ.get("AI_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": "Return ONLY JSON: {template: one of %s, params: {numbers in SI units}, questions: [], notes: []}. "
                      "params keys: led: vs,vf,i_led; voltage_divider: vin,r1,r2; rc_lowpass: vin,r,c. Use null template if unsupported." % sorted(TEMPLATES)},
                     {"role": "user", "content": prompt[:2000]}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


VOLT = re.compile(r"(\d+(?:\.\d+)?)\s*v(?:olt)?s?\b", re.I)


def _deterministic(prompt: str) -> ParsedRequest:
    p, v = prompt.lower(), VOLT.search(prompt)
    volts = float(v.group(1)) if v else None
    if "divider" in p: t = "voltage_divider"
    elif re.search(r"\brc\b|low-?pass|filter", p): t = "rc_lowpass"
    elif "led" in p: t = "led"
    else:
        return ParsedRequest(questions=[], notes=[f"Unsupported request. Supported templates: {sorted(TEMPLATES)}"])
    q, params, notes = [], {}, []
    if volts is None:
        q.append("What is the supply voltage?"); notes.append("Defaulting to 5 V until you answer")
    else:
        params["vs" if t == "led" else "vin"] = volts
    return ParsedRequest(template=t, params=params, questions=q, notes=notes)


def parse_request(prompt: str) -> ParsedRequest:
    if os.environ.get("AI_BASE_URL") and os.environ.get("AI_API_KEY"):
        try:
            pr = ParsedRequest.model_validate(json.loads(_complete(prompt)))
            if pr.template is None or pr.template in TEMPLATES:
                pr.source = "llm"; return pr
        except (httpx.HTTPError, ValidationError, ValueError, KeyError):
            pass  # fall through to deterministic parser
    return _deterministic(prompt)


class Proposal(BaseModel):
    understood: bool
    message: str
    circuit: Circuit | None = None
    changes: list[str] = []


def diff(old: Circuit, new: Circuit) -> list[str]:
    o, n = {c.ref: c for c in old.components}, {c.ref: c for c in new.components}
    out = [f"added {r}" for r in n if r not in o] + [f"removed {r}" for r in o if r not in n]
    out += [f"{r}: {o[r].model_dump(exclude={'ref'})} -> {n[r].model_dump(exclude={'ref'})}" for r in n if r in o and o[r] != n[r]]
    return out


class Operation(BaseModel):
    op: Literal["set_value", "remove", "add", "set_pin"]
    ref: str | None = None
    value: float | None = None
    pin: str | None = None
    net: str | None = None
    component: dict | None = None


class OpList(BaseModel):
    operations: list[Operation] = []
    explanation: str = ""


SI = {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9}


def _next_ref(c: Circuit, prefix: str) -> str:
    used = {x.ref for x in c.components}; n = 1
    while f"{prefix}{n}" in used: n += 1
    return f"{prefix}{n}"


def apply_operations(c: Circuit, ops: list[Operation]) -> Circuit:
    """Apply validated operations to a COPY; the result is re-validated by the Circuit model. Raises ValueError on any bad op."""
    if len(ops) > 10: raise ValueError("Too many operations (max 10)")
    data = c.model_dump()
    comps = {x["ref"]: x for x in data["components"]}
    for o in ops:
        if o.op == "add":
            comp = Component.model_validate(o.component or {})  # schema-checked
            if comp.ref in comps: raise ValueError(f"{comp.ref} already exists")
            comps[comp.ref] = comp.model_dump()
        else:
            if o.ref not in comps: raise ValueError(f"Unknown component {o.ref!r}")
            if o.op == "remove": del comps[o.ref]
            elif o.op == "set_value":
                if o.value is None or o.value <= 0 or comps[o.ref]["kind"] not in ("V", "R", "C", "L", "REG", "OA"): raise ValueError(f"Cannot set a value on {o.ref}")
                comps[o.ref]["value"] = o.value
            elif o.op == "set_pin":
                if o.pin not in PINS[comps[o.ref]["kind"]] or not o.net or not re.fullmatch(r"[A-Za-z0-9_]+", o.net): raise ValueError("Bad pin or net")
                comps[o.ref]["pins"][o.pin] = o.net
    data["components"] = list(comps.values()); data["simulation_status"] = "not_run"; data["verification_status"] = "not_run"
    return Circuit.model_validate(data)


def _complete_ops(c: Circuit, instruction: str) -> str:  # patched in tests; real endpoint path is untested here
    base, key = os.environ["AI_BASE_URL"].rstrip("/"), os.environ["AI_API_KEY"]
    r = httpx.post(f"{base}/chat/completions", timeout=30, headers={"Authorization": f"Bearer {key}"}, json={
        "model": os.environ.get("AI_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": 'Edit a circuit. Return ONLY JSON {"operations":[{"op":"set_value|remove|add|set_pin","ref":..,"value":..(SI),"pin":..,"net":..,"component":{ref,kind,value,pins,rating}}],"explanation":""}. Kinds: V,R,C,L,LED,D,Q,QP,M,MP,OA. Net "0" is ground. Max 10 ops.'},
                     {"role": "user", "content": json.dumps({"circuit": json.loads(c.model_dump_json()), "instruction": instruction[:500]})}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _det_ops(c: Circuit, ins: str) -> OpList | None:
    m = re.search(r"set\s+([A-Za-z]{1,3}\d{1,4})\s*(?:to|=)\s*(\d+(?:\.\d+)?)\s*(meg|[pnumkg])?\s*(?:ohms?|f|h|v)?\b", ins, re.I)
    if m:
        ref = m.group(1).upper(); return OpList(operations=[Operation(op="set_value", ref=ref, value=float(m.group(2)) * SI[(m.group(3) or "").lower()])], explanation=f"Set {ref}")
    m = re.search(r"remove\s+([A-Za-z]{1,3}\d{1,4})\b", ins, re.I)
    if m: return OpList(operations=[Operation(op="remove", ref=m.group(1).upper())], explanation="Remove part")
    if re.search(r"flyback|freewheel", ins, re.I):
        coil = next((x for x in c.components if x.kind == "L"), None)
        sw = next((x for x in c.components if x.kind in ("M", "Q")), None)
        src = next((x for x in c.components if x.kind == "V" and not x.pulse), None)
        if not (coil and sw and src): return OpList(explanation="Need an inductor, a switching transistor and a DC supply")
        sup = src.pins["p"]; swnet = sw.pins["d" if sw.kind == "M" else "c"]
        if any(x.kind == "D" and x.pins.get("a") == swnet and x.pins.get("k") == sup for x in c.components):
            return OpList(explanation="A flyback diode is already present")
        return OpList(operations=[Operation(op="add", component={"ref": _next_ref(c, "D"), "kind": "D", "pins": {"a": swnet, "k": sup}, "rating": 1.0})],
                      explanation="Diode from the switch node to the supply, across the inductive load (generic diode, 1 A rating assumed)")
    return None


def propose_change(c: Circuit, instruction: str) -> Proposal:
    """Edits are computed on a copy and returned as a preview; nothing is applied until the user approves via PUT."""
    ops = None
    if os.environ.get("AI_BASE_URL") and os.environ.get("AI_API_KEY"):
        try:
            cand = OpList.model_validate(json.loads(_complete_ops(c, instruction)))
            if cand.operations: apply_operations(c, cand.operations); ops = cand  # must validate before it is shown
        except (httpx.HTTPError, ValidationError, ValueError, KeyError):
            ops = None
    if ops is None: ops = _det_ops(c, instruction)
    if ops is not None:
        if not ops.operations: return Proposal(understood=True, message=ops.explanation or "No change needed")
        try: new = apply_operations(c, ops.operations)
        except (ValueError, ValidationError) as e: return Proposal(understood=True, message=f"Cannot apply: {e}")
        from app.services.verification.checks import verify
        errs = [f for f in verify(new) if f.severity == "error" and f.executed]
        warn = f" Static checks on the proposed design: {len(errs)} errors." + ("".join(f" [{f.check}] {f.target}" for f in errs[:3]) if errs else "")
        return Proposal(understood=True, message=f"{ops.explanation}. Review the changes; nothing is applied until you approve.{warn}", circuit=new, changes=diff(c, new))
    return _voltage_change(c, instruction)


def _voltage_change(c: Circuit, instruction: str) -> Proposal:
    """Change input voltage (recomputes the LED resistor when applicable)."""
    m = re.search(r"(?:input|supply)?\s*voltage\s*(?:to|=)\s*(\d+(?:\.\d+)?)\s*v", instruction, re.I)
    if not m:
        return Proposal(understood=False, message="Supported: 'change the input voltage to <N> V', 'set R1 to 4.7k', 'remove R3', 'add a flyback diode'; with an AI provider configured, other edits are attempted and validated. Nothing was changed.")
    vs, new = float(m.group(1)), c.model_copy(deep=True)
    src = next((x for x in new.components if x.kind == "V"), None)
    if not src: return Proposal(understood=False, message="No voltage source in this design")
    src.value = vs
    led = next((x for x in new.components if x.kind == "LED"), None)
    r1 = next((x for x in new.components if x.ref == "R1" and x.kind == "R"), None)
    notes = []
    if led and r1:
        try: res = calc.led_resistor(vs, 2.0, 0.010)
        except ValueError as e: return Proposal(understood=True, message=f"Cannot apply: {e}")
        r1.value = res.result; notes.append(f"Recomputed R1 for 10 mA at Vf~2.0 V (assumed): {res.substitution}")
    new.simulation_status = "not_run"; new.verification_status = "not_run"
    return Proposal(understood=True, message="Review the changes; nothing is applied until you approve. Re-run verification and simulation afterwards. " + " ".join(notes),
                    circuit=new, changes=diff(c, new))
