from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


RULES_PATH = Path(__file__).resolve().parent / "reasoning_rules.md"


def _build_reasoning_prompt(payload: dict[str, Any], rules_text: str) -> str:
    return (
        "You are running a geometry_cognition reasoned analysis.\n"
        "Apply the provided Reasoning Framework strictly.\n\n"
        "Requirements:\n"
        "- Use levels: Observation, Evidence, Inference, Conclusion.\n"
        "- Do not assert claims without evidence references.\n"
        "- Do not escalate to Conclusion unless assertion_level=confirmed.\n"
        "- Keep language conservative and traceable.\n\n"
        "Return ONLY valid JSON with this shape:\n"
        '{\n'
        '  "observation": [string],\n'
        '  "evidence": [string],\n'
        '  "inference": [string],\n'
        '  "conclusion": [string]\n'
        "}\n\n"
        "Reasoning Framework Rules:\n"
        f"{rules_text}\n\n"
        "Analysis Input:\n"
        f"{json.dumps(payload, ensure_ascii=True, indent=2)}"
    )


def _normalize_llm_output(raw: Any) -> dict[str, list[str]]:
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        data = json.loads(raw)
    else:
        raise ValueError("llm output must be dict or JSON string")

    out: dict[str, list[str]] = {}
    for key in ("observation", "evidence", "inference", "conclusion"):
        value = data.get(key, [])
        if isinstance(value, list):
            out[key] = [str(x) for x in value]
        elif value is None:
            out[key] = []
        else:
            out[key] = [str(value)]
    return out


def run_reasoned_analysis(
    payload: dict[str, Any],
    llm_callable: Callable[[str], dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    """
    Opt-in wrapper for geometry_cognition reasoning discipline.
    It does not modify global behavior and only runs when explicitly called.
    """
    if not RULES_PATH.exists():
        return {
            "status": "error",
            "message": f"reasoning rules file not found: {RULES_PATH}",
            "analysis": None,
        }

    if llm_callable is None:
        return {
            "status": "error",
            "message": "llm_callable is required for run_reasoned_analysis",
            "analysis": None,
        }

    rules_text = RULES_PATH.read_text(encoding="utf-8")
    prompt = _build_reasoning_prompt(payload, rules_text)
    raw = llm_callable(prompt)
    analysis = _normalize_llm_output(raw)

    return {
        "status": "ok",
        "message": "reasoned analysis generated with framework injection",
        "analysis": analysis,
        "framework_source": str(RULES_PATH),
    }


if __name__ == "__main__":
    # Example usage (opt-in):
    sample_payload = {
        "relations": [],
        "evidence_items": [],
        "hypotheses": [],
        "verification_plan": [],
    }

    def _demo_llm(_prompt: str) -> dict[str, list[str]]:
        return {
            "observation": ["se observa informacion relacional disponible"],
            "evidence": ["basado en evidencia de entrada"],
            "inference": ["consistente con un patron tentativo"],
            "conclusion": [],
        }

    print(json.dumps(run_reasoned_analysis(sample_payload, llm_callable=_demo_llm), indent=2))

