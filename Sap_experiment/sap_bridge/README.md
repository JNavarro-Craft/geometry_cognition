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

## Primitives at a glance

| Method + Endpoint | MCP tool | Fact returned |
|---|---|---|
| `GET /v1/units` | (internal) | active SAP unit system |
| `GET /v1/joints` | `get_joints` | points: name, coords, 6-DOF restraints |
| `GET /v1/frames` | `get_frames` | frames: name, i/j connectivity, section |
| `GET /v1/sections` | `get_sections` | section catalogue: name + type |
| `GET /v1/sections/{name}/properties` | `get_section_properties` | dimensions + universal section props |
| `GET /v1/materials` | `get_materials` | material catalogue: type + mechanical facts |
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

All read (`GET`) except the one mutating op (`POST /v1/analysis/run`). Frame stresses,
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
