from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.contracts import validate_payload


FORBIDDEN_TERMS = {"beam", "panel", "truss", "sip", "connector"}
ALLOWED_PREFIXES = ("compatible_with_", "suggests_", "requires_human_review")


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
    return lowered.startswith(ALLOWED_PREFIXES)


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
    skipped_hypotheses: list[str] = []
    idx = 1
    for hyp in hypotheses:
        hypothesis_id = str(hyp.get("hypothesis_id", ""))
        label = str(hyp.get("hypothesis_label", ""))
        mapping = active_map.get(label)
        if not mapping:
            skipped_hypotheses.append(hypothesis_id)
            continue

        interpretation_label = str(mapping.get("interpretation_label", ""))
        if not _is_allowed_label(interpretation_label):
            skipped_hypotheses.append(hypothesis_id)
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
        "message": f"Generated {len(interpretations)} domain interpretations.",
        "expected_input_contract": "hypothesis_schema.v1.json + domain_profiles/<profile>/interpretation_rules.json",
        "output_contract": "domain_interpretation_schema.v1.json",
        "domain_interpretations": interpretations,
        "skipped_hypotheses": skipped_hypotheses,
    }
