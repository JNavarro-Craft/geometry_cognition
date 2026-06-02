"""MCP tool logic: relay facts from the SAP bridge. No structural interpretation.

Each tool calls the bridge over HTTP and returns its JSON essentially verbatim,
adding only an honest error envelope on transport failure. The agnostic test
(brief, Principle 1) holds: these return joints/frames/sections — facts that exist
in any solver — never is_*/verify_*/check_* judgements.
"""
from __future__ import annotations

from typing import Any

from .bridge_backend import (
    bridge_settings,
    get_analysis_status_bridge,
    get_combinations_bridge,
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
