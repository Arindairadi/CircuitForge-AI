# CircuitForge AI (v1.0, partial)

A web EDA platform: describe a circuit, get a structured model, verification, real ngspice simulation, KiCad schematic/PCB files, BOM, review and optimization.
**Not every item in the original specification is complete or testable in the build environment.** Statuses only claim what was actually run; read `docs/limitations.md`.

## Run
```
sudo apt-get install ngspice kicad kicad-symbols kicad-footprints   # tested: ngspice 42, KiCad 7.0.11
cd backend && pip install -r requirements.txt && alembic upgrade head
PYTHONPATH=. uvicorn app.main:app --reload          # API docs at http://localhost:8000/docs
cd frontend && npm install && npm run dev            # http://localhost:5173 (proxies /api -> :8000)
```
Tests: `cd backend && PYTHONPATH=. python -m pytest -q` · `cd frontend && npm test` · `./scripts/integration.sh` (real UI-to-backend run). Env vars: `.env.example`. Docker: `docker compose up --build`.

## Verified in this build
- Backend: **72 tests passed on SQLite and again on PostgreSQL 16** (all 4 Alembic migrations applied on both). Frontend: **23 unit tests passed**, type-check + production build OK, 0 known production-dependency vulnerabilities.
- **Frontend-to-backend integration test passed** (`scripts/integration.sh`): the real React app (jsdom) against a real server: register, create, simulate (real ngspice value shown), verify, DC sweep, edit + new version, re-simulate, audit log.
- Earlier manual end-to-end over HTTP: AI proposal -> approval -> new version, KiCad export, background PCB job, BOM/zip downloads, export/import.

## Features (all "basic" unless noted; see limits below)
Circuit model (12 part kinds, 9 templates) · calculators · verification with per-part ratings from simulated currents, regulator dropout/dissipation, op-amp saturation · ngspice op/transient/AC/DC sweep/parameter sweep · KiCad 7 schematic + PDF with netlist round-trip check · KiCad PCB via pcbnew with KiCad DRC, Gerber/drill/position/SVG, zip, layout JSON · approximate 3D board view · AI layer (OpenAI-compatible + deterministic fallback; edits as validated operations applied only after approval; daily quota) · design review · optimization (LED power, divider target voltage, PCB area measured with KiCad DRC) · versions/diff · notes/duplicate/export/import · BOM with user-entered part assignments, user library, distributor adapter interface · PDF datasheet upload (untrusted-file handling) · accounts, expiring tokens, sharing roles, audit log, background jobs, rate limits · graphical schematic with wiring · learning center, settings.

## Could not be done / verified here (and why)
- **Docker images were not built or run** (no Docker daemon); compose/Dockerfile were only statically checked.
- **KiCad ERC**: needs KiCad 8; only 7.0.11 is installable here, so ERC is reported "not executed" (our own checks still run).
- **Live supplier data and a real AI provider**: need credentials. The Mouser-style adapter (unverified against the live API) and the AI layer are tested with mocked HTTP only; without keys they fail honestly.
- **Real-browser E2E**: no browser binary is available; the integration test uses jsdom with real HTTP instead. The 3D view needs WebGL and was not rendered here (geometry and fallback are tested).
- **LICENSE**: not chosen; that is your decision.
- The GitHub CI workflow has not been run.
