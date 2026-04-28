from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.evidence_graph.tools import build_evidence_graph
from gc_mcp.hypothesis_engine.tools import generate_hypotheses
from gc_mcp.domain_interpreter.tools import generate_domain_interpretations
from gc_mcp.validation_engine.tools import validate_hypotheses
from gc_mcp.rhino_extractor.tools import extract_objects
from shared.contracts import validate_payload


def _build_validation_summary(validation_results: list[dict[str, Any]]) -> dict[str, Any]:
    severity_order = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    summary = {
        "total": len(validation_results),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "inconclusive": 0,
        "by_rule": {},
        "highest_severity": "info",
    }
    highest = 0
    for item in validation_results:
        status = str(item.get("status", "inconclusive"))
        if status == "pass":
            summary["passed"] += 1
        elif status == "fail":
            summary["failed"] += 1
        elif status == "skipped":
            summary["skipped"] += 1
        else:
            summary["inconclusive"] += 1

        rule_name = str(item.get("rule_name", "unknown_rule"))
        rule_bucket = summary["by_rule"].setdefault(
            rule_name,
            {"total": 0, "pass": 0, "fail": 0, "skipped": 0, "inconclusive": 0},
        )
        rule_bucket["total"] += 1
        if status in rule_bucket:
            rule_bucket[status] += 1
        else:
            rule_bucket["inconclusive"] += 1

        sev = str(item.get("severity", "info"))
        sev_rank = severity_order.get(sev, 0)
        if sev_rank > highest:
            highest = sev_rank
            summary["highest_severity"] = sev
    return summary


def _load_input(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".json", ".3dm"}:
        return {"input_path": str(path)}
    raise ValueError("Input must be a .json fixture or .3dm Rhino model.")


def _validate_outputs(result: dict[str, Any]) -> None:
    for obj in result.get("objects", []):
        validate_payload("object_schema.v1.json", obj)
    for geom in result.get("geometry_features", []):
        validate_payload("geometry_schema.v2.json", geom)
    for ent in result.get("entities", []):
        validate_payload("entity_schema.v1.json", ent)
    for rel in result.get("relations", []):
        validate_payload("relations_schema.v1.json", rel)
    for item in result.get("evidence_items", []):
        validate_payload("evidence_schema.v1.json", item)
    for item in result.get("hypotheses", []):
        validate_payload("hypothesis_schema.v1.json", item)
    for item in result.get("validation_results", []):
        validate_payload("validation_schema.v1.json", item)
    for item in result.get("domain_interpretations", []):
        validate_payload("domain_interpretation_schema.v1.json", item)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run(
    input_path: Path,
    output_dir: Path,
    include_evidence_graph: bool = False,
    include_hypotheses: bool = False,
    include_validation: bool = False,
    include_domain: bool = False,
) -> dict[str, Any]:
    """
    Deterministic stage order (conceptual, matches dependency chain):
    rhino_extractor → geometry_kernel → evidence_graph → hypothesis_engine
    → validation_engine → domain_interpreter (optional flags gate later stages; domain implies validation+hypotheses+evidence in memory).
    """
    extractor_output = extract_objects(_load_input(input_path))
    if str(extractor_output.get("status", "")).lower() != "ok":
        msg = extractor_output.get("message", "extract_objects failed")
        raise RuntimeError(
            f"rhino_extractor did not return ok: {msg}. input_path was {input_path!s}."
        )
    if "objects" not in extractor_output or not isinstance(extractor_output.get("objects"), list):
        raise RuntimeError("rhino_extractor response missing a list objects key.")
    kernel_output = compute_geometry_features({"objects": extractor_output["objects"]})

    merged = {
        "objects": extractor_output["objects"],
        "geometry_features": kernel_output["geometry_features"],
        "entities": kernel_output["entities"],
        "relations": kernel_output["relations"],
    }

    if include_evidence_graph or include_hypotheses or include_validation or include_domain:
        evidence_output = build_evidence_graph(
            {
                "objects": merged["objects"],
                "geometry_features": merged["geometry_features"],
                "entities": merged["entities"],
                "relations": merged["relations"],
            }
        )
        merged["evidence_graph"] = {
            "nodes": evidence_output["nodes"],
            "edges": evidence_output["edges"],
        }
        merged["evidence_items"] = evidence_output["evidence_items"]

    if include_hypotheses or include_validation or include_domain:
        hypotheses_output = generate_hypotheses(
            {
                "evidence_items": merged.get("evidence_items", []),
                "entities": merged["entities"],
                "relations": merged.get("relations", []),
            }
        )
        merged["hypotheses"] = hypotheses_output["hypotheses"]

    if include_validation or include_domain:
        validation_output = validate_hypotheses(
            {
                "hypotheses": merged.get("hypotheses", []),
                "evidence_items": merged.get("evidence_items", []),
                "entities": merged["entities"],
                "relations": merged["relations"],
            }
        )
        merged["validation_results"] = validation_output["validation_results"]
        merged["validation_summary"] = _build_validation_summary(merged["validation_results"])

    if include_domain:
        domain_output = generate_domain_interpretations(
            {"hypotheses": merged.get("hypotheses", [])},
            profile="prefab",
        )
        merged["domain_interpretations"] = domain_output["domain_interpretations"]

    _validate_outputs(merged)

    _write_json(output_dir / "objects.json", merged["objects"])
    _write_json(output_dir / "geometry_features.json", merged["geometry_features"])
    _write_json(output_dir / "entities.json", merged["entities"])
    _write_json(output_dir / "relations.json", merged["relations"])
    if include_evidence_graph or include_hypotheses or include_validation or include_domain:
        _write_json(
            output_dir / "evidence_graph.json",
            {
                "nodes": merged["evidence_graph"]["nodes"],
                "edges": merged["evidence_graph"]["edges"],
                "evidence_items": merged["evidence_items"],
            },
        )
    if include_hypotheses or include_validation or include_domain:
        _write_json(output_dir / "hypotheses.json", merged["hypotheses"])
    if include_validation or include_domain:
        _write_json(output_dir / "validation_results.json", merged["validation_results"])
    if include_domain:
        _write_json(output_dir / "domain_interpretations.json", merged["domain_interpretations"])
    _write_json(output_dir / "minimal_analysis_bundle.json", merged)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Run minimal geometry_cognition analysis.")
    parser.add_argument("input_path", help="Path to Rhino .3dm file or JSON fixture.")
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for generated outputs (default: outputs).",
    )
    parser.add_argument(
        "--include-evidence-graph",
        action="store_true",
        help="Include evidence_graph stage and save evidence_graph.json.",
    )
    parser.add_argument(
        "--include-hypotheses",
        action="store_true",
        help="Include hypothesis_engine stage and save hypotheses.json.",
    )
    parser.add_argument(
        "--include-validation",
        action="store_true",
        help="Include validation_engine stage and save validation_results.json.",
    )
    parser.add_argument(
        "--include-domain",
        action="store_true",
        help="Include domain_interpreter stage and save domain_interpretations.json.",
    )
    args = parser.parse_args()

    bundle = run(
        Path(args.input_path),
        Path(args.output_dir),
        include_evidence_graph=args.include_evidence_graph,
        include_hypotheses=args.include_hypotheses,
        include_validation=args.include_validation,
        include_domain=args.include_domain,
    )
    evidence_count = len(bundle.get("evidence_items", []))
    hypotheses_count = len(bundle.get("hypotheses", []))
    validation_count = len(bundle.get("validation_results", []))
    domain_count = len(bundle.get("domain_interpretations", []))
    print(
        json.dumps(
            {
                "status": "ok",
                "objects": len(bundle["objects"]),
                "geometry_features": len(bundle["geometry_features"]),
                "entities": len(bundle["entities"]),
                "relations": len(bundle["relations"]),
                "evidence_items": evidence_count,
                "hypotheses": hypotheses_count,
                "validation_results": validation_count,
                "domain_interpretations": domain_count,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
