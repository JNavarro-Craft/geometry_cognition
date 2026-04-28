from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.reasoning_framework.execution_wrapper import run_reasoned_analysis  # noqa: E402


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    outputs_dir = PROJECT_ROOT / "outputs"
    relations_path = outputs_dir / "relations.json"
    evidence_graph_path = outputs_dir / "evidence_graph.json"
    hypotheses_path = outputs_dir / "hypotheses.json"
    verification_plan_path = outputs_dir / "verification_plan.json"

    relations = _read_json(relations_path)
    evidence_graph = _read_json(evidence_graph_path)
    hypotheses = _read_json(hypotheses_path)
    verification_plan = _read_json(verification_plan_path) if verification_plan_path.exists() else []

    evidence_items = evidence_graph.get("evidence_items", []) if isinstance(evidence_graph, dict) else []
    prompt_checks = {"framework_present": False, "levels_present": False}

    def fake_llm(prompt: str) -> dict[str, list[str]]:
        has_framework = "Reasoning Framework" in prompt
        has_levels = all(level in prompt for level in ("Observation", "Evidence", "Inference", "Conclusion"))
        prompt_checks["framework_present"] = has_framework
        prompt_checks["levels_present"] = has_levels
        if not has_framework:
            raise ValueError("Prompt does not include Reasoning Framework")
        if not has_levels:
            raise ValueError("Prompt does not include required reasoning levels")
        return {
            "observation": ["se observa evidencia relacional disponible"],
            "evidence": ["basado en ev-rel y ev-geom del pipeline"],
            "inference": ["consistente con patrones candidatos pendientes de verificacion"],
            "conclusion": [],
        }

    payload = {
        "relations": relations,
        "evidence_items": evidence_items,
        "hypotheses": hypotheses,
        "verification_plan": verification_plan,
    }
    result = run_reasoned_analysis(payload, llm_callable=fake_llm)

    print(f"relations: {len(relations) if isinstance(relations, list) else 0}")
    print(f"evidence_items: {len(evidence_items) if isinstance(evidence_items, list) else 0}")
    print(f"hypotheses: {len(hypotheses) if isinstance(hypotheses, list) else 0}")
    print(f"reasoning_rules_injected: {prompt_checks['framework_present'] and prompt_checks['levels_present']}")
    print(f"framework_source: {result.get('framework_source')}")
    print("analysis result:")
    print(json.dumps(result.get("analysis"), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

