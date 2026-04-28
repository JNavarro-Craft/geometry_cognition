from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.evidence_graph.tools import build_evidence_graph  # noqa: E402
from gc_mcp.hypothesis_engine.tools import generate_hypotheses  # noqa: E402
from gc_mcp.reasoning_framework.execution_wrapper import run_reasoned_analysis  # noqa: E402
from gc_mcp.validation_engine.tools import validate_hypotheses  # noqa: E402


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


def _reasoning_stub(_prompt: str) -> dict[str, list[str]]:
    return {
        "observation": ["se observa actualizacion de relaciones verificadas"],
        "evidence": ["basado en evidence_items regenerados y resultados de validacion"],
        "inference": ["consistente con una mejora de certeza geometrica en relaciones confirmadas"],
        "conclusion": [],
    }


def main() -> None:
    outputs = PROJECT_ROOT / "outputs"

    geometry_features = _read_json(outputs / "geometry_features.json")
    entities = _read_json(outputs / "entities.json")
    relations_verified = _read_json(outputs / "relations_verified.json")

    previous_evidence_graph_path = outputs / "evidence_graph.json"
    previous_evidence_graph = _read_json(previous_evidence_graph_path) if previous_evidence_graph_path.exists() else None

    evidence_output = build_evidence_graph(
        {
            "objects": [],
            "geometry_features": geometry_features,
            "entities": entities,
            "relations": relations_verified,
        }
    )
    evidence_items = evidence_output.get("evidence_items", [])

    hypotheses_output = generate_hypotheses(
        {
            "evidence_items": evidence_items,
            "entities": entities,
            "relations": relations_verified,
        }
    )
    hypotheses = hypotheses_output.get("hypotheses", [])

    validation_output = validate_hypotheses(
        {
            "hypotheses": hypotheses,
            "evidence_items": evidence_items,
            "entities": entities,
            "relations": relations_verified,
        }
    )
    validation_results = validation_output.get("validation_results", [])

    verification_plan_path = outputs / "verification_plan.json"
    verification_plan = _normalize_verification_plan(_read_json(verification_plan_path)) if verification_plan_path.exists() else []

    reasoned = run_reasoned_analysis(
        {
            "relations": relations_verified,
            "evidence_items": evidence_items,
            "hypotheses": hypotheses,
            "verification_plan": verification_plan,
        },
        llm_callable=_reasoning_stub,
    )

    _write_json(outputs / "evidence_graph_verified.json", evidence_output)
    _write_json(outputs / "hypotheses_verified.json", hypotheses)
    _write_json(outputs / "validation_results_verified.json", validation_results)
    _write_json(outputs / "reasoned_analysis_verified.json", reasoned)

    confirmed_relations = sum(
        1
        for r in relations_verified
        if isinstance(r, dict) and str(r.get("assertion_level", "")) == "confirmed"
    )
    hypotheses_without_missing = sum(
        1 for h in hypotheses if isinstance(h, dict) and len(h.get("missing_information", [])) == 0
    )
    pass_count = sum(1 for r in validation_results if isinstance(r, dict) and str(r.get("status", "")) == "pass")
    fail_count = sum(1 for r in validation_results if isinstance(r, dict) and str(r.get("status", "")) == "fail")

    analysis = reasoned.get("analysis", {}) if isinstance(reasoned, dict) else {}
    conclusion_count = len(analysis.get("conclusion", [])) if isinstance(analysis, dict) else 0

    print(f"relations_total: {len(relations_verified) if isinstance(relations_verified, list) else 0}")
    print(f"confirmed_relations: {confirmed_relations}")
    print(f"hypotheses_total: {len(hypotheses) if isinstance(hypotheses, list) else 0}")
    print(f"hypotheses_without_missing_information: {hypotheses_without_missing}")
    print(f"validation_pass_count: {pass_count}")
    print(f"validation_fail_count: {fail_count}")
    print(f"reasoning_conclusion_count: {conclusion_count}")
    if isinstance(previous_evidence_graph, dict):
        prev_count = len(previous_evidence_graph.get("evidence_items", []))
        print(f"previous_evidence_items_count: {prev_count}")


if __name__ == "__main__":
    main()

