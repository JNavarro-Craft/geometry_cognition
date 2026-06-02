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

### `GET /v1/sections/{name}/properties`

Dimensions + universal section properties of **one** frame section, by its exact `name`
(as returned by `/v1/sections`). Dimension keys are SAP's own parameter names; the
bridge does **not** normalize geometry across shapes (that would be interpretation).
Values are in the present units.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "section": {
    "name": "MGP10_33x73",
    "prop_type": "Rectangular",
    "material": "MGP10",
    "dimensions": { "depth": 0.073, "width": 0.033 },
    "properties": {
      "area": 0.002409, "as2": 0.0020075, "as3": 0.0020075,
      "torsion": 6.2629e-07, "i22": 2.1862e-07, "i33": 1.0698e-06,
      "s22": 1.3250e-05, "s33": 2.9310e-05, "z22": 1.9874e-05, "z33": 4.3964e-05,
      "r22": 0.0095263, "r33": 0.0210733
    }
  }
}
```

- `dimensions`: shape-specific geometry. For `Rectangular`: `depth` (SAP `T3`) and
  `width` (`T2`). Other shapes carry their own keys (diameter, flange/web…). The key set
  varies by `prop_type` — the bridge does not flatten it.
- `properties`: the universal section properties (`area`, shear areas `as2/as3`,
  `torsion` constant J, inertias `i22/i33`, section moduli `s22/s33`, plastic moduli
  `z22/z33`, radii of gyration `r22/r33`) from `GetSectProps` — available for any shape.
- `material`: the referenced material property name (join with `/v1/materials`).
- **Unsupported shape** (not implemented this phase) → `oapi_unexpected_shape` carrying
  the received type. An **unknown name** → `oapi_call_failed` (the message hints to
  cross-check `/v1/sections`). Both are `502`.

> Verified against MGP10_33x73: `area = 0.002409 = 0.073 × 0.033`, cross-checked manually.
> This endpoint resolves **one** section; to get every section's geometry, list with
> `/v1/sections` and loop client-side (no "all dimensions at once" by design).

### `GET /v1/materials`

The material property **catalogue**: each material's name, raw SAP type and basic
mechanical facts when SAP provides them. No interpretation — a name like `MGP10` is
reported with whatever SAP type it carries (`NoDesign`), never relabelled `timber`.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 5,
  "materials": [
    {
      "name": "MGP10", "mat_type": "NoDesign",
      "e": 1000000000.0, "nu": 0.3, "thermal_coeff": 1.17e-05,
      "shear_modulus": 384615384.6, "weight_per_volume": 480.0, "mass_per_volume": 48.95
    },
    {
      "name": "A615Gr60", "mat_type": "Rebar",
      "e": null, "nu": null, "thermal_coeff": null, "shear_modulus": null,
      "weight_per_volume": 7849.05, "mass_per_volume": 800.38
    }
  ]
}
```

- `mat_type`: raw `eMatType` member name (`Steel`, `Concrete`, `NoDesign`, `Rebar`,
  `Tendon`, `Aluminum`, `ColdFormed`, `Masonry`).
- `e`, `nu`, `thermal_coeff`, `shear_modulus`: from `GetMPIsotropic`, in present units.
  **Null when not applicable** — these only exist for isotropic materials; `Rebar`/
  `Tendon` come back null here, reported honestly, never faked.
- `weight_per_volume`, `mass_per_volume`: from `GetWeightAndMass`, present units.

> Implementation note: the `eMatType`/`eFramePropType` out-params need a real enum member
> as pythonnet placeholder (an int is rejected). Material type comes from `GetMaterial`,
> not `GetTypeOAPI` (two out-params). See [`../docs/brechas.md`](../docs/brechas.md) §5–8.

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
endpoints, no loads/analysis/results. Section dimensions are covered now (Phase 1b) for
`Rectangular`; other shapes return `oapi_unexpected_shape` until their extractor is added
(additive). These remaining gaps are future phases and should extend this contract
**additively**.
