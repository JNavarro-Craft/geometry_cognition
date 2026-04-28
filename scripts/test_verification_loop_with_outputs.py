from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.verification_executor.tools import execute_verification_plan  # noqa: E402
from gc_mcp.verification_planner.tools import plan_verifications  # noqa: E402


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _normalize_verification_plan(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        plan = raw.get("verification_plan", [])
        if isinstance(plan, list):
            return [x for x in plan if isinstance(x, dict)]
    return []


def _extract_evidence_items(evidence_graph_payload: Any) -> list[dict[str, Any]]:
    if isinstance(evidence_graph_payload, dict):
        items = evidence_graph_payload.get("evidence_items", [])
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        return []
    if isinstance(evidence_graph_payload, list):
        return [x for x in evidence_graph_payload if isinstance(x, dict)]
    return []


def main() -> None:
    outputs_dir = PROJECT_ROOT / "outputs"
    relations = _read_json(outputs_dir / "relations.json")
    evidence_graph = _read_json(outputs_dir / "evidence_graph.json")
    hypotheses = _read_json(outputs_dir / "hypotheses.json")

    if not isinstance(relations, list):
        raise RuntimeError("outputs/relations.json must contain a list.")
    if not isinstance(hypotheses, list):
        raise RuntimeError("outputs/hypotheses.json must contain a list.")
    evidence_items = _extract_evidence_items(evidence_graph)

    verification_plan_path = outputs_dir / "verification_plan.json"
    verification_plan_file_exists = verification_plan_path.exists()
    computed_verification_plan_count = 0
    format_mismatch = False
    if verification_plan_file_exists:
        verification_plan = _normalize_verification_plan(_read_json(verification_plan_path))
    else:
        planned = plan_verifications(
            {
                "relations": relations,
                "hypotheses": hypotheses,
                "evidence_items": evidence_items,
            }
        )
        if not isinstance(planned, dict) or "verification_plan" not in planned:
            format_mismatch = True
        verification_plan = _normalize_verification_plan(planned)
        computed_verification_plan_count = len(verification_plan)

    selected_plan_count = min(len(verification_plan), 3)
    print(f"relations_count: {len(relations)}")
    print(f"evidence_items_count: {len(evidence_items)}")
    print(f"hypotheses_count: {len(hypotheses)}")
    print(f"verification_plan_file_exists: {verification_plan_file_exists}")
    print(f"computed_verification_plan_count: {computed_verification_plan_count}")
    print(f"selected_plan_count: {selected_plan_count}")

    if len(verification_plan) == 0:
        reasons: list[str] = []
        if not any(str(r.get("assertion_level", "")) == "candidate" for r in relations if isinstance(r, dict)):
            reasons.append("no_candidate_relations")
        if not any(
            isinstance(r, dict) and isinstance(r.get("verification_required"), list) and len(r.get("verification_required", [])) > 0
            for r in relations
        ):
            reasons.append("no_verification_required")
        if len(evidence_items) == 0:
            reasons.append("missing_evidence_items")
        if len(hypotheses) == 0:
            reasons.append("missing_hypotheses")
        if format_mismatch:
            reasons.append("format_mismatch")
        print(f"empty_plan_reason: {','.join(reasons) if reasons else 'unknown'}")

    execution = execute_verification_plan(
        {
            "verification_plan": verification_plan,
            "relations": relations,
            "bridge_base_url": "http://127.0.0.1:8765",
            "max_items": 3,
            "linear_tolerance": 0.05,
            "angular_tolerance": 2.0,
        }
    )

    verification_results = execution.get("verification_results", [])
    updated_relations = execution.get("updated_relations", [])
    if not isinstance(verification_results, list):
        verification_results = []
    if not isinstance(updated_relations, list):
        updated_relations = []

    _write_json(outputs_dir / "verification_results.json", verification_results)
    _write_json(outputs_dir / "relations_verified.json", updated_relations)

    confirmed = 0
    contradicted = 0
    inconclusive = 0
    updated_ids: list[str] = []
    for rel in updated_relations:
        if not isinstance(rel, dict):
            continue
        rid = str(rel.get("relation_id", ""))
        if "verification_result" in rel and rid:
            updated_ids.append(rid)
        status = str(rel.get("verification_status", ""))
        if status == "verified":
            confirmed += 1
        elif status == "contradicted":
            contradicted += 1
        elif status == "inconclusive":
            inconclusive += 1

    print(f"execution_status: {execution.get('status', 'unknown')}")
    if execution.get("status") == "error":
        print(f"execution_error: {execution.get('message', '')}")
    print(f"executed: {int(execution.get('executed', 0))}")
    print(f"confirmed: {confirmed}")
    print(f"contradicted: {contradicted}")
    print(f"inconclusive: {inconclusive}")
    print(f"top updated relation_ids: {updated_ids[:10]}")


if __name__ == "__main__":
    main()

