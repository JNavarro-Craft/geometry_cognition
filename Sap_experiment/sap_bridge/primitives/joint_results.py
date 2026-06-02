"""Read joint analysis results (displacements, reactions) from the analysed model.

Read-only post-analysis: the results already exist in the analysed model; these
primitives only expose them. They depend on computation state, though — a case that has
not been run has nothing to read, reported as a structured ``case_not_run`` (the client
should call run_analysis first). The bridge interprets nothing: a large displacement is a
fact, not "failure" (anti-pattern #4).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §14-15):

  * cAnalysisResults.JointDispl / JointReact(Name, eItemTypeElm, ref NumberResults,
    ref Obj[], ref Elm[], ref LoadCase[], ref StepType[], ref StepNum[], ref C1[]..C6[]):
    the tuple has 13 elements — ret, n, then 5 metadata arrays + 6 component arrays at
    indices 7..12 (NOT 8..13 — verified live; the kind of off-by-one the 4-tuple lesson
    warns about). Displ components are U1..R3; React components F1..M3.
  * Results must be SELECTED for output first: Setup.DeselectAllCasesAndCombosForOutput()
    then SetCaseSelectedForOutput(name, True). Without selection the call returns
    ret=1, NumberResults=0 — which is why we gate on case status, not on that silence.
  * eItemTypeElm.ObjectElm scopes to the named object. LinearStatic → StepNum 0.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import JointDisplacements, JointReactions
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.joint_results")

_SUPPORTED_CASE_TYPE = "LinearStatic"
_FINISHED_STATUS = 4


def ensure_case_ready(sap_model: Any, oapi_namespace: Any, case_name: str) -> None:
    """Validate that ``case_name`` exists, is LinearStatic, and has been run.

    Shared guard for every results primitive. Raises:
      * OAPI_CALL_FAILED if the case name is unknown,
      * UNSUPPORTED_CASE_TYPE if it is not LinearStatic (Modal, spectrum, …),
      * CASE_NOT_RUN if it exists but has no results yet.
    """
    lc = sap_model.LoadCases
    type_placeholder = oapi_namespace.eLoadCaseType.LinearStatic

    tret, case_type, _sub = lc.GetTypeOAPI(case_name, type_placeholder, 0)
    if tret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadCases.GetTypeOAPI('{case_name}') returned {tret} "
            "(unknown case? cross-check /v1/load_cases)",
        )
    if str(case_type) != _SUPPORTED_CASE_TYPE:
        raise SapSessionError(
            error_codes.UNSUPPORTED_CASE_TYPE,
            f"case '{case_name}' is type '{case_type}', results not exposed this phase "
            "(only LinearStatic)",
        )

    # Has it been run? GetCaseStatus is global; find this case's status.
    sret, n, names, statuses = sap_model.Analyze.GetCaseStatus(0, None, None)
    if sret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Analyze.GetCaseStatus returned {sret}",
        )
    status_by_name = {str(names[i]): int(statuses[i]) for i in range(n)}
    if status_by_name.get(case_name) != _FINISHED_STATUS:
        raise SapSessionError(
            error_codes.CASE_NOT_RUN,
            f"case '{case_name}' has no results (status "
            f"{status_by_name.get(case_name)}); call run_analysis first",
        )


def select_case_for_output(sap_model: Any, case_name: str) -> None:
    """Select only ``case_name`` for results output (required before reading)."""
    setup = sap_model.Results.Setup
    dret = setup.DeselectAllCasesAndCombosForOutput()
    if dret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Results.Setup.DeselectAllCasesAndCombosForOutput returned {dret}",
        )
    sret = setup.SetCaseSelectedForOutput(case_name, True)
    if sret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Results.Setup.SetCaseSelectedForOutput('{case_name}') returned {sret}",
        )


def _single_result(res: tuple, name: str, kind: str) -> tuple:
    """Unpack a joint result tuple, asserting exactly one result row.

    Tuple layout (13 elements): ret, NumberResults, Obj[], Elm[], LoadCase[], StepType[],
    StepNum[], C1[], C2[], C3[], C4[], C5[], C6[]. Returns (step_num, [c1..c6]).
    """
    ret, n = res[0], res[1]
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Results.{kind}('{name}') returned {ret}",
        )
    if n == 0:
        # Selection succeeded but no row — treat as a shape problem, surfaced loudly.
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Results.{kind}('{name}') returned no result rows after case selection",
        )
    components = [res[k] for k in range(7, 13)]
    if any(c is None or len(c) < 1 for c in components):
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Results.{kind}('{name}') reported {n} rows but a component array is missing",
        )
    step_num = float(res[6][0]) if res[6] is not None and len(res[6]) else 0.0
    return step_num, [float(c[0]) for c in components]


def get_joint_displacements(sap_model: Any, oapi_namespace: Any, joint_name: str, case_name: str) -> JointDisplacements:
    """Return the 6-DOF displacement of ``joint_name`` in ``case_name`` (LinearStatic)."""
    ensure_case_ready(sap_model, oapi_namespace, case_name)
    select_case_for_output(sap_model, case_name)
    obj_elm = oapi_namespace.eItemTypeElm.ObjectElm
    res = sap_model.Results.JointDispl(
        joint_name, obj_elm, 0, None, None, None, None, None, None, None, None, None, None, None
    )
    step_num, (u1, u2, u3, r1, r2, r3) = _single_result(res, joint_name, "JointDispl")
    return JointDisplacements(
        joint=joint_name, case_name=case_name, coord_system="Global", step_number=step_num,
        u1=u1, u2=u2, u3=u3, r1=r1, r2=r2, r3=r3,
    )


def get_joint_reactions(sap_model: Any, oapi_namespace: Any, joint_name: str, case_name: str) -> JointReactions:
    """Return the 6-DOF reaction of ``joint_name`` in ``case_name`` (LinearStatic).

    Unrestrained DOFs read ~0; a fully free joint reads the zero vector SAP returns —
    correct information, not an error.
    """
    ensure_case_ready(sap_model, oapi_namespace, case_name)
    select_case_for_output(sap_model, case_name)
    obj_elm = oapi_namespace.eItemTypeElm.ObjectElm
    res = sap_model.Results.JointReact(
        joint_name, obj_elm, 0, None, None, None, None, None, None, None, None, None, None, None
    )
    step_num, (f1, f2, f3, m1, m2, m3) = _single_result(res, joint_name, "JointReact")
    return JointReactions(
        joint=joint_name, case_name=case_name, coord_system="Global", step_number=step_num,
        f1=f1, f2=f2, f3=f3, m1=m1, m2=m2, m3=m3,
    )
