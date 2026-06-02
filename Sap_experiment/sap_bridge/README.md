# sap_bridge — HTTP contract

HTTP service over the **SAP2000 OAPI**. The **single integration point** with SAP2000:
consumers (the MCP today; Rhino plugins and scripts tomorrow, per Objetivo 2) talk HTTP
and nobody embeds the SAP DLL. Mostly read; running analysis and savepoints mutate (and
the write-side grows from here — see Architecture below).

Strictly **agnostic** (see [`../docs/agnostic_principle.md`](../docs/agnostic_principle.md)):
exposes facts — coordinates, connectivity, property names — and interprets no structural
domain. **Treat this document as a public API contract; future consumers depend on it.**

- Base URL: `http://127.0.0.1:8766`
- Versioned under `/v1`
- All payloads JSON; all responses `application/json`

## Architecture

- Read-side: facts only, agnostic (the bulk of the endpoints below).
- Write-side: governed by [`../docs/write_side_design.md`](../docs/write_side_design.md)
  — **the architectural authority every write primitive must follow** (namespace prefix,
  dry-run, savepoints, stop-on-first-failure, confirm). Consumer-side patterns in
  [`../docs/client_patterns.md`](../docs/client_patterns.md).

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

## Primitives at a glance

| Method + Endpoint | MCP tool | Fact returned |
|---|---|---|
| `GET /v1/units` | (internal) | active SAP unit system |
| `GET /v1/model/settings` | `get_model_settings` | active DOFs, lock state, present + database units |
| **`POST`** `/v1/model/settings/active_dof` | `set_active_dof` | **write**: set active DOFs (global setting) |
| **`POST`** `/v1/model/settings/present_units` | `set_present_units` | **write**: set present units (global setting) |
| `GET /v1/joints` | `get_joints` | points: name, coords, 6-DOF restraints |
| `GET /v1/frames` | `get_frames` | frames: name, i/j connectivity, section |
| `GET /v1/sections` | `get_sections` | section catalogue: name + type |
| `GET /v1/sections/{name}/properties` | `get_section_properties` | dimensions + universal section props |
| `GET /v1/materials` | `get_materials` | material catalogue: type + mechanical facts |
| **`POST`** `/v1/materials` | `create_material` | **write**: create a material (prefixed) |
| **`POST`** `/v1/materials/{name}/properties/isotropic` | `set_material_properties_isotropic` | **write**: set isotropic properties |
| `GET /v1/load_patterns` | `get_load_patterns` | load patterns: type + self-weight multiplier |
| `GET /v1/load_cases` | `get_load_cases` | analysis cases: name + type |
| `GET /v1/load_cases/{name}/details` | `get_load_case_details` | one case's composition (LinearStatic) |
| `GET /v1/combinations` | `get_combinations` | combos: type + consolidated component items |
| `GET /v1/frames/{name}/loads/distributed` | `get_distributed_loads_on_frame` | distributed loads on one frame |
| `GET /v1/joints/{name}/loads/point` | `get_point_loads_on_joint` | point loads on one joint |
| `GET /v1/analysis/status` | `get_analysis_status` | per-case run status + model lock |
| **`POST`** `/v1/analysis/run` | `run_analysis` | **mutates**: runs analysis, returns status |
| `GET /v1/joints/{name}/displacements/{case}` | `get_joint_displacements` | 6-DOF joint displacement (LinearStatic) |
| `GET /v1/joints/{name}/reactions/{case}` | `get_joint_reactions` | 6-DOF joint reaction (LinearStatic) |
| `GET /v1/frames/{name}/forces/{case}` | `get_frame_forces` | frame internal forces per station |
| `GET /v1/savepoints` | `list_savepoints` | list savepoints (filesystem scan) |
| **`POST`** `/v1/savepoints` | `create_savepoint` | **write (fs)**: save model state to a savepoint |
| **`POST`** `/v1/savepoints/{name}/restore` | `restore_savepoint` | **write (destructive)**: restore a savepoint |

Read (`GET`) except `POST /v1/analysis/run` (runs analysis) and the savepoint writes
(`POST /v1/savepoints*`, the undo infrastructure — see Write-side conventions below).
Frame stresses,
envelope/combination results, non-LinearStatic results, point loads on frames,
temperature/displacement loads, and model writes are future phases (see
[`../docs/brechas.md`](../docs/brechas.md)).

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

### `GET /v1/model/settings`

Model configuration facts: the structural envelope (active DOFs + lock state) and units
(present + database). No parameters — the model is one.

```json
{
  "settings": {
    "active_dof": [true, false, true, false, true, false],
    "model_is_locked": false,
    "present_units": { "present_units": "kgf_m_C", "present_units_code": 8 },
    "database_units": { "present_units": "kgf_m_C", "present_units_code": 8 }
  }
}
```

- `active_dof`: the raw 6-tuple from `GetActiveDOF`, order `[U1, U2, U3, R1, R2, R3]` —
  the same index convention as joint restraints/reactions/displacements. The bridge does
  **not** name a pattern: `[true,false,true,false,true,false]` is reported as-is, never
  labelled "Plane Frame XZ" or "2D" (the client recognises that from the vector).
- `model_is_locked`: `true` if analysis results are current (editing would invalidate
  them).
- `present_units`: the active "view". `database_units`: the system the model stores data
  in internally. They may differ; both are reported. Each is a [`units` object](#the-units-object)
  (so the inner field is named `present_units` for both — the existing units shape, reused).
- Other settings categories (solver options, mass source, custom coordinate systems,
  project info, damping) are **not** here — each will be its own primitive when a use case
  appears. This is a conscious gap, not an omission.

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

### `GET /v1/load_patterns`

The load pattern **catalogue**: each pattern's name, raw SAP type and self-weight
multiplier. Names are model-supplied labels relayed verbatim — `PESO PROPIO` stays as-is,
never translated to `Dead`; the bridge never assumes which patterns a model should have.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 6,
  "load_patterns": [
    { "name": "PESO PROPIO", "load_type": "Dead", "self_weight_multiplier": 1.0 },
    { "name": "VIENTO", "load_type": "Wind", "self_weight_multiplier": 0.0 }
  ]
}
```

- `load_type`: raw `eLoadPatternType` member name (`Dead`, `Live`, `Wind`, `Snow`, …).
- `self_weight_multiplier`: factor SAP applies to self weight (typically 1.0 for a
  self-weight pattern, 0.0 otherwise).

### `GET /v1/load_cases`

The analysis load case **catalogue**: name + raw SAP case type. The case's internal
definition (which patterns/factors it applies) is a later primitive.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 7,
  "load_cases": [
    { "name": "PESO PROPIO", "case_type": "LinearStatic" },
    { "name": "MODAL", "case_type": "Modal" }
  ]
}
```

- `case_type`: raw `eLoadCaseType` member name (`LinearStatic`, `Modal`, …).

> Implementation note: `cLoadCases.GetNameList` has a type-filtered overload; the bridge
> uses the unfiltered 2-arg form so every type is listed (filtering to `LinearStatic`
> returned 6, the unfiltered call 7 — the extra being `MODAL`). See §9.

### `GET /v1/combinations`

The load combination **catalogue**: each combo's name, type and consolidated component
items. SAP returns combination contents as parallel arrays; the bridge recomposes them so
the client never juggles indices. It interprets nothing — `ENVOLVENTE` is reported with
combo_type `Envelope`, never a domain label.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "count": 8,
  "combinations": [
    {
      "name": "D+L", "combo_type": "Linear Additive", "combo_type_code": 0,
      "items": [
        { "case_name": "D", "case_type": "LoadCombo", "scale_factor": 1.0 },
        { "case_name": "VIVA", "case_type": "LoadCase", "scale_factor": 1.0 }
      ]
    }
  ]
}
```

- `combo_type_code`: raw integer from `GetTypeOAPI` (this assembly exposes no enum).
- `combo_type`: SAP's documented name for that code (`0`=Linear Additive, `1`=Envelope,
  `2`=Absolute Additive, `3`=SRSS, `4`=Range Additive); `"Unknown"` for an unmapped code,
  reported never guessed.
- `items[].case_type`: raw `eCNameType` — `"LoadCase"` (references a name from
  `/v1/load_cases`) or `"LoadCombo"` (references another combination; combo-of-combo is
  real). `scale_factor` is the component's factor.

> A combo's `LoadCase` items reference existing load cases and `LoadCombo` items existing
> combos — cross-checked on TEST_01: zero dangling references. A broken reference would be
> a fact of the **model**, reported, not patched by the bridge.

### `GET /v1/load_cases/{name}/details`

Composition of **one** load case (by exact name, as in `/v1/load_cases`). Closes the
asymmetry `/v1/combinations` left — combos already exposed their composition, cases did
not. For a `LinearStatic` case, `loads` lists the applied patterns + scale factors. For
any other type, `unsupported_case_type` is `true` and `loads` is empty: the case and its
type are reported, internals deferred — **information, not an error**.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "case": {
    "case_name": "PESO PROPIO", "case_type": "LinearStatic",
    "unsupported_case_type": false,
    "loads": [ { "load_type": "Load", "load_pattern": "PESO PROPIO", "scale_factor": 1.0 } ]
  }
}
```

- `load_pattern` references a name from `/v1/load_patterns`. An unknown case name →
  `oapi_call_failed` (502). A `Modal` case → `unsupported_case_type: true`, `loads: []`.

### `GET /v1/frames/{name}/loads/distributed`

Distributed loads on **one** frame (by exact name, as in `/v1/frames`), across all load
patterns. **Empty `loads` means the frame has none — not an error.**

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "frame": "4133", "count": 1,
  "loads": [
    {
      "load_pattern": "MUERTA", "load_type": "Force",
      "direction": "Gravity", "direction_code": 10, "coord_system": "GLOBAL",
      "rel_dist_start": 0.0, "rel_dist_end": 1.0,
      "value_start": 19.4, "value_end": 19.4
    }
  ]
}
```

- `load_type`: raw type — `Force` or `Displacement` (SAP `MyType` 1/2).
- `direction_code`: raw integer SAP direction (this assembly exposes no direction enum).
  `direction`: documented name for the code — `1-3`=Local 1/2/3, `4-6`=Global X/Y/Z,
  `7-9`=Projected, `10`=Gravity, `11`=Projected Gravity; `"Unknown"` if out of range.
  Relayed raw — `Gravity` stays `Gravity`, never `"down"`.
- `coord_system`: raw CSys name (`GLOBAL`, `Local`, a custom name).
- `rel_dist_start`/`end`: 0..1 relative positions; `value_start`/`end`: present units.
- `load_pattern` references `/v1/load_patterns`. **Anti-pattern #4: a pattern's name does
  not imply its function** — on TEST_01 `VIENTO` carries `Gravity`-direction loads. The
  bridge reports the fact, not "wind".

### `GET /v1/joints/{name}/loads/point`

Point loads (force + moment) on **one** joint (by exact name, as in `/v1/joints`), across
all load patterns. **Empty `loads` means the joint has none — not an error.**

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "joint": "27", "count": 1,
  "loads": [
    {
      "load_pattern": "VIENTO", "coord_system": "GLOBAL",
      "f1": 0.0, "f2": 0.0, "f3": -500.0, "m1": 0.0, "m2": 0.0, "m3": 0.0
    }
  ]
}
```

- `f1/f2/f3` (force) and `m1/m2/m3` (moment) are the six components in `coord_system`,
  present units. `load_pattern` references `/v1/load_patterns`.

> On TEST_01 no joint carries a point load (0/112), so this endpoint was validated on the
> empty path (returns `count: 0`, `loads: []`); the example above is illustrative of the
> non-empty shape. Non-empty coverage waits for a model with joint loads (see §11).

---

## Mutating operations

The bridge is read-only **except** for running analysis. Running analysis changes the
model's **computation** state — it produces results and may lock the model — but does
**not** modify the model definition (creating/assigning/deleting objects is Fase 1g, gated
behind a design doc). The HTTP method signals intent: `GET` is safe-read, `POST` mutates.

### `GET /v1/analysis/status`

Current analysis status per load case, plus whether the model is locked. Read-safe.

```json
{
  "model_is_locked": true,
  "count": 7,
  "status": [
    { "case_name": "DEAD", "status": "Finished", "status_code": 4, "has_run": true },
    { "case_name": "VIVA", "status": "Not Run", "status_code": 1, "has_run": false }
  ]
}
```

- `status_code`: raw int from `GetCaseStatus` — `1`=Not Run, `2`=Could Not Start,
  `3`=Not Finished, `4`=Finished; `status` is its name (`"Unknown"` if unmapped).
- `has_run`: `true` only when Finished (results exist). A case that could not start /
  did not finish is reported as the fact it is — **the bridge never judges the model**.
- `model_is_locked`: a locked model holds results that editing the model would
  invalidate. A fact, not a judgement.

### `POST /v1/analysis/run`  *(mutating)*

Runs the analysis. **BLOCKING** — `RunAnalysis` is synchronous; large models can take a
while (`runtime_seconds` reports the wall-clock cost). **No confirmation required**: it is
not destructive and re-running is idempotent (SAP skips cases with current results).

Request body (optional):

```json
{ "cases_to_run": ["DEAD", "MUERTA"] }
```

- Omit the body (or send `{}`) to run **all pending cases** (default `RunAnalysis`).
- `cases_to_run`: run only these by name. Each name is validated against existing cases
  **before touching SAP** (an unknown name → `oapi_unexpected_shape`, refused up front).
  The bridge flags the subset, runs, then **restores the original run-case flags** — the
  request leaves no side effect on which cases are flagged. (OAPI has no "run these cases"
  call; it is flag-then-run. See §13.)

Response:

```json
{
  "ran_count": 7,
  "cases_run": ["DEAD", "MODAL", "PESO PROPIO", "MUERTA", "VIVA", "VIENTO", "NIEVE"],
  "runtime_seconds": 5.797,
  "model_is_locked": true,
  "status": [ { "case_name": "DEAD", "status": "Finished", "status_code": 4, "has_run": true } ]
}
```

- `cases_run`/`ran_count`: the cases that hold results after the run (status Finished).
- `runtime_seconds`: wall-clock time of the blocking call (a re-run of an up-to-date
  model is ~0.0s — SAP skipped everything; idempotent).
- A non-zero `RunAnalysis` return → `oapi_call_failed` carrying the code: a **model-side**
  failure (singular matrix, missing supports, …). The bridge relays it; it does not
  interpret why the model did not solve.

> Validated on TEST_01: a full run took ~5.8s, all 7 cases reached Finished, the model
> locked. A subset run with flag-restore and an unknown-case rejection were both exercised.

---

## Analysis results (read-only, post-analysis)

These read the results the analysis produced. They depend on computation state: a case
must have been run. Two new error codes gate that: `case_not_run` (the case exists but has
no results — `409`, call `run_analysis` first) and `unsupported_case_type` (the case is
not LinearStatic — Modal/spectrum/… not exposed this phase, `502`). An unknown case name
is `oapi_call_failed`. Values are in present units; the bridge never converts.

### `GET /v1/joints/{name}/displacements/{case_name}`

The 6-DOF displacement of one joint in one LinearStatic case (global system).

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "displacements": {
    "joint": "9", "case_name": "MUERTA", "coord_system": "Global", "step_number": 0.0,
    "u1": 0.0, "u2": 0.0, "u3": 0.0, "r1": 0.0, "r2": 0.000133, "r3": 0.0
  }
}
```

- `u1/u2/u3` translations, `r1/r2/r3` rotations. A restrained DOF reads ~0 (reported as
  SAP gives it, never nullified). `step_number` is 0 for LinearStatic.

### `GET /v1/joints/{name}/reactions/{case_name}`

The 6-DOF reaction (force + moment) of one joint in one LinearStatic case.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "reactions": {
    "joint": "9", "case_name": "MUERTA", "coord_system": "Global", "step_number": 0.0,
    "f1": 72.02, "f2": 0.0, "f3": 7.40, "m1": 0.0, "m2": 0.0, "m3": 0.0
  }
}
```

- `f1/f2/f3` forces, `m1/m2/m3` moments. An unrestrained DOF reads ~0; a fully free joint
  reads the zero vector — correct information, not an error.

> The reactions at the restrained joints balance the applied loads. Cross-checked on
> TEST_01: the 30 restrained joints' `f3` for MUERTA sum to ~1290.86 (vertical), `f1`/`f2`
> ~0 — equilibrating the 78 MUERTA gravity loads. The bridge does **not** compute this; it
> is a fact-composition the client can do over these endpoints.

### `GET /v1/frames/{name}/forces/{case_name}`  ·  `?station=0..1`

Internal forces at the stations SAP computed along one frame, in one LinearStatic case.

```json
{
  "units": { "present_units": "kgf_m_C", "present_units_code": 8 },
  "frame": "4133", "case_name": "MUERTA", "count": 2,
  "stations": [
    { "relative_distance": 0.0, "absolute_distance": 0.0,
      "p": -0.767, "v2": -2.398, "v3": 0.0, "t": 0.0, "m2": 0.0, "m3": -0.155 },
    { "relative_distance": 1.0, "absolute_distance": 0.4916,
      "p": -0.767, "v2": 7.138, "v3": 0.0, "t": 0.0, "m2": 0.0, "m3": -1.320 }
  ]
}
```

- One item per station: `relative_distance` (0..1, derived as `absolute_distance` /
  frame length), `absolute_distance` (from the i-end), then `p` (axial), `v2`/`v3`
  (shears), `t` (torsion), `m2`/`m3` (moments).
- `?station=0..1` returns just the nearest station; omit for all. A large moment is a
  number, not "overstress" (anti-pattern #4).

---

## Write-side conventions

The write-side is governed by [`../docs/write_side_design.md`](../docs/write_side_design.md)
(the authority) with consumer patterns in
[`../docs/client_patterns.md`](../docs/client_patterns.md). In short: a configurable
namespace prefix on created objects, an optional `dry_run` flag (preview without applying),
explicit savepoints for undo, stop-on-first-failure for batches, and a `confirm` flag
mandatory for destructive operations. New error codes: `confirm_required`,
`prefix_required`, `name_already_exists`, `object_not_found`, `dry_run_validation_failed`,
`savepoint_not_found`, `savepoint_already_exists` (all `409`, client-fixable).

The first write primitives (Fase 1g.1) are savepoints — undo infrastructure that writes
the **filesystem**, not the model in memory. The first primitive that mutates the model in
memory is `set_active_dof` (Fase 1g.2).

**Audit log**: every write records one JSON-Lines entry to
`sap_bridge/logs/writes_<YYYY-MM-DD>.jsonl` (timestamp, operation, parameters incl.
dry_run/confirm, result `applied`/`preview_only`/`error_<code>`, result_details,
elapsed_ms). Errors are logged too. Read-only primitives (e.g. `list_savepoints`) are not
logged. The logs are git-ignored runtime artifacts.

**Namespace** (design doc §1, [`namespace.py`](namespace.py)): every object a `create_<noun>`
makes must carry the bridge prefix — `BRIDGE_NAMESPACE_PREFIX` env var, default `AI_`. The
prefix marks what the bridge owns:
- create without the prefix → `prefix_required`.
- create with a name already taken → `name_already_exists` (SAP would otherwise overwrite
  silently — verified, §23).
- modify/`set_properties` on a **bridge-owned** object (prefixed) → no confirm.
- modify a **pre-existing** (non-prefixed) object → `confirm` required (§5.1).
- creating a new prefixed object needs no confirm (non-destructive).

### `POST /v1/model/settings/active_dof`  *(write — global setting)*

Set the model's active DOFs. The write counterpart of the `active_dof` field from
`GET /v1/model/settings`.

```json
{ "active_dof": [true, true, true, true, true, true], "dry_run": false, "confirm": true }
```

- `active_dof`: exactly **6 booleans** `[U1, U2, U3, R1, R2, R3]` (a malformed list →
  `422` from the contract or `oapi_unexpected_shape`). The bridge validates **shape only**;
  it does not judge whether a pattern is structurally sensible (SAP accepts even all-false,
  anti-pattern #4).
- `confirm` is **mandatory** (a global setting, design doc §5.3): without it →
  `confirm_required`. `dry_run: true` previews the change with a per-DOF diff, without
  applying.

Dry-run → `would_apply` (`current_active_dof`, `new_active_dof`, `changes`); real run →
`applied` (`previous_active_dof`, `current_active_dof`, `changes`). `model_is_locked` is
echoed as a fact.

```json
{
  "dry_run": false,
  "applied": {
    "previous_active_dof": [true, false, true, false, true, false],
    "current_active_dof":  [true, true, true, true, true, true],
    "changes": ["U2: false → true", "R1: false → true", "R3: false → true"]
  },
  "model_is_locked": false
}
```

- On a **locked** model SAP rejects the change (`SetActiveDOF` returns non-zero) →
  `oapi_call_failed`. The bridge does **not** auto-unlock; unlock in SAP if intended.

> Validated end-to-end on TEST_01 via the client pattern: `create_savepoint` → dry-run
> preview → reject without confirm → apply with confirm → restore. The audit log captured
> all steps including the errors.

### `POST /v1/model/settings/present_units`  *(write — global setting)*

Set the model's present (display) units **by name**. The write counterpart of the
`present_units` field from `GET /v1/model/settings`.

```json
{ "units": "N_m_C", "dry_run": false, "confirm": true }
```

- `units`: an eUnits member name (`kgf_m_C`, `N_m_C`, `lb_ft_F`, …). An unknown name →
  `unknown_unit_system` (the message lists the supported names). The bridge resolves
  name → enum off the live `eUnits`, so the accepted set is exactly the read-side's.
- `confirm` is **mandatory** (global setting): without it → `confirm_required`.
  `dry_run: true` previews with a `change_summary` without applying. Idempotent — setting
  the current value again is a valid no-op (`change_summary: "kgf_m_C → kgf_m_C"`).

Dry-run → `would_apply` (`current_units`, `new_units`, `change_summary`); real run →
`applied` (`previous_units`, `current_units`, `change_summary`). Each units value uses the
existing [`units` object](#the-units-object) shape.

> **Display preference, not a conversion.** Changing present units reformats how the
> read-side reports values; the bridge converts nothing itself. Verified on TEST_01:
> switching to `N_m_C`, distances are unchanged (joint 9 `x` = -13.7687 in both — metres is
> metres) while forces rescale (frame 4133 distributed load 19.4 → 190.249, a factor of
> 9.80665 = kgf→N). `database_units` is **not** touched (that would convert stored data —
> out of scope). `model_is_locked` is unaffected.

### `POST /v1/materials`  *(write — new object)*

Create a material in the bridge namespace.

```json
{ "name": "AI_MGP10_Custom", "material_type": "NoDesign", "dry_run": false }
```

- `name` must carry the bridge prefix → else `prefix_required`. An existing name →
  `name_already_exists`.
- `material_type` is an `eMatType` member name — `Steel`, `Concrete`, `NoDesign`,
  `Aluminum`, `ColdFormed`, `Rebar`, `Tendon`, `Masonry`. **There is no `Wood`** in SAP26
  (use `NoDesign` for timber); an unknown name → `unknown_material_type` (lists the valid
  ones). No confirm (creating a new prefixed object). `dry_run` previews.
- Dry-run → `would_apply` (name, material_type, type_code); real run → `applied`.

> A freshly created material has **default** properties (not null) — set its properties next
> with the endpoint below. The two are separate atomic primitives; the client composes them
> (client_patterns.md Pattern 6).

### `POST /v1/materials/{name}/properties/isotropic`  *(write)*

Set a material's isotropic mechanical properties.

```json
{ "E": 1020000000, "poisson_ratio": 0.4, "thermal_coef": 0.0000117, "dry_run": false, "confirm": false }
```

- The material must exist → else `object_not_found`.
- `confirm` is required **only** for a non-bridge (pre-existing) material like `MGP10`
  (§5.1); a bridge-owned `AI_` material needs none.
- `E`, `poisson_ratio`, `thermal_coef` are in the model's **present units** — the client
  must know what those are (the bridge converts nothing). SAP derives the shear modulus
  `G = E / (2(1+nu))`; it is reported, not an input.
- Dry-run → `would_apply` (`current_properties`, `new_properties`, `changes`); real run →
  `applied` (`previous_properties`, `current_properties`, `changes`).

> Validated on TEST_01: created `AI_MGP10_Custom` (NoDesign), set its isotropic properties
> without confirm (bridge-owned); modifying `MGP10` without confirm → `confirm_required`,
> with confirm → applied; a savepoint reverted both the new material and the `MGP10` change.

### `GET /v1/savepoints`

List the savepoints for the current model. A pure filesystem scan (works even with SAP
busy). Empty list (not an error) if none.

```json
{
  "model_name": "TEST_01", "count": 1,
  "savepoints": [
    { "name": "baseline_01",
      "path": "…/test_models/TEST_01__sp_baseline_01.sdb",
      "created_at": "2026-06-02T19:49:57.482000+00:00", "size_bytes": 56380 }
  ]
}
```

### `POST /v1/savepoints`  *(write — filesystem)*

Save the current model state to `<model_dir>/<model_name>__sp_<name>.sdb`.

```json
{ "name": "baseline_01", "dry_run": false }
```

- Refuses with `savepoint_already_exists` if that name's file exists (no silent
  overwrite; use another name — delete is not implemented this phase).
- `dry_run: true` → returns `would_apply` (target path + estimated size) and confirms the
  directory is writable, without writing. Real run → `applied` with the created file's
  facts.
- Internally: `cFile.Save` repoints the in-memory model (it behaves as "Save As"), so the
  bridge saves to the savepoint and then reopens the original — the session keeps pointing
  at the user's model.

### `POST /v1/savepoints/{name}/restore`  *(write — destructive)*

Restore a savepoint, **replacing the loaded model** with it (and discarding unsaved
changes).

```json
{ "confirm": true, "dry_run": false }
```

- `confirm` is **mandatory**: without it → `confirm_required`. `dry_run: true` →
  `would_replace_with` (the savepoint that would load), without replacing.
- Missing savepoint → `savepoint_not_found`.
- The SAP handle stays valid after the reopen (no re-attach). **Note**: after a restore the
  session is loaded on the savepoint file, not the original — to return to the original
  model's workflow, reopen it. (See brechas §19.)

> Validated end-to-end on TEST_01: a full undo cycle (savepoint → change `active_dof` →
> restore) returned the model to its original state; confirm/dry-run/duplicate/not-found
> paths all exercised.

---

## Session model

Attach-only this phase: the bridge connects (COM `GetObject`) to a SAP2000 the user
already has open, and never launches it or opens/saves models. The session manager
([`sap_session.py`](sap_session.py)) keeps a `mode` seam so a future "start new instance"
mode can be added without changing this contract. OAPI calls are serialized by a
process-wide lock (COM is single-threaded).

## What this contract does NOT yet cover

Honest scope (see [`../docs/brechas.md`](../docs/brechas.md)): no pagination/filters
(all rows in one payload — fine at 112/180, revisit before large models), and no model
**writes** (creating/assigning/deleting objects — Fase 1g, gated behind a design doc).
Running analysis (Phase 1d) and results (Phase 1e: joint displacements/reactions, frame
forces — LinearStatic) are covered. **Not yet**: frame stresses (1e.2), envelope/
combination results (1e.3), non-LinearStatic results (modal/spectrum — 1f). Load
definitions (1c) and applied loads (1c.2) are covered; not yet point loads on frames,
temperature/displacement/area loads, or non-LinearStatic case composition (1c.3). Section
dimensions (1b) cover `Rectangular`; other shapes return `oapi_unexpected_shape` until
their extractor is added. These remaining gaps are future phases and should extend this
contract **additively**.
