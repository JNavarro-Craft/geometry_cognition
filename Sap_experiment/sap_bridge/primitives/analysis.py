"""Run analysis and read analysis status on the live SAP model.

This is the project's first crossing into MUTATING operations: RunAnalysis changes the
model's *computation* state (it produces results and may lock the model). It does not
modify the model definition — that is Fase 1g, gated behind a design doc. The bridge
still interprets nothing: it reports case status as facts (Not Run / Finished / …) and
never says a model is wrong because a case did not converge.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §13):

  * cAnalyze.RunAnalysis() takes NO arguments — there is no "run these cases" overload.
    To run a subset you flag cases first via SetRunCaseFlag(Name, Run, All) then call
    RunAnalysis(). So get the current flags, set the requested subset, run, and RESTORE
    the original flags so the request leaves no side effect on what is flagged.
  * cAnalyze.GetCaseStatus(ref NumberItems, ref CaseName[], ref Status[]) is GLOBAL
    (no name argument) — three parallel arrays for all cases. Status is a raw int with
    the documented mapping below; there is no status enum in this assembly.
  * cAnalyze.GetRunCaseFlag(ref NumberItems, ref CaseName[], ref Run[]) — parallel
    arrays of the current run flags. cSapModel.GetModelIsLocked() -> bool.
  * RunAnalysis is BLOCKING (synchronous); large models can take a while.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .. import error_codes
from ..contracts import AnalysisRunResponse, AnalysisStatusResponse, CaseStatus
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.analysis")

# SAP2000 OAPI documented GetCaseStatus integer mapping. Bare int in this assembly, so
# the bridge maps it to SAP's own status name (a relay, not interpretation); 'Unknown'
# for an out-of-range code, reported never guessed.
_STATUS_NAMES = {
    1: "Not Run",
    2: "Could Not Start",
    3: "Not Finished",
    4: "Finished",
}
_FINISHED_CODE = 4


def _read_case_status(analyze: Any) -> list[CaseStatus]:
    """Read the per-case analysis status (GetCaseStatus, global parallel arrays)."""
    ret, n, names, statuses = analyze.GetCaseStatus(0, None, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Analyze.GetCaseStatus returned {ret}",
        )
    if n == 0:
        return []
    if names is None or statuses is None or len(names) < n or len(statuses) < n:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Analyze.GetCaseStatus reported {n} cases but a parallel array is missing/short",
        )
    rows: list[CaseStatus] = []
    for i in range(n):
        code = int(statuses[i])
        rows.append(
            CaseStatus(
                case_name=str(names[i]),
                status=_STATUS_NAMES.get(code, "Unknown"),
                status_code=code,
                has_run=(code == _FINISHED_CODE),
            )
        )
    return rows


def get_analysis_status(sap_model: Any) -> AnalysisStatusResponse:
    """Read current analysis status: per-case status + whether the model is locked."""
    analyze = sap_model.Analyze
    rows = _read_case_status(analyze)
    return AnalysisStatusResponse(
        model_is_locked=bool(sap_model.GetModelIsLocked()),
        count=len(rows),
        status=rows,
    )


def run_analysis(sap_model: Any, cases_to_run: list[str] | None) -> AnalysisRunResponse:
    """Run the analysis. None runs all pending cases; a list runs only those by name.

    Validates every requested name exists before touching SAP (refuses with
    OAPI_UNEXPECTED_SHAPE otherwise). For a subset, flags those cases, runs, then
    restores the original run-case flags. RunAnalysis is blocking; runtime is reported.
    """
    analyze = sap_model.Analyze

    # Enumerate existing cases up front (also the validation set). GetRunCaseFlag returns
    # four values: (ret, NumberItems, CaseName[], Run[]).
    sret, ncases, case_names, case_flags = analyze.GetRunCaseFlag(0, None, None)
    if sret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Analyze.GetRunCaseFlag returned {sret}",
        )
    existing = [str(case_names[i]) for i in range(ncases)] if ncases else []
    existing_set = set(existing)

    saved_flags: list[tuple[str, bool]] | None = None
    if cases_to_run is not None:
        unknown = [c for c in cases_to_run if c not in existing_set]
        if unknown:
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"run_analysis: unknown case name(s) {unknown}; "
                "cross-check /v1/load_cases (refused before touching SAP)",
            )
        # Snapshot current flags (from the call above) to restore afterwards.
        saved_flags = [(str(case_names[i]), bool(case_flags[i])) for i in range(ncases)]
        # Flag only the requested subset.
        requested = set(cases_to_run)
        for name in existing:
            fret = analyze.SetRunCaseFlag(name, name in requested, False)
            if fret != 0:
                raise SapSessionError(
                    error_codes.OAPI_CALL_FAILED,
                    f"Analyze.SetRunCaseFlag('{name}') returned {fret}",
                )

    # Run (blocking). Measure wall-clock time.
    start = time.monotonic()
    try:
        rret = analyze.RunAnalysis()
    finally:
        # Always restore the original flags, even if the run raised.
        if saved_flags is not None:
            for name, flag in saved_flags:
                analyze.SetRunCaseFlag(name, flag, False)
    runtime = time.monotonic() - start

    if rret != 0:
        # An OAPI status from the run itself. The bridge relays the code; the client
        # interprets what it means (singular matrix, missing supports, …).
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Analyze.RunAnalysis returned {rret} (model-side analysis failure; "
            "see SAP for details — the bridge does not interpret it)",
        )

    rows = _read_case_status(analyze)
    cases_run = [r.case_name for r in rows if r.has_run]
    return AnalysisRunResponse(
        ran_count=len(cases_run),
        cases_run=cases_run,
        runtime_seconds=round(runtime, 3),
        model_is_locked=bool(sap_model.GetModelIsLocked()),
        status=rows,
    )
