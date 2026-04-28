from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.reasoning_framework.execution_wrapper import run_reasoned_analysis  # noqa: E402
from gc_mcp.verification_planner.tools import plan_verifications  # noqa: E402


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_verification_plan(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        plan = raw.get("verification_plan", [])
        if isinstance(plan, list):
            return [x for x in plan if isinstance(x, dict)]
    return []


def build_payload_from_outputs(outputs_dir: Path) -> tuple[dict[str, Any], str]:
    relations_path = outputs_dir / "relations.json"
    evidence_graph_path = outputs_dir / "evidence_graph.json"
    hypotheses_path = outputs_dir / "hypotheses.json"
    verification_plan_path = outputs_dir / "verification_plan.json"

    relations = _read_json(relations_path)
    evidence_graph = _read_json(evidence_graph_path)
    hypotheses = _read_json(hypotheses_path)
    evidence_items = evidence_graph.get("evidence_items", []) if isinstance(evidence_graph, dict) else []

    if verification_plan_path.exists():
        verification_plan = _normalize_verification_plan(_read_json(verification_plan_path))
        plan_source = "outputs/verification_plan.json"
    else:
        planned = plan_verifications(
            {
                "relations": relations if isinstance(relations, list) else [],
                "hypotheses": hypotheses if isinstance(hypotheses, list) else [],
                "evidence_items": evidence_items if isinstance(evidence_items, list) else [],
            }
        )
        verification_plan = _normalize_verification_plan(planned)
        plan_source = "computed_with_verification_planner"

    payload = {
        "relations": relations,
        "evidence_items": evidence_items,
        "hypotheses": hypotheses,
        "verification_plan": verification_plan,
    }
    return payload, plan_source


def real_llm(prompt: str, print_prompt_only: bool = False) -> dict[str, list[str]] | str:
    """
    Stub manual para futura integracion con Claude API.
    No ejecuta llamadas externas automaticamente.
    """
    print("\n===== BEGIN GENERATED PROMPT =====\n")
    print(prompt)
    print("\n===== END GENERATED PROMPT =====\n")

    if print_prompt_only:
        raise SystemExit(0)

    print("Modo manual: pega JSON valido con keys observation/evidence/inference/conclusion")
    print("O presiona Enter para usar respuesta simulada por defecto.")
    user_input = input("> ").strip()
    if user_input:
        return user_input

    return {
        "observation": ["se observa informacion relacional del pipeline"],
        "evidence": ["basado en evidence_items y hypotheses disponibles"],
        "inference": ["podria indicar interacciones candidatas pendientes de verificacion"],
        "conclusion": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reasoned analysis with manual LLM stub.")
    parser.add_argument(
        "--print-prompt-only",
        action="store_true",
        help="Generate and print wrapper prompt only, then exit.",
    )
    args = parser.parse_args()

    outputs_dir = PROJECT_ROOT / "outputs"
    payload, plan_source = build_payload_from_outputs(outputs_dir)
    print(f"verification_plan_items: {len(payload.get('verification_plan', []))}")
    print(f"verification_plan_source: {plan_source}")

    def _llm(prompt: str) -> dict[str, list[str]] | str:
        return real_llm(prompt, print_prompt_only=args.print_prompt_only)

    result = run_reasoned_analysis(payload, llm_callable=_llm)
    if args.print_prompt_only:
        return

    print("\n===== REASONED ANALYSIS RESULT =====\n")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

