# sap_bridge

Read-only HTTP service over the **SAP2000 OAPI**. The single integration point with
SAP2000: consumers (the MCP today; Rhino plugins and scripts tomorrow) talk HTTP and
nobody embeds the SAP DLL.

Strictly **agnostic**: exposes facts (coordinates, connectivity, property names) and
interprets no structural domain. Runs on `localhost:8766`.

> The full HTTP contract is documented here in **Commit 6**. This stub covers the
> scaffold (Commit 1).

## Run

```powershell
# from the repo root, with SAP2000 already open on a model (attach-only):
$env:PYTHONPATH = "i:\Mi unidad\geometry_cognition"
python -m uvicorn Sap_experiment.sap_bridge.main:app --host 127.0.0.1 --port 8766
```

Requires Python 3.11+ on Windows, `pythonnet`, and SAP2000 installed (the bridge
auto-resolves `SAP2000v1.dll`; override with the `SAP_OAPI_DLL` env var).

## Endpoints (so far)

- `GET /health` — bridge liveness + whether a SAP session is attached + resolved DLL
  path. Does not attach; safe to poll.
- `GET /v1/units` — active SAP unit system as a fact (`present_units`,
  `present_units_code`). Never converts.

Coming in their own commits: `GET /v1/joints`, `GET /v1/frames`, `GET /v1/sections`.

## Errors

Every failure returns the same envelope with a stable `code`:

```json
{ "error": true, "code": "sap_not_running", "message": "..." }
```

`409` for client-fixable preconditions (no SAP open / no model); `502` when the bridge
reached SAP and something on that side failed. Codes are enumerated in
[error_codes.py](error_codes.py).

## Session model

Attach-only this phase: the bridge connects to a SAP2000 the user already has open
(COM `GetObject`) and never launches it or opens/saves models. The session manager
([sap_session.py](sap_session.py)) keeps a `mode` seam so a future "start new
instance" mode can be added without changing callers.
