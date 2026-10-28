import math, os, pytest
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db"); os.environ["CF_AUTO_CREATE"] = "1"
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.circuit import Circuit, Component
from app.services.circuit_generation.templates import generate
from app.services.engineering_calculations import calc
from app.services.simulation import spice
from app.services.verification.checks import verify

needs_ngspice = pytest.mark.skipif(spice.engine_version() is None, reason="ngspice not installed")


def test_led_resistor_e24():
    r = calc.led_resistor(5, 2, 0.010)
    assert r.result == 300.0 and r.unit == "ohm"  # 300 ohm is an E24 value


def test_divider_and_series_parallel():
    assert calc.voltage_divider(5, 10e3, 10e3).result == pytest.approx(2.5)
    assert calc.parallel_resistance(100, 100) == pytest.approx(50)
    assert calc.rc_time_constant(1e3, 1e-6).result == pytest.approx(1e-3)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError): calc.led_resistor(1.5, 2.0, 0.01)
    with pytest.raises(ValueError): calc.voltage_divider(5, -1, 10)


def test_unknown_template():
    with pytest.raises(ValueError): generate("warp_drive")


def test_unconnected_pin_and_no_ground():
    c = Circuit(name="bad", components=[Component(ref="V1", kind="V", value=5, pins={"p": "a"}),
                                        Component(ref="R1", kind="R", value=100, pins={"1": "a"})])
    checks = {f.check for f in verify(c)}
    assert {"connectivity.unconnected_pin", "connectivity.no_ground"} <= checks


def test_rating_violation_detected():
    c = generate("led", vs=5, vf=2, i_led=0.010)
    c.components[1].value = 10  # 10 ohm -> ~300 mA
    f = verify(c, {"R1": 0.3, "D1": 0.3})
    assert any(x.check == "ratings.led_current" for x in f) and any(x.check == "ratings.resistor_power" for x in f)


def test_ratings_not_executed_without_sim():
    f = verify(generate("led"))
    assert any(x.check == "ratings.dc_current" and not x.executed for x in f)


@needs_ngspice
def test_divider_op_matches_theory():
    res = spice.operating_point(generate("voltage_divider", vin=5, r1=10e3, r2=10e3))
    assert res["node_voltages"]["out"] == pytest.approx(2.5, rel=1e-6)


@needs_ngspice
def test_led_op_current_close_to_target():
    res = spice.operating_point(generate("led"))
    i = abs(res["source_currents"]["V1"])
    assert 0.008 < i < 0.012  # ~10 mA target; LED model is approximate


@needs_ngspice
def test_rc_transient_at_one_tau():
    c = generate("rc_lowpass", vin=5, r=1e3, c=1e-6)
    res = spice.transient(c, "out", 1e-5, 5e-3)
    v_tau = min(zip(res["time"], res["voltage"]), key=lambda tv: abs(tv[0] - 1e-3))[1]
    assert v_tau == pytest.approx(5 * (1 - math.exp(-1)), rel=0.02)


@needs_ngspice
def test_sim_error_surfaced_not_faked():
    c = Circuit(name="bad", components=[Component(ref="R1", kind="R", value=100, pins={"1": "a"})])
    with pytest.raises(spice.SimulationError): spice.operating_point(c)


def _auth(client, email="a@example.com"):
    client.post("/auth/register", json={"email": email, "password": "correct-horse-1"})
    t = client.post("/auth/login", json={"email": email, "password": "correct-horse-1"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_api_auth_ownership_and_workflow():
    client = TestClient(app)
    assert client.get("/projects").status_code == 401
    ha, hb = _auth(client, "alice@example.com"), _auth(client, "bob@example.com")
    assert client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}).status_code == 401
    pid = client.post("/projects", json={"name": "LED", "template": "led"}, headers=ha).json()["id"]
    assert client.get(f"/projects/{pid}", headers=hb).status_code == 404  # other user cannot access
    assert client.post(f"/projects/{pid}/verify", headers=ha).status_code == 200
    if spice.engine_version():
        r = client.post(f"/projects/{pid}/simulate", json={"analysis": "op"}, headers=ha)
        assert r.status_code == 200 and "led_a" in r.json()["node_voltages"]
    assert client.post("/projects", json={"name": "x", "template": "nope"}, headers=ha).status_code == 422
    assert client.delete(f"/projects/{pid}", headers=hb).status_code == 404
    assert client.delete(f"/projects/{pid}", headers=ha).status_code == 204


def test_calculate_endpoint_errors():
    client = TestClient(app)
    assert client.post("/calculate", json={"kind": "voltage_divider", "args": {"vin": 5, "r1": 1e3, "r2": 1e3}}).json()["result"] == 2.5
    assert client.post("/calculate", json={"kind": "led_resistor", "args": {"vs": 1, "vf": 2, "i_led": 0.01}}).status_code == 422


def test_components_and_bom():
    client = TestClient(app)
    assert any(c["id"] == "led-generic-red-5mm" for c in client.get("/components", params={"q": "led"}).json())
    assert all(c["datasheet_url"] is None for c in client.get("/components").json())  # never invented
    h = _auth(client, "carol@example.com")
    pid = client.post("/projects", json={"name": "d", "template": "voltage_divider"}, headers=h).json()["id"]
    rows = client.get(f"/projects/{pid}/bom", headers=h).json()
    assert {r["quantity"] for r in rows if r["category"] == "resistor"} == {2}  # R1,R2 same value grouped
    assert client.get(f"/projects/{pid}/bom", params={"format": "csv"}, headers=h).text.startswith("references,")


def test_ai_parse_fallback_and_llm_validation(monkeypatch):
    from app.services.ai import service as ai
    pr = ai.parse_request("Design a 9 V LED indicator")
    assert pr.template == "led" and pr.params == {"vs": 9.0} and pr.source == "deterministic"
    assert ai.parse_request("LED circuit").questions  # missing voltage -> follow-up question
    assert ai.parse_request("build a rocket").template is None
    monkeypatch.setenv("AI_BASE_URL", "http://x"); monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setattr(ai, "_complete", lambda p: '{"template":"led","params":{"vs":12}}')
    assert ai.parse_request("anything").source == "llm"
    monkeypatch.setattr(ai, "_complete", lambda p: '{"template":"evil_shell","params":{}}')  # untrusted output rejected
    assert ai.parse_request("a 5 V LED").source == "deterministic"
    monkeypatch.setattr(ai, "_complete", lambda p: "not json")
    assert ai.parse_request("a 5 V LED").template == "led"


def test_propose_then_approve_and_review():
    client = TestClient(app)
    h = _auth(client, "dave@example.com")
    pid = client.post("/projects", json={"name": "L", "template": "led"}, headers=h).json()["id"]
    pr = client.post(f"/projects/{pid}/ai/propose", json={"instruction": "Change the input voltage to 12 V"}, headers=h).json()
    assert pr["understood"] and any("R1" in x for x in pr["changes"])
    assert client.get(f"/projects/{pid}", headers=h).json()["circuit"]["version"] == 1  # not applied yet
    assert next(x for x in pr["circuit"]["components"] if x["ref"] == "R1")["value"] == 1000.0
    assert client.put(f"/projects/{pid}/circuit", json=pr["circuit"], headers=h).json()["version"] == 2
    assert not client.post(f"/projects/{pid}/ai/propose", json={"instruction": "make it faster"}, headers=h).json()["understood"]
    if spice.engine_version():
        client.post(f"/projects/{pid}/simulate", json={"analysis": "op"}, headers=h)
    rv = client.post(f"/projects/{pid}/review", headers=h).json()
    assert "not" in rv["summary"].lower() and rv["unverified_assumptions"] and rv["checks_not_executed"]
    assert client.get("/learning/led").json()["formula"].startswith("R =")


from app.integrations.kicad import schematic as kicad
needs_kicad = pytest.mark.skipif(kicad.available() is None, reason="kicad-cli not installed")


@needs_ngspice
def test_ac_rc_cutoff_is_minus_3db():
    c = generate("rc_lowpass", vin=5, r=1e3, c=1e-6)  # fc = 159.15 Hz
    res = spice.ac(c, "out", 1, 10e3, points=50)
    fc = calc.rc_cutoff(1e3, 1e-6).result
    m = min(zip(res["freq_hz"], res["magnitude_db"]), key=lambda x: abs(x[0] - fc))[1]
    assert m == pytest.approx(-3.01, abs=0.15)
    assert res["magnitude_db"][0] == pytest.approx(0, abs=0.05)


@needs_kicad
def test_kicad_export_roundtrip(tmp_path):
    from pathlib import Path
    for t in ("led", "voltage_divider", "rc_lowpass"):
        r = kicad.export_and_validate(generate(t), tmp_path / t)
        assert r["netlist_roundtrip_ok"], r["mismatches"]
        assert "design.pdf" in r["files"] and (tmp_path / t / "design.kicad_sch").stat().st_size > 0
    with pytest.raises(kicad.KicadError):
        kicad.build_schematic(Circuit(name="b", components=[Component(ref="R1", kind="R", value=1, pins={"1": "a"})]))


@needs_ngspice
def test_optimize_led_power_measured_and_constrained():
    client = TestClient(app); h = _auth(client, "erin@example.com")
    pid = client.post("/projects", json={"name": "L", "template": "led"}, headers=h).json()["id"]
    o = client.post(f"/projects/{pid}/optimize", json={"objective": "lower_power", "target_led_current_ma": 5, "min_led_current_ma": 2}, headers=h).json()
    assert o["supported"] and o["constraint_satisfied"] and o["original"]["method"].startswith("simulated")
    assert 35 < o["reduction_pct"] < 65  # ~10 mA -> ~5 mA
    bad = client.post(f"/projects/{pid}/optimize", json={"objective": "lower_power", "target_led_current_ma": 1, "min_led_current_ma": 2}, headers=h).json()
    assert not bad["supported"]
    d = client.post(f"/projects/{pid}/optimize", json={"objective": "lower_power", "target_led_current_ma": 3, "min_led_current_ma": 5}, headers=h).json()
    assert not d["supported"]


def test_versions_diff_and_download_whitelist():
    client = TestClient(app); h = _auth(client, "fay@example.com")
    pid = client.post("/projects", json={"name": "L", "template": "led"}, headers=h).json()["id"]
    pr = client.post(f"/projects/{pid}/ai/propose", json={"instruction": "change the input voltage to 9 V"}, headers=h).json()
    client.put(f"/projects/{pid}/circuit", json=pr["circuit"], headers=h)
    assert [v["number"] for v in client.get(f"/projects/{pid}/versions", headers=h).json()] == [1, 2]
    assert any("V1" in x for x in client.get(f"/projects/{pid}/versions/1/diff/2", headers=h).json()["changes"])
    assert client.get(f"/projects/{pid}/export/kicad/..%2F..%2Fetc%2Fpasswd", headers=h).status_code == 404
    assert client.get(f"/projects/{pid}/export/kicad/design.pdf", headers=h).status_code == 404  # not generated yet


@needs_kicad
def test_export_api_and_download(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "ART", tmp_path)
    client = TestClient(app); ha, hb = _auth(client, "gus@example.com"), _auth(client, "hal@example.com")
    pid = client.post("/projects", json={"name": "L", "template": "rc_lowpass"}, headers=ha).json()["id"]
    r = client.post(f"/projects/{pid}/export/kicad", headers=ha).json()
    assert r["netlist_roundtrip_ok"]
    assert client.get(f"/projects/{pid}/export/kicad/design.kicad_sch", headers=ha).text.startswith("(kicad_sch")
    assert client.get(f"/projects/{pid}/export/kicad/design.kicad_sch", headers=hb).status_code == 404


def test_rate_limit(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "RATE", 3); m._hits.clear()
    client = TestClient(app); h = _auth(client, "ivy@example.com")
    codes = [client.post("/ai/parse", json={"prompt": "5 V LED"}, headers=h).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3] == 429


from app.integrations.kicad import pcb as kpcb
needs_pcb = pytest.mark.skipif(kicad.available() is None or not kpcb.pcbnew_available(), reason="KiCad/pcbnew not available")


@needs_pcb
@pytest.mark.parametrize("tpl", ["led", "voltage_divider", "rc_lowpass"])
def test_pcb_generation_drc_and_exports(tmp_path, tpl):
    r = kpcb.generate_pcb(generate(tpl), tmp_path)
    assert r["drc"]["unconnected"] == 0 and r["drc"]["errors"] == 0, r["drc"]
    assert any(n.endswith(".drl") for n in r["gerber_files"]) and any(n.endswith(".gtl") for n in r["gerber_files"])
    import zipfile
    assert zipfile.ZipFile(tmp_path / "fabrication.zip").testzip() is None
    assert (tmp_path / "design.svg").read_text().lstrip().startswith("<?xml")
    assert r["manufacturing_readiness"]["ready_for_fabrication"] is False  # never claimed


@needs_pcb
def test_pcb_drc_detects_broken_routing(tmp_path):
    import re
    kpcb.generate_pcb(generate("led"), tmp_path)
    t = (tmp_path / "design.kicad_pcb").read_text()
    broken = re.sub(r"\(segment .*?\)\n", "", t, count=2, flags=re.S)  # delete two track segments
    assert broken != t
    (tmp_path / "broken.kicad_pcb").write_text(broken)
    import subprocess, sys
    code = ("import pcbnew,sys;b=pcbnew.LoadBoard(sys.argv[1]);pcbnew.WriteDRCReport(b,sys.argv[2],pcbnew.EDA_UNITS_MILLIMETRES,True)")
    subprocess.run([sys.executable, "-c", code, str(tmp_path / "broken.kicad_pcb"), str(tmp_path / "b.rpt")], check=True)
    assert kpcb._parse_drc((tmp_path / "b.rpt").read_text())["unconnected"] > 0


@needs_pcb
def test_pcb_api_and_isolation(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "ART", tmp_path); m._hits.clear()
    client = TestClient(app); ha, hb = _auth(client, "jo@example.com"), _auth(client, "kim@example.com")
    pid = client.post("/projects", json={"name": "P", "template": "led"}, headers=ha).json()["id"]
    r = client.post(f"/projects/{pid}/pcb/generate", headers=ha).json()
    assert r["drc"]["unconnected"] == 0 and r["files"].count("fabrication.zip") == 1
    assert client.get(f"/projects/{pid}/export/kicad/fabrication.zip", headers=ha).content[:2] == b"PK"
    assert client.get(f"/projects/{pid}/export/kicad/fabrication.zip", headers=hb).status_code == 404
    assert client.post(f"/projects/{pid}/pcb/generate", headers=hb).status_code == 404


def test_alembic_migration_creates_schema(tmp_path):
    import subprocess, sys, sqlite3
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path}/m.db", "CF_AUTO_CREATE": "0", "PYTHONPATH": "."}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env, capture_output=True)
    tables = {r[0] for r in sqlite3.connect(tmp_path / "m.db").execute("select name from sqlite_master where type='table'")}
    assert {"users", "tokens", "projects", "project_versions", "alembic_version"} <= tables


def _at(res, t):  # sample nearest time
    return min(zip(res["time"], res["voltage"]), key=lambda tv: abs(tv[0] - t))[1]


@needs_ngspice
def test_npn_switch_on_off_levels():
    res = spice.transient(generate("npn_switch"), "col", 1e-5, 5e-3)
    assert _at(res, 0.5e-3) > 3.0   # off: collector pulled up through R1 (LED not conducting)
    assert _at(res, 2.0e-3) < 0.5   # on: saturated, Vce(sat) small


@needs_ngspice
def test_mosfet_switch_on_off_levels():
    res = spice.transient(generate("mosfet_switch"), "drain", 1e-5, 5e-3)
    assert _at(res, 0.5e-3) == pytest.approx(12.0, abs=0.1) and _at(res, 2.0e-3) < 0.5


@needs_ngspice
def test_relay_flyback_diode_clamps_spike():
    with_d = spice.transient(generate("relay_driver"), "drain", 2e-6, 25e-3)
    without = spice.transient(generate("relay_driver", flyback=0.0), "drain", 2e-6, 25e-3)
    assert max(with_d["voltage"]) < 12 + 2.5          # clamped near Vcc + diode drop
    assert max(without["voltage"]) > 50               # unclamped inductive kick
    assert not any(x.kind == "D" for x in generate("relay_driver", flyback=0.0).components)


@needs_ngspice
def test_opamp_gain():
    res = spice.operating_point(generate("opamp_noninverting", vin=0.1, rf=9e3, rg=1e3))
    assert res["node_voltages"]["out"] == pytest.approx(1.0, rel=1e-3)


@needs_ngspice
def test_component_currents_replace_single_loop_assumption():
    res = spice.operating_point(generate("voltage_divider", vin=5, r1=10e3, r2=10e3))
    assert res["component_currents"]["R1"] == pytest.approx(0.25e-3, rel=1e-3)
    c = generate("led")  # LED with 10 ohm resistor: simulated currents drive the rating findings
    c.components[1].value = 10.0
    f = verify(c, spice.operating_point(c)["component_currents"])
    assert any(x.check == "ratings.led_current" for x in f) and any(x.check == "ratings.resistor_power" for x in f)


def test_new_rating_checks_and_unset_ratings():
    c = generate("npn_switch")
    f = verify(c, {"Q1": 0.5, "D1": 0.001, "R1": 0.0, "R2": 0.0})
    assert any(x.check == "ratings.bjt_ic" and x.severity == "error" for x in f)
    assert any(x.check == "ratings.transient_peaks" and not x.executed for x in f)
    c.components[4].rating = None
    f2 = verify(c, {"Q1": 0.5})
    assert any(x.check == "ratings.bjt_ic" and not x.executed for x in f2)  # unset rating reported, not guessed


def test_new_calculators():
    r = calc.bjt_base_resistor(5, 0.7, 0.010)
    assert r.result == 4300.0 and r.result <= (5 - 0.7) / 0.001   # rounded DOWN so base current is sufficient
    assert calc.regulator_dissipation(12, 5, 0.1, theta_ja=50).warnings and calc.regulator_dissipation(12, 5, 0.1).result == pytest.approx(0.7)
    assert calc.battery_runtime(2000, 100, 0.8).result == pytest.approx(16.0)
    assert calc.capacitor_energy(1e-3, 10).result == pytest.approx(0.05)
    assert calc.mosfet_switch_check(12, 120, 2.5, 2.0, 1.0).warnings  # weak gate drive flagged
    for bad in (lambda: calc.regulator_dissipation(3, 5, 0.1), lambda: calc.battery_runtime(1000, 0), lambda: calc.bjt_base_resistor(0.5, 0.7, 0.01)):
        with pytest.raises(ValueError): bad()


def test_all_templates_valid_and_unknown_params_rejected():
    from app.services.circuit_generation.templates import TEMPLATES
    for t in TEMPLATES:
        c = generate(t); assert c.components and not [f for f in verify(c) if f.severity == "error"], t
    with pytest.raises(TypeError): generate("led", nonsense=1)
    with pytest.raises(ValueError): generate("relay_driver", r_coil=-5)
    with pytest.raises(ValueError): Component(ref="R1", kind="R", value=1, pulse=[0] * 7)


@needs_kicad
@pytest.mark.parametrize("tpl", ["npn_switch", "mosfet_switch", "relay_driver", "opamp_noninverting"])
def test_kicad_roundtrip_new_parts(tmp_path, tpl):
    r = kicad.export_and_validate(generate(tpl), tmp_path)
    assert r["netlist_roundtrip_ok"], r["mismatches"]


@needs_pcb
@pytest.mark.parametrize("tpl", ["npn_switch", "mosfet_switch", "relay_driver"])
def test_pcb_new_parts_drc(tmp_path, tpl):
    r = kpcb.generate_pcb(generate(tpl), tmp_path)
    assert r["drc"]["unconnected"] == 0 and r["drc"]["errors"] == 0, r["drc"]


@needs_pcb
def test_pcb_rejects_ideal_opamp(tmp_path):
    with pytest.raises(kicad.KicadError, match="no footprint"):
        kpcb.generate_pcb(generate("opamp_noninverting"), tmp_path)


def test_new_templates_via_api_and_bom():
    client = TestClient(app); h = _auth(client, "lee@example.com")
    for t in ("relay_driver", "npn_switch"):
        pid = client.post("/projects", json={"name": t, "template": t}, headers=h).json()["id"]
        cats = {r["category"] for r in client.get(f"/projects/{pid}/bom", headers=h).json()}
        assert {"resistor", "source"} <= cats and ("mosfet" in cats or "transistor" in cats)
        assert client.get(f"/learning/{t}").status_code == 200
        assert client.post(f"/projects/{pid}/verify", headers=h).status_code == 200
    assert client.post("/calculate", json={"kind": "battery_runtime", "args": {"capacity_mah": 2000, "load_ma": 100}}).json()["result"] == pytest.approx(16.0)


def _poll(client, h, jid, tries=100):
    import time
    for _ in range(tries):
        j = client.get(f"/jobs/{jid}", headers=h).json()
        if j["status"] in ("done", "failed"): return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


@needs_ngspice
def test_background_jobs_lifecycle_and_failure():
    client = TestClient(app); h = _auth(client, "mo@example.com"); m._hits.clear() if (m := __import__("app.main", fromlist=["x"])) else None
    pid = client.post("/projects", json={"name": "J", "template": "voltage_divider"}, headers=h).json()["id"]
    r = client.post(f"/projects/{pid}/jobs", json={"kind": "simulate", "params": {"analysis": "op"}}, headers=h)
    assert r.status_code == 202
    j = _poll(client, h, r.json()["id"])
    assert j["status"] == "done" and j["result"]["node_voltages"]["out"] == pytest.approx(2.5)
    assert "op" in client.get(f"/projects/{pid}", headers=h).json()["results"]   # stored with the project version
    bad = _poll(client, h, client.post(f"/projects/{pid}/jobs", json={"kind": "simulate", "params": {"analysis": "tran", "node": "nope", "tstep": 1e-6, "tstop": 1e-3}}, headers=h).json()["id"])
    assert bad["status"] == "failed" and "Unknown node" in bad["error"] and bad["result"] is None
    other = _auth(client, "nia@example.com")
    assert client.get(f"/jobs/{r.json()['id']}", headers=other).status_code == 404


def test_collaboration_roles_and_audit():
    client = TestClient(app)
    owner, ed, vw, out = (_auth(client, f"{n}@example.com") for n in ("own1", "ed1", "vw1", "out1"))
    pid = client.post("/projects", json={"name": "S", "template": "led"}, headers=owner).json()["id"]
    assert client.post(f"/projects/{pid}/members", json={"email": "ed1@example.com", "role": "editor"}, headers=owner).status_code == 201
    assert client.post(f"/projects/{pid}/members", json={"email": "vw1@example.com", "role": "viewer"}, headers=owner).status_code == 201
    assert client.post(f"/projects/{pid}/members", json={"email": "vw1@example.com", "role": "editor"}, headers=ed).status_code == 403  # editors cannot share
    assert client.get(f"/projects/{pid}", headers=vw).status_code == 200
    assert client.post(f"/projects/{pid}/verify", headers=vw).status_code == 403   # viewer cannot write
    assert client.post(f"/projects/{pid}/verify", headers=ed).status_code == 200
    assert client.get(f"/projects/{pid}", headers=out).status_code == 404
    assert any(p["id"] == pid for p in client.get("/projects", headers=vw).json())
    c = client.get(f"/projects/{pid}", headers=ed).json()["circuit"]
    assert client.put(f"/projects/{pid}/circuit", json=c, headers=ed).status_code == 200
    assert client.put(f"/projects/{pid}/circuit", json=c, headers=vw).status_code == 403
    assert client.delete(f"/projects/{pid}", headers=ed).status_code == 403
    log = client.get(f"/projects/{pid}/audit", headers=owner).json()
    assert {"project.create", "member.add", "circuit.update"} <= {e["action"] for e in log} and any(e["by"] == "ed1@example.com" for e in log)
    client.delete(f"/projects/{pid}/members/ed1@example.com", headers=owner)
    assert client.get(f"/projects/{pid}", headers=ed).status_code == 404


def test_logout_password_change_and_token_expiry(monkeypatch):
    client = TestClient(app); h = _auth(client, "pw@example.com")
    assert client.get("/me", headers=h).json()["email"] == "pw@example.com"
    assert client.put("/me/password", json={"current_password": "bad-password", "new_password": "another-pass-1"}, headers=h).status_code == 403
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/me", headers=h).status_code == 401           # token revoked
    h2 = _auth(client, "pw@example.com")
    assert client.put("/me/password", json={"current_password": "correct-horse-1", "new_password": "another-pass-1"}, headers=h2).status_code == 204
    assert client.get("/me", headers=h2).status_code == 401           # all sessions revoked
    assert client.post("/auth/login", json={"email": "pw@example.com", "password": "another-pass-1"}).status_code == 200
    h3 = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "pw@example.com", "password": "another-pass-1"}).json()["access_token"]}
    monkeypatch.setenv("TOKEN_TTL_DAYS", "0")
    assert client.get("/me", headers=h3).status_code == 401           # expired


@needs_ngspice
def test_pmos_highside_levels_and_pnp_conducts():
    res = spice.transient(generate("pmos_highside"), "out", 1e-5, 5e-3)
    assert _at(res, 0.5e-3) < 0.1 and _at(res, 2e-3) == pytest.approx(12.0, abs=0.2)   # off -> 0 V, on -> ~Vcc
    pnp = Circuit(name="pnp", components=[
        Component(ref="V1", kind="V", value=5, pins={"p": "vcc", "n": "0"}),
        Component(ref="Q1", kind="QP", pins={"b": "base", "c": "col", "e": "vcc"}, rating=0.1),
        Component(ref="R1", kind="R", value=4300, pins={"1": "base", "2": "0"}),
        Component(ref="R2", kind="R", value=330, pins={"1": "col", "2": "0"})])
    op = spice.operating_point(pnp)
    assert op["component_currents"]["Q1"] != 0 and abs(op["component_currents"]["Q1"]) > 5e-3   # collector conducts ~10 mA scale


@needs_ngspice
def test_dc_and_parameter_sweeps_match_theory():
    c = generate("voltage_divider", vin=5, r1=10e3, r2=10e3)
    d = spice.dc_sweep(c, "V1", "out", 0, 10, 1)
    assert all(v == pytest.approx(x / 2, abs=1e-6) for x, v in zip(d["x"], d["voltage"]))
    p = spice.param_sweep(c, "R2", 1e3, 10e3, 4, "out")
    assert all(v == pytest.approx(5 * r / (10e3 + r), rel=1e-4) for r, v in zip(p["values"], p["voltage"]))
    for bad in (lambda: spice.dc_sweep(c, "R1", "out", 0, 1, 0.1), lambda: spice.dc_sweep(c, "V1", "out", 0, 10, -1),
                lambda: spice.param_sweep(c, "V9", 1, 2, 3, "out"), lambda: spice.param_sweep(c, "R2", 1, 2, 99, "out")):
        with pytest.raises(spice.SimulationError): bad()


@needs_ngspice
def test_sweep_api():
    client = TestClient(app); h = _auth(client, "sw@example.com")
    pid = client.post("/projects", json={"name": "d", "template": "voltage_divider"}, headers=h).json()["id"]
    r = client.post(f"/projects/{pid}/simulate", json={"analysis": "dc", "source": "V1", "node": "out", "start": 0, "stop": 4, "step": 1}, headers=h).json()
    assert r["voltage"][-1] == pytest.approx(2.0)
    s = client.post(f"/projects/{pid}/sweep", json={"ref": "R2", "node": "out", "start": 1e3, "stop": 1e4, "points": 3}, headers=h)
    assert s.status_code == 200 and len(s.json()["voltage"]) == 3
    assert client.post(f"/projects/{pid}/sweep", json={"ref": "R2", "node": "nope", "start": 1, "stop": 2, "points": 3}, headers=h).status_code == 422


def test_ai_free_form_edits_deterministic():
    from app.services.ai import service as ai
    relay = generate("relay_driver", flyback=0.0)
    p = ai.propose_change(relay, "please add a flyback diode")
    assert p.understood and p.circuit and any(c.kind == "D" and c.pins == {"a": "drain", "k": "vcc"} for c in p.circuit.components) and p.changes
    assert not any(c.kind == "D" for c in relay.components)                         # original untouched
    assert ai.propose_change(p.circuit, "add a flyback diode").circuit is None       # already present, no change proposed
    s = ai.propose_change(generate("led"), "set R1 to 4.7k")
    assert next(c for c in s.circuit.components if c.ref == "R1").value == pytest.approx(4700)
    assert ai.propose_change(generate("led"), "remove D1").circuit is not None
    assert "Unknown component" in ai.propose_change(generate("led"), "set R9 to 100").message
    assert not ai.propose_change(generate("led"), "make it prettier").understood


def test_ai_llm_operations_validated(monkeypatch):
    from app.services.ai import service as ai
    monkeypatch.setenv("AI_BASE_URL", "http://x"); monkeypatch.setenv("AI_API_KEY", "k")
    good = '{"operations":[{"op":"set_value","ref":"R1","value":1000}],"explanation":"raise R1"}'
    monkeypatch.setattr(ai, "_complete_ops", lambda c, i: good)
    p = ai.propose_change(generate("led"), "dim the LED")
    assert next(c for c in p.circuit.components if c.ref == "R1").value == 1000
    hostile = '{"operations":[{"op":"add","component":{"ref":"X1","kind":"RM","pins":{}}}]}'      # invalid kind -> rejected, falls back
    monkeypatch.setattr(ai, "_complete_ops", lambda c, i: hostile)
    assert not ai.propose_change(generate("led"), "dim the LED").understood
    monkeypatch.setattr(ai, "_complete_ops", lambda c, i: '{"operations":[{"op":"set_pin","ref":"R1","pin":"1","net":"bad net; rm -rf"}]}')
    assert not ai.propose_change(generate("led"), "do thing").understood
    monkeypatch.setattr(ai, "_complete_ops", lambda c, i: "garbage")
    assert ai.propose_change(generate("led"), "set R1 to 1k").circuit is not None                 # deterministic fallback still works


@needs_ngspice
def test_optimize_divider_target_measured():
    client = TestClient(app); h = _auth(client, "od@example.com")
    pid = client.post("/projects", json={"name": "d", "template": "voltage_divider", "params": {"vin": 5, "r1": 10e3, "r2": 2e3}}, headers=h).json()["id"]
    o = client.post(f"/projects/{pid}/optimize", json={"objective": "hit_target_voltage", "target_v": 3.3, "tolerance_pct": 1}, headers=h).json()
    assert o["supported"] and o["original"]["method"].startswith("simulated") and o["alternative"]["method"].startswith("simulated")
    assert o["chosen_r2_e24_ohm"] == pytest.approx(20e3)                                        # best E24 value for R1=10k, target 3.3 V
    assert o["alternative"]["vout"] == pytest.approx(5 * 20e3 / 30e3, rel=1e-4) and o["alternative"]["error_pct"] == pytest.approx(1.0101, abs=0.01)
    assert o["alternative"]["error_pct"] < o["original"]["error_pct"]
    assert o["constraint_satisfied"] is False and "misses" in o["action"]                        # 1.01% > 1% tolerance: honestly reported
    ok = client.post(f"/projects/{pid}/optimize", json={"objective": "hit_target_voltage", "target_v": 3.3, "tolerance_pct": 2}, headers=h).json()
    assert ok["constraint_satisfied"] is True and "PUT" in ok["action"]
    assert client.post(f"/projects/{pid}/optimize", json={"objective": "hit_target_voltage"}, headers=h).status_code == 422
    assert not client.post(f"/projects/{pid}/optimize", json={"objective": "hit_target_voltage", "target_v": 9}, headers=h).json()["supported"]


def test_notes_duplicate_export_import_roundtrip():
    client = TestClient(app); ha, hb = _auth(client, "pm1@example.com"), _auth(client, "pm2@example.com")
    pid = client.post("/projects", json={"name": "Orig", "template": "led"}, headers=ha).json()["id"]
    assert client.put(f"/projects/{pid}/notes", json={"notes": "check Vf"}, headers=ha).status_code == 204
    assert client.get(f"/projects/{pid}", headers=ha).json()["notes"] == "check Vf"
    assert client.put(f"/projects/{pid}/notes", json={"notes": "x"}, headers=hb).status_code == 404
    dup = client.post(f"/projects/{pid}/duplicate", headers=ha).json()
    assert dup["name"] == "Orig (copy)" and client.get(f"/projects/{dup['id']}", headers=ha).json()["notes"] == "check Vf"
    exp = client.get(f"/projects/{pid}/export", headers=ha).json()
    assert exp["format"] == "circuitforge-project"
    exp["circuit"]["simulation_status"] = "simulated"                               # a file cannot claim results
    imp = client.post("/projects/import", json=exp, headers=hb)
    assert imp.status_code == 201
    assert client.get(f"/projects/{imp.json()['id']}", headers=hb).json()["circuit"]["simulation_status"] == "not_run"
    bad = {**exp, "circuit": {**exp["circuit"], "components": [{"ref": "R1", "kind": "RM", "pins": {}}]}}
    assert client.post("/projects/import", json=bad, headers=hb).status_code == 422
    assert client.post("/projects/import", json={**exp, "format": "other"}, headers=hb).status_code == 422
    assert client.post(f"/projects/{pid}/duplicate", headers=hb).status_code == 404


@needs_kicad
@pytest.mark.parametrize("tpl", ["pmos_highside"])
def test_kicad_pmos_template_roundtrip(tmp_path, tpl):
    r = kicad.export_and_validate(generate(tpl), tmp_path)
    assert r["netlist_roundtrip_ok"], r["mismatches"]


@needs_kicad
def test_kicad_pnp_symbol_roundtrip(tmp_path):
    c = Circuit(name="pnp", components=[Component(ref="V1", kind="V", value=5, pins={"p": "vcc", "n": "0"}),
        Component(ref="Q1", kind="QP", pins={"b": "base", "c": "col", "e": "vcc"}), Component(ref="R1", kind="R", value=4300, pins={"1": "base", "2": "0"}),
        Component(ref="R2", kind="R", value=330, pins={"1": "col", "2": "0"})])
    assert kicad.export_and_validate(c, tmp_path)["netlist_roundtrip_ok"]


@needs_pcb
def test_pcb_pmos_template_drc(tmp_path):
    r = kpcb.generate_pcb(generate("pmos_highside"), tmp_path)
    assert r["drc"]["unconnected"] == 0 and r["drc"]["errors"] == 0, r["drc"]


@needs_ngspice
def test_ldo_regulation_dropout_and_thermal_findings():
    for vin, expect in ((9, set()), (12, {"regulator.dissipation"}), (5.5, {"regulator.dropout"})):
        c = generate("ldo_supply", vin=vin, vout=5, i_load=0.1)
        r = spice.operating_point(c)
        assert r["component_currents"]["REG1"] == pytest.approx(0.1 if vin >= 7 else 0.07, rel=0.02)   # measured regulator output current
        assert r["node_voltages"]["vout"] == pytest.approx(5.0 if vin >= 7 else vin - 2.0, abs=0.01)
        got = {x.check for x in verify(c, r["component_currents"], r["node_voltages"]) if x.check.startswith("regulator")}
        assert got == expect, (vin, got)
    f = verify(generate("ldo_supply"), {"REG1": 2.0}, {"vin": 9.0, "vout": 5.0})
    assert any(x.check == "ratings.regulator_iout" and x.severity == "error" for x in f)       # 2 A > assumed 1 A rating
    assert any("junction temperature NOT computed" in x.evidence for x in verify(generate("ldo_supply", vin=12), {"REG1": 0.1}, {"vin": 12.0, "vout": 5.0}))


def test_ldo_template_validation_and_ai_edit():
    from app.services.ai import service as ai
    with pytest.raises(ValueError): generate("ldo_supply", vin=3, vout=5)           # needs Vin > Vout
    with pytest.raises(ValueError): generate("ldo_supply", i_load=-1)
    p = ai.propose_change(generate("ldo_supply"), "set REG1 to 3.3")
    assert next(c for c in p.circuit.components if c.ref == "REG1").value == pytest.approx(3.3)


@needs_ngspice
def test_ldo_via_api_findings_use_simulated_data():
    client = TestClient(app); h = _auth(client, "ldo@example.com")
    pid = client.post("/projects", json={"name": "L", "template": "ldo_supply", "params": {"vin": 12.0}}, headers=h).json()["id"]
    assert not any(f["check"].startswith("regulator.") for f in client.post(f"/projects/{pid}/verify", headers=h).json()["findings"])  # nothing simulated yet
    client.post(f"/projects/{pid}/simulate", json={"analysis": "op"}, headers=h)
    checks = {f["check"] for f in client.post(f"/projects/{pid}/verify", headers=h).json()["findings"]}
    assert "regulator.dissipation" in checks
    assert any(r["category"] == "regulator" for r in client.get(f"/projects/{pid}/bom", headers=h).json())


@needs_kicad
def test_kicad_ldo_roundtrip(tmp_path):
    r = kicad.export_and_validate(generate("ldo_supply"), tmp_path)
    assert r["netlist_roundtrip_ok"], r["mismatches"]


@needs_pcb
def test_pcb_ldo_drc(tmp_path):
    r = kpcb.generate_pcb(generate("ldo_supply"), tmp_path)
    assert r["drc"]["unconnected"] == 0 and r["drc"]["errors"] == 0, r["drc"]


@needs_ngspice
def test_opamp_rails_clamp_and_saturation_finding():
    lin = generate("opamp_noninverting", vin=0.3, rf=9e3, rg=1e3, vcc=5.0)        # gain 10 -> 3 V, inside the rails
    r = spice.operating_point(lin)
    assert r["node_voltages"]["out"] == pytest.approx(3.0, rel=2e-3)
    assert not any(x.check == "opamp.saturated" for x in verify(lin, r["component_currents"], r["node_voltages"]))
    sat = generate("opamp_noninverting", vin=0.6, rf=9e3, rg=1e3, vcc=5.0)        # ideal answer 6 V, rail is 5 V
    r = spice.operating_point(sat)
    assert r["node_voltages"]["out"] == pytest.approx(5.0, abs=0.01)
    f = [x for x in verify(sat, r["component_currents"], r["node_voltages"]) if x.check == "opamp.saturated"]
    assert f and f[0].severity == "warning" and "rail=5 V" in f[0].evidence
    ideal = spice.operating_point(generate("opamp_noninverting", vin=0.6))        # no rails: still ideal
    assert ideal["node_voltages"]["out"] == pytest.approx(6.0, rel=1e-3)
    with pytest.raises(ValueError): generate("opamp_noninverting", vcc=-1)


@needs_kicad
def test_kicad_opamp_with_rails_roundtrip(tmp_path):
    assert kicad.export_and_validate(generate("opamp_noninverting", vcc=5.0), tmp_path)["netlist_roundtrip_ok"]


def test_manual_components_and_part_assignment_bom():
    client = TestClient(app); ha, hb = _auth(client, "pa1@example.com"), _auth(client, "pa2@example.com")
    r = client.post("/components/manual", json={"category": "Resistor", "description": "my 330R", "manufacturer": "Acme", "part_number": "AR-330", "specs": {"power_w": 0.25}, "datasheet_url": "https://example.com/ds.pdf"}, headers=ha)
    assert r.status_code == 201
    mine = client.get("/components/mine", headers=ha).json()
    assert mine[0]["part_number"] == "AR-330" and "not verified" in mine[0]["source"] and client.get("/components/mine", headers=hb).json() == []   # private to the owner
    assert client.post("/components/manual", json={"category": "x", "description": "d", "datasheet_url": "javascript:alert(1)"}, headers=ha).status_code == 422
    pid = client.post("/projects", json={"name": "B", "template": "voltage_divider"}, headers=ha).json()["id"]
    before = client.get(f"/projects/{pid}/bom", headers=ha).json()
    assert all(row["mpn"] == "" and "Generic part" in row["notes"] for row in before)   # nothing invented
    body = {"ref": "R1", "manufacturer": "Acme", "mpn": "AR-10K", "datasheet_url": "https://example.com/ar.pdf", "price": "0.02 USD", "availability": "in stock (per my quote)", "notes": "from my quote"}
    assert client.put(f"/projects/{pid}/bom/parts", json=body, headers=ha).status_code == 200
    rows = client.get(f"/projects/{pid}/bom", headers=ha).json()
    r1 = next(x for x in rows if "R1" in x["references"])
    assert r1["mpn"] == "AR-10K" and r1["quantity"] == 1 and "User-entered" in r1["notes"]
    assert next(x for x in rows if "R2" in x["references"])["mpn"] == ""       # R2 has the same value but a different part -> separate rows
    assert client.put(f"/projects/{pid}/bom/parts", json={**body, "ref": "R9"}, headers=ha).status_code == 422          # not in the design
    assert client.put(f"/projects/{pid}/bom/parts", json={**body, "price": "free; DROP TABLE"}, headers=ha).status_code == 422
    assert client.put(f"/projects/{pid}/bom/parts", json=body, headers=hb).status_code == 404
    assert "AR-10K" in client.get(f"/projects/{pid}/bom", params={"format": "csv"}, headers=ha).text
    assert client.delete(f"/projects/{pid}/bom/parts/R1", headers=ha).status_code == 204
    assert all(x["mpn"] == "" for x in client.get(f"/projects/{pid}/bom", headers=ha).json())


def test_distributor_adapter_requires_credentials_and_parses_defensively(monkeypatch):
    import httpx
    from app.services.component_database import distributors as dist
    client = TestClient(app); h = _auth(client, "dist@example.com"); monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    assert client.get("/components/lookup", params={"mpn": "X"}, headers=h).status_code == 503           # no credentials -> honest failure
    ok = {"SearchResults": {"NumberOfResult": 1, "Parts": [{"Manufacturer": "Acme", "ManufacturerPartNumber": "AR-10K", "Description": "res", "DataSheetUrl": "https://e.com/d.pdf",
          "Availability": "100 In Stock", "PriceBreaks": [{"Quantity": 1, "Price": "$0.10", "Currency": "USD"}]}, {"ManufacturerPartNumber": "BARE"}]}, "Errors": []}
    seen = {}
    def handler(req: httpx.Request):
        seen["url"] = str(req.url); seen["body"] = req.content.decode(); return httpx.Response(200, json=ok)
    res = dist.MouserAdapter("k", httpx.MockTransport(handler)).search_part_number("AR-10K")
    assert res[0]["mpn"] == "AR-10K" and res[0]["price_breaks"][0]["currency"] == "USD" and res[0]["retrieved"] and "unverified" in res[0]["source"]
    assert res[1]["datasheet_url"] is None and res[1]["price_breaks"] == []        # missing fields stay empty, never invented
    assert "apiKey=k" in seen["url"] and "AR-10K" in seen["body"]
    for transport in (httpx.MockTransport(lambda r: httpx.Response(500)), httpx.MockTransport(lambda r: httpx.Response(200, json={"Errors": [{"Message": "bad key"}]})),
                      httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))):
        with pytest.raises(dist.DistributorUnavailable): dist.MouserAdapter("k", transport).search_part_number("X")
    monkeypatch.setenv("MOUSER_API_KEY", "k"); monkeypatch.setattr(dist.MouserAdapter, "search_part_number", lambda self, mpn: [{"mpn": mpn}])
    assert client.get("/components/lookup", params={"mpn": "Q1"}, headers=h).json() == {"results": [{"mpn": "Q1"}]}


def test_datasheet_upload_security_and_lifecycle(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "ART", tmp_path); m._hits.clear()
    client = TestClient(app); owner, viewer, out = (_auth(client, f"{n}@example.com") for n in ("dso", "dsv", "dsx"))
    pid = client.post("/projects", json={"name": "D", "template": "led"}, headers=owner).json()["id"]
    client.post(f"/projects/{pid}/members", json={"email": "dsv@example.com", "role": "viewer"}, headers=owner)
    pdf = b"%PDF-1.4\n%fake but valid header\n" + b"x" * 100
    up = lambda h, data=pdf, name="ds.pdf": client.post(f"/projects/{pid}/datasheets", files={"file": (name, data, "application/pdf")}, headers=h)
    r = up(owner, name="../../etc/passwd")                                         # traversal attempt in the filename
    assert r.status_code == 201 and "/" not in r.json()["name"] and ".." not in r.json()["name"] and r.json()["name"].endswith(".pdf")
    stored = list((tmp_path / "datasheets" / str(pid)).iterdir()); assert len(stored) == 1 and stored[0].suffix == ".pdf" and len(stored[0].stem) == 32   # server-generated name
    assert up(owner, data=b"MZ\x90\x00 not a pdf", name="evil.pdf").status_code == 415
    monkeypatch.setattr(m, "MAX_DATASHEET", 50); assert up(owner).status_code == 413; monkeypatch.setattr(m, "MAX_DATASHEET", 5 * 1024 * 1024)
    assert up(viewer).status_code == 403 and up(out).status_code == 404
    did = r.json()["id"]
    dl = client.get(f"/projects/{pid}/datasheets/{did}", headers=viewer)
    assert dl.status_code == 200 and dl.content == pdf and dl.headers["x-content-type-options"] == "nosniff" and dl.headers["content-type"] == "application/pdf"
    assert client.get(f"/projects/{pid}/datasheets/{did}", headers=out).status_code == 404
    assert [d["id"] for d in client.get(f"/projects/{pid}/datasheets", headers=viewer).json()] == [did]
    assert client.delete(f"/projects/{pid}/datasheets/{did}", headers=viewer).status_code == 403
    assert client.delete(f"/projects/{pid}/datasheets/{did}", headers=owner).status_code == 204 and not list((tmp_path / "datasheets" / str(pid)).iterdir())
    for _ in range(20): assert up(owner).status_code == 201
    assert up(owner).status_code == 422                                            # per-project cap


def test_ai_daily_quota(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "AI_DAILY_LIMIT", 2); m._ai_used.clear(); m._hits.clear()
    client = TestClient(app); h = _auth(client, "quota@example.com")
    codes = [client.post("/ai/parse", json={"prompt": "5 V LED"}, headers=h).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert client.post("/calculate", json={"kind": "power", "args": {"v": 1, "i": 1}}).status_code == 200      # non-AI endpoints unaffected


@needs_pcb
def test_pcb_layout_geometry_and_pitch_validation(tmp_path):
    c = generate("npn_switch")
    r = kpcb.generate_pcb(c, tmp_path, pitch=16.0)
    lay = r["layout"]; assert lay["pitch_mm"] == 16.0 and {p["ref"] for p in lay["parts"]} == {x.ref for x in c.components}
    b = lay["board"]
    assert all(p["w"] > 0 and p["h"] > 0 and b["x0"] <= p["x"] <= b["x1"] and b["y0"] <= p["y"] <= b["y1"] for p in lay["parts"])   # every part lies on the board
    import json
    assert json.loads((tmp_path / "layout.json").read_text())["pitch_mm"] == 16.0 and "layout.json" in r["files"]
    for bad in (7.9, 40.1):
        with pytest.raises(kicad.KicadError, match="pitch_mm"): kpcb.generate_pcb(c, tmp_path / "x", pitch=bad)


@needs_pcb
def test_pcb_area_optimizer_is_measured_and_excludes_failing_layouts(tmp_path):
    r = kpcb.optimize_pcb_area(generate("led"), tmp_path)
    assert r["constraint_satisfied"] and r["alternative"]["drc_clean"] and r["alternative"]["area_mm2"] <= r["original"]["area_mm2"]
    assert r["reduction_pct"] == pytest.approx(100 * (r["original"]["area_mm2"] - r["alternative"]["area_mm2"]) / r["original"]["area_mm2"], abs=0.1)
    clean = [t["area_mm2"] for t in r["tried"] if t["drc_clean"]]
    assert r["alternative"]["area_mm2"] == min(clean)                                    # best among DRC-clean candidates only
    failing = [t for t in r["tried"] if not t["drc_clean"]]
    assert failing and all(t["area_mm2"] < r["alternative"]["area_mm2"] for t in failing)   # smaller layouts exist but were rejected by KiCad DRC
    assert all(t["drc_errors"] > 0 or t["drc_unconnected"] > 0 for t in failing)


@needs_pcb
def test_pcb_area_optimize_and_pitched_generate_via_api(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "ART", tmp_path); m._hits.clear()
    client = TestClient(app); h = _auth(client, "area@example.com")
    pid = client.post("/projects", json={"name": "A", "template": "led"}, headers=h).json()["id"]
    o = client.post(f"/projects/{pid}/optimize", json={"objective": "smaller_pcb_area"}, headers=h).json()
    assert o["constraint_satisfied"] and "pitch_mm=" in o["action"]
    g = client.post(f"/projects/{pid}/pcb/generate", params={"pitch_mm": o["alternative"]["pitch_mm"]}, headers=h).json()
    assert g["drc"]["errors"] == 0 and g["drc"]["unconnected"] == 0 and g["board_mm"] == o["alternative"]["board_mm"]    # applying it reproduces the measured result
    assert client.post(f"/projects/{pid}/pcb/generate", params={"pitch_mm": 3}, headers=h).status_code == 422
    assert client.get(f"/projects/{pid}/export/kicad/layout.json", headers=h).json()["board"]["x1"] > 0
