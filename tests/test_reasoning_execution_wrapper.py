from pathlib import Path

from gc_mcp.reasoning_framework import execution_wrapper as ew


def test_wrapper_injects_rules_automatically_and_returns_structured_levels():
    captured = {"prompt": ""}

    def fake_llm(prompt: str):
        captured["prompt"] = prompt
        return {
            "observation": ["se observa una relacion candidata"],
            "evidence": ["basado en ev-rel-rel-001"],
            "inference": ["podria indicar interaccion pendiente de verificacion"],
            "conclusion": [],
        }

    out = ew.run_reasoned_analysis(
        {
            "relations": [{"relation_id": "rel-001", "assertion_level": "candidate"}],
            "evidence_items": [{"evidence_id": "ev-rel-rel-001"}],
            "hypotheses": [],
            "verification_plan": [],
        },
        llm_callable=fake_llm,
    )

    assert out["status"] == "ok"
    assert set(out["analysis"].keys()) == {"observation", "evidence", "inference", "conclusion"}
    assert "Reasoning Framework Rules" in captured["prompt"]
    assert "Observation" in captured["prompt"]
    assert "Conclusion" in captured["prompt"]
    # rules are auto-loaded from file; caller did not provide rules text
    assert "Toda afirmacion debe indicar explicitamente su nivel" in captured["prompt"]


def test_wrapper_returns_clear_error_when_rules_file_missing(monkeypatch):
    monkeypatch.setattr(ew, "RULES_PATH", Path("C:/geometry_cognition/no_rules_here.md"))

    out = ew.run_reasoned_analysis(
        {"relations": [], "evidence_items": [], "hypotheses": [], "verification_plan": []},
        llm_callable=lambda _prompt: {},
    )

    assert out["status"] == "error"
    assert "reasoning rules file not found" in out["message"]

