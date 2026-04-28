from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.contracts import validate_payload


FORBIDDEN_TERMS = {"beam", "panel", "truss", "sip", "connector"}
ALLOWED_PREFIXES = ("compatible_with_", "suggests_")
ALLOWED_EXACT_LABELS = {"requires_human_review", "no_domain_mapping_available", "observed_structural_pattern"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_interpretation_rules(profile: str) -> list[dict[str, Any]]:
    rules_path = _project_root() / "domain_profiles" / profile / "interpretation_rules.json"
    if not rules_path.exists():
        return []
    with rules_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", [])


def _is_allowed_label(label: str) -> bool:
    lowered = label.lower()
    if any(term in lowered for term in FORBIDDEN_TERMS):
        return False
    return lowered.startswith(ALLOWED_PREFIXES) or lowered in ALLOWED_EXACT_LABELS


def _fallback_interpretation(
    *,
    idx: int,
    hypothesis: dict[str, Any],
    profile: str,
    reason: str,
) -> dict[str, Any]:
    hypothesis_id = str(hypothesis.get("hypothesis_id", ""))
    confidence = float(hypothesis.get("confidence", 0.0))
    supporting = [str(x) for x in hypothesis.get("supporting_evidence", [])]

    low_or_missing_evidence = confidence < 0.5 or len(supporting) == 0
    if low_or_missing_evidence:
        interpretation_label = "requires_human_review"
        status = "weak"
        limitations = [
            reason,
            "low confidence or missing supporting evidence",
            "requires human review before downstream decisions",
        ]
    else:
        interpretation_label = "no_domain_mapping_available"
        status = "unsupported"
        limitations = [
            "no matching domain interpretation rule",
            "requires human review before downstream decisions",
        ]

    interpretation = {
        "interpretation_id": f"int-{idx:04d}",
        "entity_id": str(hypothesis.get("entity_id", "")),
        "domain": profile,
        "interpretation_label": interpretation_label,
        "confidence": max(0.0, min(1.0, confidence)),
        "supporting_evidence": supporting,
        "derived_from_hypotheses": [hypothesis_id],
        "limitations": limitations,
        "status": status,
    }
    validate_payload("domain_interpretation_schema.v1.json", interpretation)
    return interpretation


def generate_domain_interpretations(payload: dict[str, Any], profile: str = "prefab") -> dict[str, Any]:
    hypotheses = payload.get("hypotheses", [])
    rules = _load_interpretation_rules(profile)

    # Conservative filter: ignore high-risk mappings.
    active_map = {
        rule["hypothesis_label"]: rule
        for rule in rules
        if str(rule.get("contamination_risk", "")).lower() != "high"
    }

    interpretations: list[dict[str, Any]] = []
    fallback_hypotheses: list[str] = []
    idx = 1
    for hyp in hypotheses:
        hypothesis_id = str(hyp.get("hypothesis_id", ""))
        label = str(hyp.get("hypothesis_label", ""))
        confidence = float(hyp.get("confidence", 0.0))
        supporting = [str(x) for x in hyp.get("supporting_evidence", [])]
        mapping = active_map.get(label)
        # Minimal activation path: ambiguous + enough confidence + evidence.
        if label == "ambiguous_entity" and confidence >= 0.5 and len(supporting) > 0:
            interpretation = {
                "interpretation_id": f"int-{idx:04d}",
                "entity_id": str(hyp.get("entity_id", "")),
                "domain": profile,
                "interpretation_label": "observed_structural_pattern",
                "confidence": max(0.0, min(1.0, confidence)),
                "supporting_evidence": supporting,
                "derived_from_hypotheses": [hypothesis_id],
                "limitations": [
                    "consistent geometric pattern observed with stable relational evidence; domain mapping not available",
                    "requires human review before downstream decisions",
                ],
                "status": "weak",
            }
            validate_payload("domain_interpretation_schema.v1.json", interpretation)
            interpretations.append(interpretation)
            idx += 1
            continue
        if not mapping:
            interpretations.append(
                _fallback_interpretation(
                    idx=idx,
                    hypothesis=hyp,
                    profile=profile,
                    reason="no matching domain interpretation rule",
                )
            )
            fallback_hypotheses.append(hypothesis_id)
            idx += 1
            continue

        interpretation_label = str(mapping.get("interpretation_label", ""))
        if not _is_allowed_label(interpretation_label):
            interpretations.append(
                _fallback_interpretation(
                    idx=idx,
                    hypothesis=hyp,
                    profile=profile,
                    reason="mapping produced disallowed interpretation label",
                )
            )
            fallback_hypotheses.append(hypothesis_id)
            idx += 1
            continue

        confidence_multiplier = float(mapping.get("confidence_multiplier", 0.8))
        confidence = max(0.0, min(1.0, float(hyp.get("confidence", 0.0)) * confidence_multiplier))

        interpretation = {
            "interpretation_id": f"int-{idx:04d}",
            "entity_id": str(hyp.get("entity_id", "")),
            "domain": profile,
            "interpretation_label": interpretation_label,
            "confidence": confidence,
            "supporting_evidence": [str(x) for x in hyp.get("supporting_evidence", [])],
            "derived_from_hypotheses": [hypothesis_id],
            "limitations": [
                "domain interpretation is conservative and non-definitive",
                "requires human review before downstream decisions",
            ],
            "status": str(mapping.get("interpretation_status", "tentative")),
        }
        validate_payload("domain_interpretation_schema.v1.json", interpretation)
        interpretations.append(interpretation)
        idx += 1

    return {
        "mcp_name": "domain_interpreter",
        "role": "domain_interpretation",
        "status": "ok",
        "message": (
            f"Generated {len(interpretations)} domain interpretations "
            f"({len(fallback_hypotheses)} fallback)."
        ),
        "expected_input_contract": "hypothesis_schema.v1.json + domain_profiles/<profile>/interpretation_rules.json",
        "output_contract": "domain_interpretation_schema.v1.json",
        "domain_interpretations": interpretations,
        "skipped_hypotheses": [],
        "fallback_hypotheses": fallback_hypotheses,
    }
