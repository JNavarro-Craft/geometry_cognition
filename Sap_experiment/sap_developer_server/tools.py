"""MCP tool logic: relay facts from the SAP bridge. No structural interpretation.

Each tool calls the bridge over HTTP and returns its JSON essentially verbatim,
adding only an honest error envelope on transport failure. The agnostic test
(brief, Principle 1) holds: these return joints/frames/sections — facts that exist
in any solver — never is_*/verify_*/check_* judgements.
"""
from __future__ import annotations

from typing import Any

from .bridge_backend import (
    assign_section_to_frames_bridge,
    assign_sections_to_frames_bridge,
    bridge_settings,
    create_material_bridge,
    create_rectangular_section_bridge,
    create_savepoint_bridge,
    get_analysis_status_bridge,
    get_combinations_bridge,
    get_model_settings_bridge,
    list_savepoints_bridge,
    modify_rectangular_section_bridge,
    new_blank_model_bridge,
    open_model_bridge,
    reset_workspace_bridge,
    restore_savepoint_bridge,
    save_workspace_as_bridge,
    set_model_locked_bridge,
    set_active_dof_bridge,
    set_material_properties_isotropic_bridge,
    set_present_units_bridge,
    get_distributed_loads_on_frame_bridge,
    get_frame_forces_bridge,
    get_frames_bridge,
    get_joint_displacements_bridge,
    get_joint_reactions_bridge,
    get_joints_bridge,
    get_load_case_details_bridge,
    get_load_cases_bridge,
    get_load_patterns_bridge,
    get_materials_bridge,
    get_point_loads_on_joint_bridge,
    get_section_properties_bridge,
    get_sections_bridge,
    run_analysis_bridge,
)


def _bridge_error(exc: Exception) -> dict[str, Any]:
    """Uniform error envelope for the LLM when the bridge is unreachable or errored.
    The bridge's own {code, message} is embedded in the RuntimeError string."""
    return {
        "error": "bridge_unavailable",
        "message": str(exc),
        "hint": "Is the SAP bridge running on its port and is SAP2000 open with a model?",
    }


def get_model_settings() -> dict[str, Any]:
    """The open SAP model's configuration facts: ``active_dof`` (6 flags
    [U1,U2,U3,R1,R2,R3], True = active — same index convention as joint restraints),
    ``model_is_locked`` (analysis results current), and ``present_units`` +
    ``database_units`` (present is the active view; database is the internal storage
    system).

    Facts only. The MCP does not interpret the DOF vector — it never labels a model
    'Plane Frame XZ', '2D' or 'Space Frame'. You recognise that pattern from the flags;
    e.g. [true,false,true,false,true,false] means U1/U3/R2 active.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_model_settings_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_joints() -> dict[str, Any]:
    """Every point object in the open SAP model: name, global Cartesian coordinates
    (in the model's present units, echoed under ``units``) and the raw 6-DOF
    restraint flags [U1,U2,U3,R1,R2,R3] (True = restrained).

    Facts only. This does not classify supports as pinned/fixed/roller — that mapping
    is structural domain and belongs to you, the client, not the MCP.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_joints_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001 — relay transport failure honestly
        return _bridge_error(exc)


def get_frames() -> dict[str, Any]:
    """Every frame (line) object in the open SAP model: name, the two end point names
    (``point_i`` / ``point_j`` — they match the names from get_joints, so you join on
    them to get coordinates) and the assigned ``section`` property name.

    Facts only. This does not classify frames as chords/struts/diagonals — that role
    reasoning emerges from connectivity and dimensions in the client, not the MCP.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_frames_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_sections() -> dict[str, Any]:
    """The frame section property catalogue defined in the open SAP model: each
    section's ``name`` and its SAP ``prop_type`` (e.g. 'Rectangular').

    Facts only. Section names are model-supplied labels relayed verbatim — the MCP
    does not interpret them or resolve their geometric dimensions. To know which
    sections are actually *used*, cross-reference with get_frames (the ``section``
    field there); this tool lists what is *defined*.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_sections_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_materials() -> dict[str, Any]:
    """The material property catalogue defined in the open SAP model: each material's
    ``name``, its raw SAP ``mat_type`` (e.g. 'Steel', 'Concrete', 'NoDesign') and basic
    mechanical facts when available — ``e`` (modulus), ``nu`` (Poisson), ``thermal_coeff``,
    ``shear_modulus``, ``weight_per_volume``, ``mass_per_volume`` — in the model's present
    units (echoed under ``units``).

    Facts only. The MCP does not interpret a material: a name like 'MGP10' is reported
    with whatever SAP type it has ('NoDesign' here), never relabelled 'timber'. Fields
    are null when SAP does not provide them (e.g. non-isotropic materials), never faked.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_materials_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_section_properties(name: str) -> dict[str, Any]:
    """Dimensions and universal section properties for ONE frame section, by its exact
    ``name`` (as returned by get_sections). Returns the shape ``prop_type``, the
    referenced ``material`` name, ``dimensions`` (shape-specific geometry keyed by SAP's
    own parameter names, e.g. depth/width for Rectangular) and ``properties`` (universal:
    area, inertias i22/i33, torsion, moduli, radii of gyration). All in present units.

    Facts only — the bridge does not normalize geometry across shapes or interpret the
    section. Unsupported shapes return a structured error carrying the received type. To
    list all sections first, use get_sections; this resolves one at a time (compose the
    loop client-side if you need every section's dimensions).
    """
    base_url, timeout = bridge_settings()
    try:
        return get_section_properties_bridge(base_url, timeout, name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_load_patterns() -> dict[str, Any]:
    """The load pattern catalogue defined in the open SAP model: each pattern's ``name``,
    raw SAP ``load_type`` (e.g. 'Dead', 'Live', 'Wind', 'Snow') and
    ``self_weight_multiplier``.

    Facts only. Names are model-supplied labels relayed verbatim — 'PESO PROPIO' is not
    translated to 'Dead', and the MCP never assumes which patterns a model should have.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_load_patterns_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_load_cases() -> dict[str, Any]:
    """The analysis load case catalogue in the open SAP model: each case's ``name`` and
    raw SAP ``case_type`` (e.g. 'LinearStatic', 'Modal').

    Facts only. The case's internal definition (which patterns/factors it uses) is not
    resolved here — that is a later primitive. To see applied loads, that is also a later
    phase; this lists what cases are *defined*.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_load_cases_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_combinations() -> dict[str, Any]:
    """The load combination catalogue in the open SAP model: each combo's ``name``,
    ``combo_type`` (e.g. 'Linear Additive', 'Envelope') with its raw ``combo_type_code``,
    and ``items`` — the consolidated component list, each with ``case_name``,
    ``case_type`` ('LoadCase' or 'LoadCombo') and ``scale_factor``.

    Facts only. SAP's parallel arrays are recomposed for you. The MCP does not interpret
    a combo: 'ENVOLVENTE' is reported with combo_type 'Envelope', never labelled a
    seismic/ULS combo. Items of type 'LoadCase' reference names from get_load_cases;
    items of type 'LoadCombo' reference other combos (combo-of-combo is real).
    """
    base_url, timeout = bridge_settings()
    try:
        return get_combinations_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_distributed_loads_on_frame(frame_name: str) -> dict[str, Any]:
    """Distributed loads on ONE frame, by its exact ``frame_name`` (as in get_frames),
    across all load patterns. Each item has ``load_pattern``, ``load_type`` ('Force'/
    'Displacement'), ``direction`` (e.g. 'Gravity', 'Local 2') with raw ``direction_code``,
    ``coord_system``, ``rel_dist_start``/``rel_dist_end`` (0..1) and ``value_start``/
    ``value_end`` (present units).

    Facts only. An empty ``loads`` list means the frame has no distributed loads — not an
    error. Directions are relayed raw ('Gravity' stays 'Gravity'); ``load_pattern`` values
    reference names from get_load_patterns. To scan the model, loop get_frames client-side.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_distributed_loads_on_frame_bridge(base_url, timeout, frame_name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_point_loads_on_joint(joint_name: str) -> dict[str, Any]:
    """Point loads (force + moment) on ONE joint, by its exact ``joint_name`` (as in
    get_joints), across all load patterns. Each item has ``load_pattern``,
    ``coord_system`` and the six components ``f1/f2/f3`` (force) and ``m1/m2/m3`` (moment),
    in present units.

    Facts only. An empty ``loads`` list means the joint has no point loads — not an error.
    ``load_pattern`` values reference names from get_load_patterns.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_point_loads_on_joint_bridge(base_url, timeout, joint_name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_load_case_details(case_name: str) -> dict[str, Any]:
    """Composition of ONE load case, by its exact ``case_name`` (as in get_load_cases).
    Returns ``case_type`` and ``loads`` — for a LinearStatic case, the applied patterns
    with ``load_type``, ``load_pattern`` and ``scale_factor`` (mirrors get_combinations
    items). For any other case type, ``unsupported_case_type`` is true and ``loads`` is
    empty: the case and its type are reported, internals deferred (not an error).

    Facts only. ``load_pattern`` values reference names from get_load_patterns.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_load_case_details_bridge(base_url, timeout, case_name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def run_analysis(cases_to_run: list[str] | None = None) -> dict[str, Any]:
    """Run the structural analysis on the open SAP model. MUTATES computation state (it
    produces results and may lock the model); it does NOT modify the model definition.

    With ``cases_to_run=None``, runs all pending cases. With a list of case names (from
    get_load_cases), runs only those — names are validated to exist first, and the model's
    run-case flags are restored afterwards. Returns ``ran_count``, ``cases_run``,
    ``runtime_seconds`` (the call is BLOCKING — large models can take a while),
    ``model_is_locked`` and a per-case ``status`` snapshot.

    A model-side failure (non-convergence, singular matrix) surfaces as a structured
    error or as cases that did not reach 'Finished' — reported as facts. The bridge never
    says the model is wrong. Re-running is idempotent (SAP skips up-to-date cases).
    """
    base_url, timeout = bridge_settings()
    try:
        return run_analysis_bridge(base_url, timeout, cases_to_run)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_analysis_status() -> dict[str, Any]:
    """Read the current analysis status of the open SAP model. Read-only.

    Returns ``model_is_locked`` and, per load case, ``case_name``, ``status`` (named:
    'Not Run'/'Could Not Start'/'Not Finished'/'Finished') with raw ``status_code``, and
    ``has_run`` (True only when Finished — results exist). Facts only: a locked model or a
    case that did not finish is reported as-is, never judged.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_analysis_status_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_joint_displacements(joint_name: str, case_name: str) -> dict[str, Any]:
    """The 6-DOF displacement of ONE joint in ONE load case (LinearStatic). Returns
    ``u1/u2/u3`` (translations) and ``r1/r2/r3`` (rotations) in the global system,
    present units. Read-only post-analysis.

    Facts only. A restrained DOF reads ~0 (as SAP gives it). If the case has not been run,
    returns a structured ``case_not_run`` (call run_analysis first); a non-LinearStatic
    case returns ``unsupported_case_type``. A large displacement is a number, not "failure".
    """
    base_url, timeout = bridge_settings()
    try:
        return get_joint_displacements_bridge(base_url, timeout, joint_name, case_name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_joint_reactions(joint_name: str, case_name: str) -> dict[str, Any]:
    """The 6-DOF reaction (force + moment) of ONE joint in ONE load case (LinearStatic).
    Returns ``f1/f2/f3`` (forces) and ``m1/m2/m3`` (moments) in the global system, present
    units. Read-only post-analysis.

    Facts only. An unrestrained DOF reads ~0; a fully free joint reads the zero vector —
    correct information, not an error. ``case_not_run`` / ``unsupported_case_type`` as for
    displacements. Reactions at the restrained joints balance the applied loads (global
    equilibrium) — a cross-check the client can compose, not a judgement the bridge makes.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_joint_reactions_bridge(base_url, timeout, joint_name, case_name)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_frame_forces(frame_name: str, case_name: str, station: float | None = None) -> dict[str, Any]:
    """Internal forces along ONE frame in ONE load case (LinearStatic): a list of
    ``stations``, each with ``relative_distance`` (0..1), ``absolute_distance``, ``p``
    (axial), ``v2``/``v3`` (shears), ``t`` (torsion), ``m2``/``m3`` (moments), present
    units. Read-only post-analysis.

    ``station`` (0..1) returns just that station; omit for all SAP computed. Facts only —
    a large moment is a number, not "overstress". ``case_not_run`` / ``unsupported_case_type``
    as above.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_frame_forces_bridge(base_url, timeout, frame_name, case_name, station)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


# --- Write-side: savepoints (undo infrastructure, Fase 1g.1) -----------------


def create_savepoint(name: str, dry_run: bool = False) -> dict[str, Any]:
    """Save the current model state to a savepoint file (WRITE — to the filesystem, not
    the SAP model in memory). The file is ``<model>__sp_<name>.sdb`` next to the model.
    Refuses if a savepoint of that ``name`` already exists (no silent overwrite — use a
    different name). ``dry_run=true`` previews the target path + estimated size + that the
    directory is writable, without writing.

    This is undo infrastructure: take a savepoint before a risky write, then
    restore_savepoint if the result is unwanted (see client_patterns.md Pattern 2).
    """
    base_url, timeout = bridge_settings()
    try:
        return create_savepoint_bridge(base_url, timeout, name, dry_run)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def restore_savepoint(name: str, confirm: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Restore a savepoint, REPLACING the currently loaded model with it (and discarding
    unsaved changes). Destructive, so ``confirm=true`` is mandatory — without it you get
    a ``confirm_required`` error. ``dry_run=true`` previews which savepoint would be loaded
    without replacing anything. A missing savepoint → ``savepoint_not_found``.

    Do NOT pass confirm=true automatically: preview with dry_run, decide, then confirm
    (client_patterns.md Pattern 3).
    """
    base_url, timeout = bridge_settings()
    try:
        return restore_savepoint_bridge(base_url, timeout, name, confirm, dry_run)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def list_savepoints() -> dict[str, Any]:
    """List the savepoints that exist for the current model (read-only filesystem scan).
    Returns each savepoint's ``name``, absolute ``path``, ``created_at`` (ISO-8601) and
    ``size_bytes``. Empty list if none (not an error). Works even if SAP is busy — it is a
    directory scan, not an OAPI call.
    """
    base_url, timeout = bridge_settings()
    try:
        return list_savepoints_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def set_active_dof(active_dof: list[bool], dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Set the model's active DOFs (WRITE — mutates the model; a global setting). ``active_dof``
    must be exactly 6 booleans [U1,U2,U3,R1,R2,R3]. Because it is a global setting,
    ``confirm=true`` is mandatory — without it you get ``confirm_required``. ``dry_run=true``
    previews the change (with a readable per-DOF diff like 'U2: false → true') without
    applying.

    Facts only — the bridge validates shape (6 booleans) and relays SAP; it does NOT judge
    whether a DOF pattern is structurally valid (SAP accepts even all-false) and does NOT
    unlock a locked model (a locked model rejects the change → oapi_call_failed). Recommended
    flow (client_patterns.md): create_savepoint → set_active_dof(dry_run) → review →
    set_active_dof(confirm=true) → verify → restore_savepoint if unwanted.
    """
    base_url, timeout = bridge_settings()
    try:
        return set_active_dof_bridge(base_url, timeout, active_dof, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def set_present_units(units: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Set the model's present (display) units by NAME (WRITE — mutates the model; a global
    setting). ``units`` is an eUnits member name, e.g. 'N_m_C', 'kgf_m_C', 'lb_ft_F' — an
    unknown name returns ``unknown_unit_system`` (with the supported names listed).
    ``confirm=true`` is mandatory (else ``confirm_required``); ``dry_run=true`` previews with a
    ``change_summary`` like 'kgf_m_C → N_m_C' without applying.

    Changing present units is a DISPLAY preference: it reformats how the read primitives
    report values (distances stay metres; forces/moments rescale, e.g. kgf → N ≈ ×9.81).
    The bridge converts nothing itself; it sets the system and the read-side reports in it.
    database_units is not touched. Recommended flow (client_patterns.md): create_savepoint →
    dry_run → review → confirm → verify → restore_savepoint if unwanted.
    """
    base_url, timeout = bridge_settings()
    try:
        return set_present_units_bridge(base_url, timeout, units, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def set_model_locked(locked: bool, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Set the model lock state (WRITE — global state). ``run_analysis`` LOCKS the model and
    SAP then rejects edits to the model definition (create/assign/modify) with oapi_call_failed.
    Call this with ``locked=false`` (and ``confirm=true``) to UNLOCK and keep modifying — this is
    how you close an iterative write→analyze→write loop. ``confirm=true`` is mandatory (global
    state); ``dry_run=true`` previews; idempotent (setting the current value is a valid no-op).
    The bridge does NOT auto-unlock for you — that keeps every primitive predictable.
    """
    base_url, timeout = bridge_settings()
    try:
        return set_model_locked_bridge(base_url, timeout, locked, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def open_model(path: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Open a model, REPLACING the currently loaded one (WRITE). ``path`` must be an ABSOLUTE
    .sdb path that exists on disk (else ``invalid_path`` / ``file_not_found`` — the bridge checks
    before opening so SAP never ends up on a phantom file). ``confirm=true`` is mandatory (it
    discards unsaved changes); ``dry_run=true`` previews.

    Main use: after restore_savepoint the session is loaded on the savepoint file; call
    open_model(<base model path>) to return to the original model. Also for switching models or
    recovering from an unexpected state.
    """
    base_url, timeout = bridge_settings()
    try:
        return open_model_bridge(base_url, timeout, path, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def reset_workspace(dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Reset the bridge's transient workspace to a clean copy of the immutable BASE model
    (WRITE). The bridge operates on a workspace copy so the user's base file is never written;
    this regenerates that workspace from the clean base, returning you to a known baseline —
    without relying on savepoints. ``confirm=true`` mandatory (discards workspace changes);
    ``dry_run=true`` previews. Use between iterations of a what-if experiment to start each one
    from the same clean baseline.
    """
    base_url, timeout = bridge_settings()
    try:
        return reset_workspace_bridge(base_url, timeout, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def save_workspace_as(path: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Save the current workspace content to ``path`` as a NEW base model (WRITE — closes the
    build-from-blank cycle). ``path`` must be an ABSOLUTE .sdb path and must NOT be the current
    base model (writing the base is a future commit primitive; else ``invalid_path``).
    ``confirm=true`` is mandatory ONLY to OVERWRITE an existing file (saving to a fresh path
    needs no confirm); ``dry_run=true`` previews.

    Use after building a model from new_blank_model (or after editing any workspace) to
    materialize it on disk. After saving, ``path`` becomes the immutable base and the bridge
    re-anchors onto a fresh workspace beside it — the normal workspace pattern resumes (you can
    reset_workspace, savepoint, etc. against the new base).
    """
    base_url, timeout = bridge_settings()
    try:
        return save_workspace_as_bridge(base_url, timeout, path, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def new_blank_model(units: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Initialize an EMPTY model from scratch (WRITE — build-from-blank). ``units`` is a
    unit-system name (eUnits member, e.g. 'kgf_m_C', 'N_m_C'; else ``unknown_unit_system``).
    DESTRUCTIVE: discards the currently loaded model WITHOUT saving → ``confirm=true`` is
    mandatory (else ``confirm_required``); ``dry_run=true`` previews.

    The empty model (0 joints, 0 frames, SAP default materials) gets a temp workspace and NO
    base file. Build it with the create_* primitives (materials, sections, geometry — phases
    1h.2+), then call save_workspace_as(path) to materialize it as a new base on disk. Units are
    not anchored — set_present_units can change them afterward.
    """
    base_url, timeout = bridge_settings()
    try:
        return new_blank_model_bridge(base_url, timeout, units, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def create_material(name: str, material_type: str, dry_run: bool = False) -> dict[str, Any]:
    """Create a material (WRITE — new object). ``name`` MUST start with the bridge namespace
    prefix (default 'AI_') — otherwise ``prefix_required``. ``material_type`` is an eMatType
    member name: 'Steel', 'Concrete', 'NoDesign', 'Aluminum', 'ColdFormed', 'Rebar',
    'Tendon', 'Masonry' — there is NO 'Wood' in SAP (use 'NoDesign' for timber); an unknown
    type → ``unknown_material_type`` (lists the valid names). An existing name →
    ``name_already_exists`` (SAP would otherwise overwrite it silently). No confirm needed
    (creating a new prefixed object). ``dry_run=true`` previews.

    A freshly created material has only default properties — call
    set_material_properties_isotropic next to make it usable (create + set is the client's
    composition; see client_patterns.md Pattern 4).
    """
    base_url, timeout = bridge_settings()
    try:
        return create_material_bridge(base_url, timeout, name, material_type, dry_run)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def set_material_properties_isotropic(
    name: str, E: float, poisson_ratio: float, thermal_coef: float,
    dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """Set a material's isotropic mechanical properties (WRITE). The material must exist
    (else ``object_not_found``). ``confirm=true`` is required only when modifying a
    NON-bridge (pre-existing) material like 'MGP10' (§5.1); a bridge-owned material (prefix
    'AI_') needs none. ``dry_run=true`` previews with a per-field diff.

    ``E`` (modulus), ``poisson_ratio`` and ``thermal_coef`` are in the model's PRESENT
    UNITS — you must know what those are (check get_model_settings); the bridge converts
    nothing. SAP derives the shear modulus G from E and poisson_ratio.
    """
    base_url, timeout = bridge_settings()
    try:
        return set_material_properties_isotropic_bridge(
            base_url, timeout, name, E, poisson_ratio, thermal_coef, dry_run, confirm
        )
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def create_rectangular_section(
    name: str, material: str, depth: float, width: float,
    color: int | None = None, notes: str = "", dry_run: bool = False
) -> dict[str, Any]:
    """Create a rectangular frame section (WRITE — new object). ``name`` MUST start with the
    bridge prefix (default 'AI_') else ``prefix_required``. ``material`` must be an existing
    material (else ``object_not_found``). ``depth`` (T3) and ``width`` (T2) must be > 0 (else
    ``invalid_dimensions``), in the model's present length units. An existing name →
    ``name_already_exists`` (SAP would otherwise overwrite it silently). No confirm needed.
    ``dry_run=true`` previews. The applied values are read back from SAP.
    """
    base_url, timeout = bridge_settings()
    try:
        return create_rectangular_section_bridge(
            base_url, timeout, name, material, depth, width, color, notes, dry_run
        )
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def modify_rectangular_section(
    name: str, material: str | None = None, depth: float | None = None,
    width: float | None = None, color: int | None = None, notes: str | None = None,
    dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """Modify an existing rectangular frame section (WRITE). The section must exist and be
    Rectangular (else ``object_not_found`` / ``section_type_mismatch``). Pass only the fields
    you want to change — all None → ``nothing_to_modify``. ``confirm=true`` is required only
    for a NON-bridge (pre-existing) section like 'MGP10_33x73' (§5.1); a bridge-owned 'AI_'
    section needs none. ``dry_run=true`` previews with a per-field diff. Dimensions in present
    units; the bridge converts nothing.
    """
    base_url, timeout = bridge_settings()
    try:
        return modify_rectangular_section_bridge(
            base_url, timeout, name, material, depth, width, color, notes, dry_run, confirm
        )
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def assign_section_to_frames(
    section_name: str, frame_names: list, dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """Assign ONE section to many frames (WRITE — batch over pre-existing frames). The
    section and EVERY frame must exist (strict pre-validation → ``object_not_found`` listing
    the missing ones). Empty ``frame_names`` → ``empty_batch``. ``confirm=true`` is mandatory
    (touches pre-existing frames, §5.1). ``dry_run=true`` previews with per-frame changes
    without applying.

    Returns ``applied`` (each frame's previous→current section, read back), ``failed_at``
    (null in normal flow — pre-validation prevents it; set only on an unexpected mid-loop
    OAPI failure) and ``not_attempted``. A >10-frame result includes a ``hint`` suggesting
    dry_run. Recommended: create_savepoint → dry_run → review → confirm → restore if unwanted.
    """
    base_url, timeout = bridge_settings()
    try:
        return assign_section_to_frames_bridge(
            base_url, timeout, section_name, frame_names, dry_run, confirm
        )
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def assign_sections_to_frames(
    assignments: list, dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """Assign sections to frames per a heterogeneous mapping (WRITE — batch). ``assignments``
    is a list of ``{"frame_name": ..., "section_name": ...}``. Every referenced section and
    frame must exist (strict pre-validation). Empty → ``empty_batch``. ``confirm=true``
    mandatory; ``dry_run=true`` previews. Same applied/failed_at/not_attempted shape as the
    homogeneous tool. The bridge composes a loop internally (the OAPI has no native
    heterogeneous batch) — you don't see that detail.
    """
    base_url, timeout = bridge_settings()
    try:
        return assign_sections_to_frames_bridge(base_url, timeout, assignments, dry_run, confirm)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)
