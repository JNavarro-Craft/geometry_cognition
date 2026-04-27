from __future__ import annotations

from typing import Any

from shared.contracts import validate_payload


FORBIDDEN_TERMS = {"panel", "beam", "truss", "sip", "connector", "wood", "steel"}
FINAL_TRUTH_TERMS = {"final_truth", "definitive", "ground_truth", "confirmed_truth", "absolute_truth"}


def _normalize_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _exact_entity_id(value: Any) -> str:
    """entity_id identity for R2: no strip or truncation (entity_schema.v1.json)."""
    if value is None:
        return ""
    return str(value)


def _exact_evidence_id(value: Any) -> str:
    """evidence_id identity for R3: no strip; must match evidence_items (evidence_schema)."""
    if value is None:
        return ""
    return str(value)


def _contains_forbidden(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in FORBIDDEN_TERMS)


def _contains_final_truth_claim(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_final_truth_claim(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_final_truth_claim(v) for v in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(term in lowered for term in FINAL_TRUTH_TERMS)
    return False


def _result(
    validation_id: str,
    target_id: str,
    rule_id: str,
    rule_name: str,
    status: str,
    severity: str,
    evidence: list[str],
    recommendation: str | None,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    item = {
        "validation_id": validation_id,
        "target_id": target_id,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "status": status,
        "severity": severity,
        "evidence": evidence,
        "recommendation": recommendation,
        "skipped_reason": skipped_reason,
    }
    validate_payload("validation_schema.v1.json", item)
    return item


def validate_hypotheses(payload: dict[str, Any]) -> dict[str, Any]:
    hypotheses = payload.get("hypotheses", [])
    evidence_items = payload.get("evidence_items", [])
    entities = payload.get("entities", [])
    relations = payload.get("relations", [])

    evidence_ids = {
        _exact_evidence_id(item.get("evidence_id")) for item in evidence_items if _exact_evidence_id(item.get("evidence_id"))
    }
    entity_ids = {_exact_entity_id(item.get("entity_id")) for item in entities if _exact_entity_id(item.get("entity_id"))}

    results: list[dict[str, Any]] = []
    idx = 1
    for hyp in hypotheses:
        hypothesis_id = _normalize_id(hyp.get("hypothesis_id")) or "unknown_hypothesis"
        target_id = hypothesis_id
        supporting = [
            _exact_evidence_id(x) for x in hyp.get("supporting_evidence", []) if _exact_evidence_id(x)
        ]
        contradicting = [
            _exact_evidence_id(x) for x in hyp.get("contradicting_evidence", []) if _exact_evidence_id(x)
        ]
        confidence = float(hyp.get("confidence", -1))
        missing_info = hyp.get("missing_information", [])
        label = str(hyp.get("hypothesis_label", ""))
        entity_id = _exact_entity_id(hyp.get("entity_id"))

        def add(rule_id: str, rule_name: str, ok: bool, evidence: list[str], recommendation: str) -> None:
            nonlocal idx
            results.append(
                _result(
                    validation_id=f"val-{idx:05d}",
                    target_id=target_id,
                    rule_id=rule_id,
                    rule_name=rule_name,
                    status="pass" if ok else "fail",
                    severity="warning" if ok else "error",
                    evidence=evidence,
                    recommendation=None if ok else recommendation,
                )
            )
            idx += 1

        # 1) hypothesis_has_supporting_evidence
        add(
            "R1",
            "hypothesis_has_supporting_evidence",
            ok=len(supporting) > 0,
            evidence=supporting[:3],
            recommendation="Provide at least one supporting evidence reference.",
        )
        # 2) hypothesis_references_existing_entity
        add(
            "R2",
            "hypothesis_references_existing_entity",
            ok=entity_id in entity_ids,
            evidence=[entity_id] if entity_id else [],
            recommendation="Use an existing entity_id from entity outputs.",
        )
        # 3) hypothesis_references_existing_evidence
        all_refs = supporting + contradicting
        add(
            "R3",
            "hypothesis_references_existing_evidence",
            ok=all(ref in evidence_ids for ref in all_refs),
            evidence=all_refs[:5],
            recommendation="Ensure all evidence references exist in evidence_items.",
        )
        # 4) hypothesis_confidence_within_range
        add(
            "R4",
            "hypothesis_confidence_within_range",
            ok=0.0 <= confidence <= 1.0,
            evidence=[str(confidence)],
            recommendation="Set confidence within [0,1].",
        )
        # 5) hypothesis_has_no_forbidden_domain_terms
        add(
            "R5",
            "hypothesis_has_no_forbidden_domain_terms",
            ok=not _contains_forbidden(label),
            evidence=[label],
            recommendation="Use domain-agnostic labels and vocabulary.",
        )
        # 6) hypothesis_declares_no_final_truth
        add(
            "R6",
            "hypothesis_declares_no_final_truth",
            ok=not _contains_final_truth_claim(hyp),
            evidence=[hypothesis_id],
            recommendation="Remove final truth claims; keep hypothesis tentative.",
        )
        # 7) hypothesis_missing_information_declared_when_low_confidence
        low_conf = confidence < 0.5
        add(
            "R7",
            "hypothesis_missing_information_declared_when_low_confidence",
            ok=(not low_conf) or (isinstance(missing_info, list) and len(missing_info) > 0),
            evidence=[str(confidence)] + [str(x) for x in missing_info[:2]],
            recommendation="Declare missing_information when confidence is low.",
        )
        # 8) hypothesis_contradictions_are_explicit_when_present
        has_relation_evidence = any(
            isinstance(ev, dict) and ev.get("evidence_type") == "relation"
            for ev in evidence_items
            if _exact_evidence_id(ev.get("evidence_id")) in supporting
        )
        if has_relation_evidence:
            add(
                "R8",
                "hypothesis_contradictions_are_explicit_when_present",
                ok=isinstance(contradicting, list),
                evidence=contradicting[:3],
                recommendation="Declare contradicting_evidence list explicitly when relation evidence is present.",
            )
        else:
            results.append(
                _result(
                    validation_id=f"val-{idx:05d}",
                    target_id=target_id,
                    rule_id="R8",
                    rule_name="hypothesis_contradictions_are_explicit_when_present",
                    status="inconclusive",
                    severity="info",
                    evidence=[],
                    recommendation="No relation evidence context available.",
                    skipped_reason=None,
                )
            )
            idx += 1

    return {
        "mcp_name": "validation_engine",
        "role": "validation",
        "status": "ok",
        "message": f"Validated {len(hypotheses)} hypotheses with {len(results)} rule results.",
        "expected_input_contract": "hypothesis_schema.v1.json + evidence_schema.v1.json + entity_schema.v1.json + relations_schema.v1.json",
        "output_contract": "validation_schema.v1.json",
        "validation_results": results,
        "evaluated_hypothesis_count": len(hypotheses),
        "observed_relation_count": len(relations),
    }
