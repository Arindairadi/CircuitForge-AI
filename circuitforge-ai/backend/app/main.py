import hashlib, json, logging, secrets
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
import os
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.db import Base, engine, get_db
from app.models.tables import CustomComponent, Datasheet, PartAssignment, AuditEvent, Job, Project, ProjectMember, ProjectVersion, Token, User, now
from app.core.db import SessionLocal
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from app.schemas.circuit import Circuit
from app.services.circuit_generation.templates import generate, TEMPLATES
from app.services.engineering_calculations import calc
from app.services.simulation import spice
from app.services.verification.checks import verify
from app.services.component_database import db as compdb
from app.services.component_database import distributors
import re, uuid
from app.services.ai import service as ai
from app.services.optimization import optimizer
from app.integrations.kicad import schematic as kicad
from app.integrations.kicad import pcb as kicad_pcb
from pathlib import Path
import time, collections, subprocess
from fastapi.responses import FileResponse
from app.services.learning.content import LESSONS, GLOSSARY
from app.services.reporting import bom as bomlib

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("circuitforge")
app = FastAPI(title="CircuitForge AI", version="0.1.0")
if os.environ.get("CF_AUTO_CREATE") == "1":  # tests/dev only; production uses `alembic upgrade head`
    Base.metadata.create_all(engine)
ph = PasswordHash.recommended()
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","), allow_methods=["*"], allow_headers=["*"])


class Cred(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    password: str = Field(min_length=8, max_length=128)


def _h(t: str) -> str: return hashlib.sha256(t.encode()).hexdigest()


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    tok = authorization.removeprefix("Bearer ").strip()
    row = db.get(Token, _h(tok)) if tok else None
    if not row or (dt.datetime.now(dt.UTC).replace(tzinfo=None) - row.created_at) > dt.timedelta(days=int(os.environ.get("TOKEN_TTL_DAYS", "7"))):
        raise HTTPException(401, "Invalid or missing token")
    return db.get(User, row.user_id)


_hits: dict[int, collections.deque] = collections.defaultdict(collections.deque)
RATE = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))


def rate_limit(user: User = Depends(current_user)):
    q, now = _hits[user.id], time.monotonic()
    while q and now - q[0] > 60: q.popleft()
    if len(q) >= RATE: raise HTTPException(429, "Rate limit exceeded; try again in a minute")
    q.append(now)


@app.get("/health")
def health(): return {"status": "ok", "ngspice": spice.engine_version(), "kicad_cli": kicad.available()}


@app.post("/auth/register", status_code=201)
def register(c: Cred, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == c.email.lower())): raise HTTPException(409, "Email already registered")
    db.add(User(email=c.email.lower(), password_hash=ph.hash(c.password))); db.commit()
    return {"status": "registered"}


@app.post("/auth/login")
def login(c: Cred, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == c.email.lower()))
    if not u or not ph.verify(c.password, u.password_hash): raise HTTPException(401, "Invalid credentials")
    t = secrets.token_urlsafe(32)
    db.add(Token(token_hash=_h(t), user_id=u.id)); db.commit()
    return {"access_token": t}


def _overrides(db: Session, pid: int) -> dict:
    return {a.ref: {"manufacturer": a.manufacturer, "mpn": a.mpn, "datasheet_url": a.datasheet_url, "price": a.price, "availability": a.availability, "notes": a.notes}
            for a in db.scalars(select(PartAssignment).where(PartAssignment.project_id == pid)).all()}


# per-user daily AI quota (in-memory, per process)
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "200"))
_ai_used: dict[tuple[int, str], int] = collections.defaultdict(int)


def ai_quota(user: User = Depends(current_user)):
    key = (user.id, dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"))
    if _ai_used[key] >= AI_DAILY_LIMIT: raise HTTPException(429, f"Daily AI request limit ({AI_DAILY_LIMIT}) reached")
    _ai_used[key] += 1


RANK = {"viewer": 1, "editor": 2, "owner": 3}


def _owned(db: Session, pid: int, user: User, role: str = "owner") -> Project:
    """Access check. Non-members get 404 (no existence leak); members with too low a role get 403."""
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    if p.owner_id == user.id: return p
    m = db.scalar(select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == user.id))
    if not m: raise HTTPException(404, "Project not found")
    if role == "owner" or RANK[m.role] < RANK[role]: raise HTTPException(403, f"Requires {role} access")
    return p


def _audit(db: Session, user: User, pid: int | None, action: str, detail: str = ""):
    db.add(AuditEvent(user_id=user.id, project_id=pid, action=action, detail=detail[:500])); db.commit()


def _save_version(db, p: Project, circuit: Circuit, results: dict | None = None):
    n = (p.versions[-1].number + 1) if p.versions else 1
    circuit.version = n
    db.add(ProjectVersion(project_id=p.id, number=n, circuit_json=circuit.model_dump_json(), results_json=json.dumps(results or {})))
    db.commit(); db.refresh(p)


def _currents(r: dict) -> dict | None:
    op = r.get("op")
    return op.get("component_currents") if op else None  # per-component currents from ngspice (no single-loop assumption)


def _latest(p: Project) -> tuple[Circuit, dict]:
    if not p.versions: raise HTTPException(409, "Project has no circuit yet")
    v = p.versions[-1]
    return Circuit.model_validate_json(v.circuit_json), json.loads(v.results_json)


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template: str | None = None
    params: dict[str, float] = {}


@app.get("/templates")
def templates(): return {"templates": sorted(TEMPLATES)}


@app.post("/projects", status_code=201)
def create_project(body: NewProject, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = Project(owner_id=user.id, name=body.name); db.add(p); db.commit(); db.refresh(p)
    if body.template:
        try: circuit = generate(body.template, **body.params)
        except (ValueError, TypeError) as e: raise HTTPException(422, str(e))
        _save_version(db, p, circuit)
    _audit(db, user, p.id, "project.create", f"name={p.name!r} template={body.template}")
    return {"id": p.id, "name": p.name, "versions": len(p.versions)}


@app.get("/projects")
def list_projects(skip: int = 0, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(current_user)):
    shared = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    rows = db.scalars(select(Project).where((Project.owner_id == user.id) | Project.id.in_(shared)).order_by(Project.id).offset(skip).limit(min(limit, 100))).all()
    return [{"id": p.id, "name": p.name, "versions": len(p.versions), "owned": p.owner_id == user.id} for p in rows]


@app.get("/projects/{pid}")
def get_project(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer"); c, r = _latest(p)
    return {"id": p.id, "name": p.name, "notes": p.notes, "circuit": c, "results": r}


@app.put("/projects/{pid}/circuit")
def update_circuit(pid: int, circuit: Circuit, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); _save_version(db, p, circuit)  # new version; previous results are not carried over
    _audit(db, user, p.id, "circuit.update", f"new version {circuit.version}, {len(circuit.components)} components")
    return {"version": circuit.version}


@app.delete("/projects/{pid}", status_code=204)
def delete_project(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user); _audit(db, user, p.id, "project.delete", p.name); db.delete(p); db.commit()


@app.post("/projects/{pid}/verify")
def verify_project(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, r = _latest(p)
    findings = verify(c, _currents(r), (r.get("op") or {}).get("node_voltages"))
    r["verification"] = [f.model_dump() for f in findings]
    p.versions[-1].results_json = json.dumps(r); db.commit()
    return {"findings": findings, "disclaimer": "Automated checks only; not certification"}


class SimReq(BaseModel):
    analysis: str = Field(pattern="^(op|tran|ac|dc)$")
    node: str | None = None
    fstart: float | None = None
    fstop: float | None = None
    source: str | None = None
    start: float | None = None
    stop: float | None = None
    step: float | None = None
    tstep: float | None = None
    tstop: float | None = None


@app.post("/projects/{pid}/simulate", dependencies=[Depends(rate_limit)])
def simulate(pid: int, req: SimReq, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, r = _latest(p)
    try:
        if req.analysis == "op": res = spice.operating_point(c)
        elif req.analysis == "dc":
            if not (req.source and req.node and req.start is not None and req.stop is not None and req.step): raise HTTPException(422, "source, node, start, stop, step required")
            res = spice.dc_sweep(c, req.source, req.node, req.start, req.stop, req.step)
        elif req.analysis == "ac":
            if not (req.node and req.fstart and req.fstop): raise HTTPException(422, "node, fstart, fstop required")
            res = spice.ac(c, req.node, req.fstart, req.fstop)
        else:
            if not (req.node and req.tstep and req.tstop): raise HTTPException(422, "node, tstep, tstop required")
            res = spice.transient(c, req.node, req.tstep, req.tstop)
    except spice.SimulationError as e:
        raise HTTPException(422, f"Simulation failed: {e}")  # never fabricate a waveform
    r[req.analysis] = res
    p.versions[-1].results_json = json.dumps(r); db.commit()
    return res


class CalcReq(BaseModel):
    kind: str
    args: dict[str, float]


@app.post("/calculate")
def calculate(req: CalcReq):
    fns = {"ohms_law_current": calc.ohms_law_current, "led_resistor": calc.led_resistor, "voltage_divider": calc.voltage_divider,
           "power": calc.power_dissipation, "rc_time_constant": calc.rc_time_constant, "rc_cutoff": calc.rc_cutoff,
           "bjt_base_resistor": calc.bjt_base_resistor, "regulator_dissipation": calc.regulator_dissipation, "battery_runtime": calc.battery_runtime,
           "capacitor_energy": calc.capacitor_energy, "mosfet_switch_check": calc.mosfet_switch_check}
    if req.kind not in fns: raise HTTPException(422, f"Unknown calculation. Available: {sorted(fns)}")
    try: return fns[req.kind](**req.args)
    except (ValueError, TypeError) as e: raise HTTPException(422, str(e))


@app.get("/components")
def components(q: str = "", category: str | None = None): return compdb.search(q, category)


@app.get("/projects/{pid}/bom")
def bom(pid: int, format: str = "json", db: Session = Depends(get_db), user: User = Depends(current_user)):
    c, _ = _latest(_owned(db, pid, user, "viewer")); rows = bomlib.build_bom(c, _overrides(db, pid))
    if format == "csv": return Response(bomlib.to_csv(rows), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=bom.csv"})
    return rows


class Prompt(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


@app.post("/ai/parse", dependencies=[Depends(rate_limit), Depends(ai_quota)])
def ai_parse(body: Prompt, user: User = Depends(current_user)):
    return ai.parse_request(body.prompt)  # a proposal only; nothing is created


class Instruction(BaseModel):
    instruction: str = Field(min_length=3, max_length=500)


@app.post("/projects/{pid}/ai/propose", dependencies=[Depends(rate_limit), Depends(ai_quota)])
def ai_propose(pid: int, body: Instruction, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c, _ = _latest(_owned(db, pid, user, "viewer"))
    return ai.propose_change(c, body.instruction)  # apply with PUT /projects/{pid}/circuit after approval


@app.post("/projects/{pid}/review")
def review(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer"); c, r = _latest(p)
    op = r.get("op"); currents = _currents(r); facts = []
    if op:
        i = abs(next(iter(op["source_currents"].values()), 0.0))
        facts.append(f"ngspice operating point ({op['engine']}) gave source current {i*1e3:.3f} mA with ideal/approximate models")
    findings = verify(c, currents, (op or {}).get("node_voltages"))
    pick = lambda sev: [f for f in findings if f.severity == sev and f.executed]
    return {"summary": f"{len(pick('error'))} errors, {len(pick('warning'))} warnings from automated checks. Not a safety or production certification.",
            "critical_issues": pick("error"), "warnings": pick("warning"), "verified_facts": facts,
            "unverified_assumptions": c.assumptions, "checks_not_executed": [f for f in findings if not f.executed],
            "tests_required": ["Bench measurement of the built circuit", "Datasheet check of real part ratings"] + ([] if op else ["Run an operating-point simulation"]),
            "source": "deterministic rules (no AI model used)"}


@app.get("/learning/{template}")
def learning(template: str):
    if template not in LESSONS: raise HTTPException(404, "No lesson for this template")
    return {**LESSONS[template], "glossary": GLOSSARY}


ART = Path(os.environ.get("ARTIFACT_DIR", "./artifacts"))
KICAD_FILES = {"design.kicad_sch", "design.net", "design.pdf", "design.kicad_pcb", "drc.rpt", "positions.csv", "design.svg", "fabrication.zip", "layout.json"}  # whitelist: no user-controlled paths


@app.post("/projects/{pid}/export/kicad", dependencies=[Depends(rate_limit)])
def export_kicad(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, _ = _latest(p)
    if not kicad.available(): raise HTTPException(503, "kicad-cli is not installed on the server")
    try: res = kicad.export_and_validate(c, ART / str(p.id) / f"v{c.version}")
    except kicad.KicadError as e: raise HTTPException(422, f"KiCad export failed: {e}")
    return {**res, "version": c.version}


@app.get("/projects/{pid}/export/kicad/{filename}")
def download_kicad(pid: int, filename: str, version: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer")
    if filename not in KICAD_FILES: raise HTTPException(404, "Unknown file")
    f = ART / str(p.id) / f"v{version or _latest(p)[0].version}" / filename
    if not f.is_file(): raise HTTPException(404, "File not generated yet")
    return FileResponse(f, filename=filename)


@app.get("/projects/{pid}/versions")
def versions(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer")
    return [{"number": v.number, "created_at": v.created_at, "components": len(Circuit.model_validate_json(v.circuit_json).components)} for v in p.versions]


@app.get("/projects/{pid}/versions/{a}/diff/{b}")
def version_diff(pid: int, a: int, b: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer"); by = {v.number: v for v in p.versions}
    if a not in by or b not in by: raise HTTPException(404, "Version not found")
    return {"from": a, "to": b, "changes": ai.diff(Circuit.model_validate_json(by[a].circuit_json), Circuit.model_validate_json(by[b].circuit_json))}


class OptReq(BaseModel):
    objective: str = Field(pattern="^(lower_power|hit_target_voltage|smaller_pcb_area)$")
    target_led_current_ma: float = 5.0
    min_led_current_ma: float = 2.0
    target_v: float | None = None
    tolerance_pct: float = 1.0


@app.post("/projects/{pid}/optimize", dependencies=[Depends(rate_limit)])
def optimize(pid: int, req: OptReq, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c, _ = _latest(_owned(db, pid, user, "viewer"))
    if req.objective == "smaller_pcb_area":
        if not (kicad.available() and kicad_pcb.pcbnew_available()): raise HTTPException(503, "KiCad/pcbnew is not available on the server")
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as td: return kicad_pcb.optimize_pcb_area(c, Path(td))
        except (kicad.KicadError, subprocess.TimeoutExpired) as e: raise HTTPException(422, f"PCB optimization failed: {e}")
    if req.objective == "hit_target_voltage":
        if req.target_v is None: raise HTTPException(422, "target_v is required")
        return optimizer.optimize_divider_target(c, req.target_v, req.tolerance_pct)
    return optimizer.optimize_led_power(c, req.target_led_current_ma, req.min_led_current_ma)


@app.post("/projects/{pid}/pcb/generate", dependencies=[Depends(rate_limit)])
def generate_pcb(pid: int, pitch_mm: float = Query(25.0, ge=8, le=40), db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, _ = _latest(p)
    if not kicad.available(): raise HTTPException(503, "kicad-cli is not installed on the server")
    try: res = kicad_pcb.generate_pcb(c, ART / str(p.id) / f"v{c.version}", pitch=pitch_mm)
    except (kicad.KicadError, subprocess.TimeoutExpired) as e: raise HTTPException(422, f"PCB generation failed: {e}")
    return {**res, "version": c.version}


@app.post("/auth/logout", status_code=204)
def logout(authorization: str = Header(default=""), db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(Token, _h(authorization.removeprefix("Bearer ").strip()))
    if row: db.delete(row); db.commit()


@app.get("/me")
def me(user: User = Depends(current_user)): return {"email": user.email}


class PwChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@app.put("/me/password", status_code=204)
def change_password(body: PwChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not ph.verify(body.current_password, user.password_hash): raise HTTPException(403, "Current password is incorrect")
    user.password_hash = ph.hash(body.new_password)
    for t in db.scalars(select(Token).where(Token.user_id == user.id)).all(): db.delete(t)  # revoke all sessions
    db.commit(); _audit(db, user, None, "user.password_change")


class Member(BaseModel):
    email: str
    role: str = Field(pattern="^(viewer|editor)$")


@app.post("/projects/{pid}/members", status_code=201)
def add_member(pid: int, body: Member, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user)
    other = db.scalar(select(User).where(User.email == body.email.lower()))
    if not other: raise HTTPException(404, "No user with that email")
    if other.id == user.id: raise HTTPException(422, "You already own this project")
    m = db.scalar(select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == other.id))
    if m: m.role = body.role
    else: db.add(ProjectMember(project_id=pid, user_id=other.id, role=body.role))
    db.commit(); _audit(db, user, pid, "member.add", f"{other.email} as {body.role}")
    return {"email": other.email, "role": body.role}


@app.get("/projects/{pid}/members")
def list_members(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user)
    return [{"email": db.get(User, m.user_id).email, "role": m.role} for m in db.scalars(select(ProjectMember).where(ProjectMember.project_id == pid)).all()]


@app.delete("/projects/{pid}/members/{email}", status_code=204)
def remove_member(pid: int, email: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user)
    other = db.scalar(select(User).where(User.email == email.lower()))
    m = other and db.scalar(select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == other.id))
    if not m: raise HTTPException(404, "Member not found")
    db.delete(m); db.commit(); _audit(db, user, pid, "member.remove", email)


@app.get("/projects/{pid}/audit")
def audit_log(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.project_id == pid).order_by(AuditEvent.id.desc()).limit(100)).all()
    return [{"action": a.action, "detail": a.detail, "by": db.get(User, a.user_id).email, "at": a.created_at} for a in rows]


# ---- background jobs (thread pool; status persisted in the DB)
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("JOB_WORKERS", "2")))


class JobReq(BaseModel):
    kind: str = Field(pattern="^(simulate|pcb)$")
    params: dict = {}


def _run_job(job_id: int, pid: int, version: int):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id); job.status = "running"; db.commit()
        pv = db.scalar(select(ProjectVersion).where(ProjectVersion.project_id == pid, ProjectVersion.number == version))
        c, params = Circuit.model_validate_json(pv.circuit_json), json.loads(job.params_json)
        if job.kind == "simulate":
            a = params.get("analysis")
            if a == "op": res = spice.operating_point(c)
            elif a == "tran": res = spice.transient(c, str(params["node"]), float(params["tstep"]), float(params["tstop"]))
            elif a == "ac": res = spice.ac(c, str(params["node"]), float(params["fstart"]), float(params["fstop"]))
            else: raise ValueError("analysis must be op, tran or ac")
            r = json.loads(pv.results_json); r[a] = res; pv.results_json = json.dumps(r)
        else:
            res = kicad_pcb.generate_pcb(c, ART / str(pid) / f"v{version}")
        job.result_json = json.dumps(res); job.status = "done"
    except Exception as e:  # recorded as a failed job; never a fabricated result
        db.rollback(); job = db.get(Job, job_id); job.status = "failed"; job.error = f"{type(e).__name__}: {e}"[:500]
    finally:
        job = db.get(Job, job_id); job.finished_at = now(); db.commit(); db.close()


@app.post("/projects/{pid}/jobs", status_code=202, dependencies=[Depends(rate_limit)])
def create_job(pid: int, req: JobReq, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, _ = _latest(p)
    job = Job(project_id=p.id, user_id=user.id, kind=req.kind, params_json=json.dumps(req.params)); db.add(job); db.commit()
    _pool.submit(_run_job, job.id, p.id, c.version)
    return {"id": job.id, "status": job.status}


@app.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    _owned(db, job.project_id, user, "viewer")  # same access rule as the project
    return {"id": job.id, "kind": job.kind, "status": job.status, "error": job.error or None, "result": json.loads(job.result_json) if job.result_json else None}


class SweepReq(BaseModel):
    ref: str
    node: str
    start: float
    stop: float
    points: int = Field(ge=2, le=50)


@app.post("/projects/{pid}/sweep", dependencies=[Depends(rate_limit)])
def sweep(pid: int, req: SweepReq, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c, _ = _latest(_owned(db, pid, user, "viewer"))
    try: return spice.param_sweep(c, req.ref, req.start, req.stop, req.points, req.node)
    except spice.SimulationError as e: raise HTTPException(422, f"Sweep failed: {e}")


class Notes(BaseModel):
    notes: str = Field(max_length=10000)


@app.put("/projects/{pid}/notes", status_code=204)
def set_notes(pid: int, body: Notes, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); p.notes = body.notes; db.commit(); _audit(db, user, p.id, "notes.update")


class ProjectFile(BaseModel):
    format: str = Field(pattern="^circuitforge-project$")
    schema_version: int = 1
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=10000)
    circuit: Circuit


@app.get("/projects/{pid}/export")
def export_project(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "viewer"); c, _ = _latest(p)
    return ProjectFile(format="circuitforge-project", name=p.name, notes=p.notes, circuit=c)


@app.post("/projects/import", status_code=201)
def import_project(body: ProjectFile, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if len(body.circuit.components) > 500: raise HTTPException(422, "Too many components (max 500)")
    p = Project(owner_id=user.id, name=body.name, notes=body.notes); db.add(p); db.commit(); db.refresh(p)
    body.circuit.simulation_status = body.circuit.verification_status = "not_run"  # imported files cannot claim results
    _save_version(db, p, body.circuit); _audit(db, user, p.id, "project.import", p.name)
    return {"id": p.id, "name": p.name}


@app.post("/projects/{pid}/duplicate", status_code=201)
def duplicate_project(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    src = _owned(db, pid, user, "viewer"); c, _ = _latest(src)
    p = Project(owner_id=user.id, name=f"{src.name} (copy)"[:200], notes=src.notes); db.add(p); db.commit(); db.refresh(p)
    c.simulation_status = c.verification_status = "not_run"
    _save_version(db, p, c); _audit(db, user, p.id, "project.duplicate", f"from {src.id}")
    return {"id": p.id, "name": p.name}


URL_PATTERN = r"^https?://[^\s]{3,480}$"


class ManualComponent(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=300)
    manufacturer: str | None = Field(default=None, max_length=100)
    part_number: str | None = Field(default=None, max_length=100)
    package: str | None = Field(default=None, max_length=60)
    datasheet_url: str | None = Field(default=None, pattern=URL_PATTERN)
    specs: dict[str, float | str] = {}


@app.post("/components/manual", status_code=201)
def add_manual_component(body: ManualComponent, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if len(body.specs) > 20: raise HTTPException(422, "At most 20 specs")
    cc = CustomComponent(owner_id=user.id, category=body.category.lower(), description=body.description, manufacturer=body.manufacturer, part_number=body.part_number,
                         package=body.package, datasheet_url=body.datasheet_url, specs_json=json.dumps(body.specs)); db.add(cc); db.commit()
    return {"id": cc.id}


@app.get("/components/mine")
def my_components(q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(CustomComponent).where(CustomComponent.owner_id == user.id).order_by(CustomComponent.id)).all()
    ql = q.lower().strip()
    return [{"id": r.id, "category": r.category, "description": r.description, "manufacturer": r.manufacturer, "part_number": r.part_number, "package": r.package,
             "datasheet_url": r.datasheet_url, "specs": json.loads(r.specs_json), "source": "user-entered (not verified by CircuitForge)"}
            for r in rows if not ql or ql in r.description.lower() or ql in (r.part_number or "").lower() or ql in r.category]


@app.get("/components/lookup", dependencies=[Depends(rate_limit)])
def lookup_part(mpn: str = Query(min_length=1, max_length=80), user: User = Depends(current_user)):
    try: return {"results": distributors.MouserAdapter().search_part_number(mpn)}
    except distributors.DistributorUnavailable as e: raise HTTPException(503, str(e))


class Assign(BaseModel):
    ref: str = Field(pattern=r"^[A-Z]{1,3}[0-9]{1,4}$")
    manufacturer: str | None = Field(default=None, max_length=100)
    mpn: str | None = Field(default=None, max_length=100)
    datasheet_url: str | None = Field(default=None, pattern=URL_PATTERN)
    price: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+(\.[0-9]+)? ?[A-Za-z]{0,3}$")
    availability: str | None = Field(default=None, max_length=100)
    notes: str = Field(default="", max_length=300)


@app.put("/projects/{pid}/bom/parts")
def assign_part(pid: int, body: Assign, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor"); c, _ = _latest(p)
    if body.ref not in {x.ref for x in c.components}: raise HTTPException(422, f"{body.ref} is not in the current design")
    a = db.scalar(select(PartAssignment).where(PartAssignment.project_id == pid, PartAssignment.ref == body.ref)) or PartAssignment(project_id=pid, ref=body.ref)
    for k in ("manufacturer", "mpn", "datasheet_url", "price", "availability", "notes"): setattr(a, k, getattr(body, k))
    a.entered_at = now(); db.add(a); db.commit(); _audit(db, user, pid, "bom.assign", f"{body.ref} -> {body.mpn}")
    return {"ref": a.ref, "source": "user-entered"}


@app.delete("/projects/{pid}/bom/parts/{ref}", status_code=204)
def unassign_part(pid: int, ref: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user, "editor")
    a = db.scalar(select(PartAssignment).where(PartAssignment.project_id == pid, PartAssignment.ref == ref))
    if not a: raise HTTPException(404, "No assignment for that reference")
    db.delete(a); db.commit()


# ---- datasheet uploads (untrusted: stored under server-generated names, never parsed or executed)
from fastapi import File, UploadFile, Query
MAX_DATASHEET = 5 * 1024 * 1024
DS_DIR = lambda pid: ART / "datasheets" / str(pid)


@app.post("/projects/{pid}/datasheets", status_code=201, dependencies=[Depends(rate_limit)])
async def upload_datasheet(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _owned(db, pid, user, "editor")
    if db.scalar(select(func.count()).select_from(Datasheet).where(Datasheet.project_id == pid)) >= 20: raise HTTPException(422, "At most 20 datasheets per project")
    data = await file.read(MAX_DATASHEET + 1)
    if len(data) > MAX_DATASHEET: raise HTTPException(413, "File too large (max 5 MB)")
    if not data.startswith(b"%PDF-"): raise HTTPException(415, "Only PDF files are accepted")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (file.filename or "datasheet.pdf").replace("\\", "/").split("/")[-1])[:90].lstrip(".") or "datasheet.pdf"
    if not base.lower().endswith(".pdf"): base += ".pdf"
    stored = uuid.uuid4().hex + ".pdf"
    d = DS_DIR(pid); d.mkdir(parents=True, exist_ok=True); (d / stored).write_bytes(data)
    row = Datasheet(project_id=pid, uploader_id=user.id, stored_name=stored, display_name=base, size=len(data), sha256=hashlib.sha256(data).hexdigest()); db.add(row); db.commit()
    _audit(db, user, pid, "datasheet.upload", base)
    return {"id": row.id, "name": base, "size": row.size, "sha256": row.sha256}


@app.get("/projects/{pid}/datasheets")
def list_datasheets(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user, "viewer")
    return [{"id": d.id, "name": d.display_name, "size": d.size, "sha256": d.sha256} for d in db.scalars(select(Datasheet).where(Datasheet.project_id == pid).order_by(Datasheet.id)).all()]


@app.get("/projects/{pid}/datasheets/{did}")
def download_datasheet(pid: int, did: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user, "viewer")
    d = db.get(Datasheet, did)
    if not d or d.project_id != pid or not (DS_DIR(pid) / d.stored_name).is_file(): raise HTTPException(404, "Datasheet not found")
    return FileResponse(DS_DIR(pid) / d.stored_name, media_type="application/pdf", filename=d.display_name, headers={"X-Content-Type-Options": "nosniff"})


@app.delete("/projects/{pid}/datasheets/{did}", status_code=204)
def delete_datasheet(pid: int, did: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _owned(db, pid, user, "editor")
    d = db.get(Datasheet, did)
    if not d or d.project_id != pid: raise HTTPException(404, "Datasheet not found")
    (DS_DIR(pid) / d.stored_name).unlink(missing_ok=True); db.delete(d); db.commit(); _audit(db, user, pid, "datasheet.delete", d.display_name)
