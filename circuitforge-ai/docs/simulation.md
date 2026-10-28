# Simulation
ngspice batch mode (tested v42). Analyses: op (with per-component currents), tran, ac (source AC 1 V). Each run uses a temp dir, 10 s CPU / 1 GB rlimits and a wall-clock timeout; ngspice errors become 422 responses. Results are stored with the project version. Values come from generic ideal/approximate models, not measurements; the op-amp is ideal (no rails/bandwidth).

Also: DC sweep of a voltage source (<= 2000 points, ngspice `dc`) and parameter sweep (re-runs the operating point for 2-50 values of an R/C/L/V; each point is a real ngspice run).
