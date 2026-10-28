# Architecture
- **frontend/**: React + TypeScript (Vite). Talks to the API under `/api` (dev proxy / nginx).
- **backend/app**: FastAPI. `schemas/circuit.py` is the single circuit model; rendering, verification, simulation, BOM and KiCad export all derive from it.
- **services/**: calculations, templates, verification, ngspice runner, optimization, AI layer, BOM, learning content.
- **integrations/kicad/**: schematic generation (KiCad symbol libs), PCB generation (`pcbnew` in a subprocess), exports via `kicad-cli`.
- **Storage**: SQLAlchemy (SQLite default, PostgreSQL via DATABASE_URL), Alembic migrations, generated files under ARTIFACT_DIR/<project_id>/v<version>/ (server-built paths only).
Honesty rules enforced in code: `simulation_status` is set only by a successful run; unexecuted checks are reported as `executed: false`; exports never claim fabrication readiness.
