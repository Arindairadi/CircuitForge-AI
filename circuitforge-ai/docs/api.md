# API (OpenAPI at /docs)
Auth: POST /auth/register, /auth/login, /auth/logout; GET /me; PUT /me/password.
Projects: POST/GET /projects, GET/DELETE /projects/{id}, PUT /projects/{id}/circuit, GET /versions, /versions/{a}/diff/{b}, /audit; members: POST/GET /members, DELETE /members/{email}.
Engineering: POST /calculate; /projects/{id}/verify, /simulate (op|tran|ac), /review, /optimize, /ai/propose; POST /ai/parse; GET /components, /templates, /learning/{template}.
Outputs: GET /projects/{id}/bom?format=csv; POST /export/kicad, /pcb/generate; GET /export/kicad/{file}.
Jobs: POST /projects/{id}/jobs (simulate|pcb) -> 202; GET /jobs/{id}. GET /health reports ngspice and kicad-cli versions.
Errors: {"detail": ...}; 401 auth, 403 role, 404 not found/no access, 422 invalid input or tool failure, 429 rate limit, 503 tool missing.

Added: POST /projects/{id}/sweep; /simulate analysis=dc (source,node,start,stop,step); PUT /projects/{id}/notes; POST /projects/{id}/duplicate; GET /projects/{id}/export; POST /projects/import; /optimize objective=hit_target_voltage (target_v, tolerance_pct); /ai/propose accepts free-form instructions (validated operations).

Part kinds accepted by the circuit schema: V, R, C, L, LED, D, Q, QP, M, MP, OA, REG; template `ldo_supply`.

Parts/data: POST /components/manual; GET /components/mine; GET /components/lookup?mpn= (503 without MOUSER_API_KEY); PUT /projects/{id}/bom/parts; DELETE /projects/{id}/bom/parts/{ref}.
Datasheets: POST/GET /projects/{id}/datasheets; GET/DELETE /projects/{id}/datasheets/{did}.
PCB: POST /projects/{id}/pcb/generate?pitch_mm=8..40; GET /projects/{id}/export/kicad/layout.json; /optimize objective=smaller_pcb_area.
