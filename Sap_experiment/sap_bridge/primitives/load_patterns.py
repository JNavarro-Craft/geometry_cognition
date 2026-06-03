"""Read the load pattern catalogue defined in the live SAP model.

Pure facts: each pattern's name, its raw SAP load type and its self-weight multiplier.
The bridge does not translate a name ('PESO PROPIO' stays 'PESO PROPIO', not 'Dead')
and does not know which patterns a model "should" have — the patterns are a fact of the
model, never created or assumed by the bridge (brief, Principle 1; the SapConfigurator
leak we refuse).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §9):

  * cLoadPatterns.GetNameList(ref NumberNames, ref MyName) — no type filter, returns all.
  * GetLoadType(name, ref eLoadPatternType) — the eLoadPatternType out-param needs a real
    enum member as pythonnet placeholder (an int is rejected; same rule as §5).
  * GetSelfWTMultiplier(name, ref Double) — note the capital WT.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import CreateLoadPatternResponse, LoadPattern, LoadPatternCreation
from ..namespace import assert_no_conflict, assert_prefix_required
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.load_patterns")


def get_load_patterns(sap_model: Any, oapi_namespace: Any) -> list[LoadPattern]:
    """Return every load pattern with its SAP type and self-weight multiplier.

    ``oapi_namespace`` is the loaded SAP2000v1 module, needed for the eLoadPatternType
    enum placeholder the OAPI out-param requires.
    """
    lp = sap_model.LoadPatterns
    type_placeholder = oapi_namespace.eLoadPatternType.Dead

    ret, number, names = lp.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadPatterns.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"LoadPatterns.GetNameList reported {number} patterns but returned no names",
        )

    patterns: list[LoadPattern] = []
    for name in names:
        name = str(name)
        tret, load_type = lp.GetLoadType(name, type_placeholder)
        if tret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadPatterns.GetLoadType('{name}') returned {tret}",
            )
        sret, sw_mult = lp.GetSelfWTMultiplier(name, 0.0)
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadPatterns.GetSelfWTMultiplier('{name}') returned {sret}",
            )
        patterns.append(
            LoadPattern(
                name=name,
                load_type=str(load_type),
                self_weight_multiplier=float(sw_mult),
            )
        )
    return patterns


def list_pattern_names(sap_model: Any) -> list[str]:
    """Just the load-pattern names (for existence checks by write primitives, Fase 1h.4)."""
    ret, number, names = sap_model.LoadPatterns.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"LoadPatterns.GetNameList returned {ret}"
        )
    return [str(names[i]) for i in range(number)] if number else []


def pattern_type_names(oapi_namespace: Any) -> list[str]:
    """Every eLoadPatternType member name this assembly supports (read off the live enum, no
    hardcoded table — §36)."""
    import clr  # type: ignore
    import System  # type: ignore

    return list(System.Enum.GetNames(clr.GetClrType(oapi_namespace.eLoadPatternType)))


def resolve_pattern_type(oapi_namespace: Any, name: str) -> Any | None:
    """Resolve a pattern-type NAME (case-insensitive) to its eLoadPatternType member, or None.

    Case-insensitive because the OAPI uses CamelCase ('Dead','Live') but callers may pass
    'DEAD'/'live' (§36). Matches against the live enum so the accepted set never drifts."""
    members = pattern_type_names(oapi_namespace)
    match = next((m for m in members if m.lower() == name.lower()), None)
    return getattr(oapi_namespace.eLoadPatternType, match, None) if match else None


def validate_load_pattern_exists(sap_model: Any, pattern_name: str) -> None:
    """Raise OBJECT_NOT_FOUND unless ``pattern_name`` is a defined load pattern. Shared by the
    joint/frame load primitives (and a future combinations primitive)."""
    if pattern_name not in set(list_pattern_names(sap_model)):
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"load pattern '{pattern_name}' not found (list with GET /v1/load-patterns)",
        )


def create_load_pattern(
    sap_model: Any, oapi_namespace: Any, name: str, pattern_type: str,
    self_weight_multiplier: float, add_load_case: bool, dry_run: bool, confirm: bool,
) -> CreateLoadPatternResponse:
    """Create a load pattern. Prefix-enforced; pattern_type resolved off the live enum
    (case-insensitive); confirm mandatory. ``LoadPatterns.Add`` rejects a duplicate (ret=1) but
    we also guard name_already_exists for a clear message (§36)."""
    with audited("create_load_pattern", {"name": name, "pattern_type": pattern_type,
                                         "self_weight_multiplier": self_weight_multiplier,
                                         "add_load_case": add_load_case,
                                         "dry_run": dry_run, "confirm": confirm}) as ctx:
        assert_prefix_required(name)
        type_member = resolve_pattern_type(oapi_namespace, pattern_type)
        if type_member is None:
            supported = ", ".join(pattern_type_names(oapi_namespace))
            raise SapSessionError(
                error_codes.UNKNOWN_LOAD_PATTERN_TYPE,
                f"unknown load pattern type '{pattern_type}'; supported: {supported}",
            )
        assert_no_conflict(name, list_pattern_names(sap_model))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": name, "pattern_type": pattern_type}
            return CreateLoadPatternResponse(
                dry_run=True,
                would_apply=LoadPatternCreation(
                    name=name, pattern_type=pattern_type,
                    self_weight_multiplier=self_weight_multiplier, add_load_case=add_load_case),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "create_load_pattern modifies the model; pass confirm=true to create",
            )

        ret = sap_model.LoadPatterns.Add(name, type_member, self_weight_multiplier, add_load_case)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadPatterns.Add('{name}') returned {ret_code}",
            )
        # Read back the stored type (M2): GetLoadType gives the canonical member name.
        tret, stored_type = sap_model.LoadPatterns.GetLoadType(name, oapi_namespace.eLoadPatternType.Dead)
        stored = str(stored_type) if tret == 0 else pattern_type
        ctx["result_details"] = {"name": name, "pattern_type": stored}
        return CreateLoadPatternResponse(
            dry_run=False,
            applied=LoadPatternCreation(
                name=name, pattern_type=stored,
                self_weight_multiplier=self_weight_multiplier, add_load_case=add_load_case),
        )
