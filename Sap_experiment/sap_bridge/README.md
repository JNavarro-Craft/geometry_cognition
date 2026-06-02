# sap_bridge — HTTP contract

Read-only HTTP service over the **SAP2000 OAPI**. The **single integration point** with
SAP2000: consumers (the MCP today; Rhino plugins and scripts tomorrow, per Objetivo 2)
talk HTTP and nobody embeds the SAP DLL.

Strictly **agnostic** (see [`../docs/agnostic_principle.md`](../docs/agnostic_principle.md)):
exposes facts — coordinates, connectivity, property names — and interprets no structural
domain. **Treat this document as a public API contract; future consumers depend on it.**

- Base URL: `http://127.0.0.1:8766`
- Versioned under `/v1`
- All payloads JSON; all responses `application/json`

---

## Run

```powershell
# SAP2000 must already be open on a model (attach-only — the bridge never launches it):
$env:PYTHONPATH = "i:\Mi unidad\geometry_cognition"
python -m uvicorn Sap_experiment.sap_bridge.main:app --host 127.0.0.1 --port 8766
```

Requires Python 3.11+ on Windows, `pythonnet`, and SAP2000 installed. The bridge
auto-resolves `SAP2000v1.dll` (latest `SAP2000 NN` install); override with the
`SAP_OAPI_DLL` env var, or pin a version with `SAP_VERSION`.

---

## Contract conventions (stable)

These hold across **every** endpoint and are meant to stay stable:

1. **Facts, never judgements.** Fields report coordinates, connectivity, property
   names, enum values. No `is_*` / `verify_*` / `check_*` and no domain words.
2. **Units are exposed, never converted.** Every list response embeds a `units` object
   (the active SAP unit system). The bridge does not convert; the client converts
   knowing what it holds on each side.
3. **Uniform error envelope.** Every failure returns the same shape with a stable
   machine-readable `code`. Branch on `code`, not on prose.
4. **Counts are explicit.** List responses include a `count`.

### Error envelope

```json
{ "error": true, "code": "sap_not_running", "message": "no running SAP2000 instance found to attach to" }
```

| HTTP | When | Codes |
|---|---|---|
| `409` | Client-fixable precondition | `session_not_attached`, `sap_not_running`, `sap_process_died`, `no_model_open` |
| `502` | The bridge reached SAP and something there failed | `oapi_call_failed`, `oapi_unexpected_shape`, `pythonnet_unavailable`, `assembly_not_found` |

Codes are enumerated in [`error_codes.py`](error_codes.py). `oapi_call_failed` carries the
numeric OAPI status in the message; `oapi_unexpected_shape` means an OAPI call succeeded
but returned data the bridge would not silently patch (the silent-bug class we hunt).

### The `units` object

```json
{ "present_units": "kgf_m_C", "present_units_code": 8 }
```

`present_units` is the SAP `eUnits` member name; `present_units_code` its integer value.
Match on either; the bridge does not interpret the system.

---

## Endpoints

### `GET /health`

Bridge liveness + whether a SAP session is currently attached. **Does not attach**; safe
to poll.

```json
{ "status": "ok", "sap_attached": false, "oapi_dll": "C:\\Program Files\\Computers and Structures\\SAP2000 26\\SAP2000v1.dll" }
```

`sap_attached` reflects an *existing* session only — it is `false` until a `/v1/*` call
triggers the (lazy) attach. `oapi_dll` is the resolved assembly path, or `null` if not
found.

### `GET /v1/units`

The active SAP2000 unit system, as a fact. Returns the [`units` object](#the-units-object)
directly. Triggers an attach if none exists.

### `GET /v1/joints`

Every point object: name, global Cartesian coordinates (in the present units) and the raw
6-DOF restraint flags. **No support classification** (pinned/fixed/roller is domain).

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 112,
  "joints": [
    {
      "name": "1",
      "x": -10.7064840452, "y": 4.7036260798, "z": 2.1545346903,
      "coord_system": "Global",
      "restraints": [false, false, true, false, false, false]
    }
  ]
}
```

- `restraints`: `[U1, U2, U3, R1, R2, R3]`, `true` = restrained. Raw 6-tuple; the bridge
  does not name the pattern.
- `coord_system`: currently always `"Global"` (field reserved for future systems).

### `GET /v1/frames`

Every frame (line) object: name, the two end point names (connectivity) and the assigned
section property. **No role classification** (chord/strut/diagonal is domain).

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 180,
  "frames": [
    { "name": "4060", "point_i": "1891", "point_j": "1892", "section": "MGP10_33x73", "auto_select": "" }
  ]
}
```

- `point_i` / `point_j`: end point **names** — they match `name` in `/v1/joints`, so a
  client joins on them to resolve coordinates.
- `section`: assigned frame section property name, raw (a model-supplied label).
- `auto_select`: SAP auto-select list name, `""` if none.

### `GET /v1/sections`

The frame section property **catalogue** defined in the model: name + SAP type. Lists
what is *defined* (cross-reference `/v1/frames` `section` for what is *used*). Names are
model-supplied labels relayed verbatim; the bridge does not interpret them or resolve
dimensions.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 6,
  "sections": [
    { "name": "MGP10_33x73", "prop_type": "Rectangular" }
  ]
}
```

- `prop_type`: raw `eFramePropType` member name (e.g. `Rectangular`, `I`, `Box`).

> Implementation note: `cPropFrame.GetNameList` filters by type, so the bridge unions
> over all `eFramePropType` values and cross-checks the total against `PropFrame.Count()`,
> raising `oapi_unexpected_shape` on a mismatch rather than returning a partial catalogue.
> See [`../docs/brechas.md`](../docs/brechas.md).

---

## Session model

Attach-only this phase: the bridge connects (COM `GetObject`) to a SAP2000 the user
already has open, and never launches it or opens/saves models. The session manager
([`sap_session.py`](sap_session.py)) keeps a `mode` seam so a future "start new instance"
mode can be added without changing this contract. OAPI calls are serialized by a
process-wide lock (COM is single-threaded).

## What this contract does NOT yet cover

Honest scope (see [`../docs/brechas.md`](../docs/brechas.md)): no pagination/filters
(all rows in one payload — fine at 112/180, revisit before large models), no write
endpoints, no loads/analysis/results, no section dimensions. These are future phases and
should extend this contract **additively**.
