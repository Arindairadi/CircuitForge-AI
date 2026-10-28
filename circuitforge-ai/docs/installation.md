# Installation
```
sudo apt-get install ngspice kicad kicad-symbols kicad-footprints   # KiCad 7.x tested
cd backend && pip install -r requirements.txt
alembic upgrade head            # or CF_AUTO_CREATE=1 for throwaway dev DBs
PYTHONPATH=. uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev
```
Tests: `cd backend && PYTHONPATH=. python -m pytest -q` (KiCad/ngspice tests skip if the tools are missing).
PCB generation needs a Python interpreter that can `import pcbnew`; set PCBNEW_PYTHON if the server runs in a venv.
