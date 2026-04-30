from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.geometry_kernel.tools import compute_geometry_features
from gc_mcp.rhino_extractor.tools import extract_objects
from shared.contracts import validate_payload


def _load_input(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".json", ".3dm"}:
        return {"input_path": str(path)}
    raise ValueError("Input must be a .json fixture or .3dm Rhino model.")


def _is_bridge_mode() -> bool:
    return str(os.environ.get("GC_BACKEND_MODE", "")).strip().lower() == "bridge"


def _validate_outputs(result: dict[str, Any]) -> None:
    for obj in result.get("objects", []):
        validate_payload("object_schema.v1.json", obj)
    for geom in result.get("geometry_features", []):
        validate_payload("geometry_schema.v2.json", geom)
    for ent in result.get("entities", []):
        validate_payload("entity_schema.v1.json", ent)
    for rel in result.get("relations", []):
        validate_payload("relations_schema.v2.json", rel)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run(
    input_path: Path | None,
    output_dir: Path,
) -> dict[str, Any]:
    """
    Deterministic stage order:
    rhino_extractor → geometry_kernel
    """
    bridge_mode = _is_bridge_mode()
    if bridge_mode:
        # Bridge mode reads objects from the Rhino bridge endpoint and does not require input_path.
        extractor_payload: dict[str, Any] = {}
    else:
        if input_path is None:
            raise ValueError("input_path is required in local mode (use .json or .3dm).")
        extractor_payload = _load_input(input_path)

    extractor_output = extract_objects(extractor_payload)
    if str(extractor_output.get("status", "")).lower() != "ok":
        msg = extractor_output.get("message", "extract_objects failed")
        input_label = str(input_path) if input_path is not None else "<bridge-mode-no-input>"
        raise RuntimeError(
            f"rhino_extractor did not return ok: {msg}. input_path was {input_label}."
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

    _validate_outputs(merged)

    _write_json(output_dir / "objects.json", merged["objects"])
    _write_json(output_dir / "geometry_features.json", merged["geometry_features"])
    _write_json(output_dir / "entities.json", merged["entities"])
    _write_json(output_dir / "relations.json", merged["relations"])
    _write_json(output_dir / "minimal_analysis_bundle.json", merged)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Run minimal geometry_cognition analysis.")
    parser.add_argument(
        "input_path",
        nargs="?",
        default=None,
        help="Path to Rhino .3dm/.json in local mode; optional in bridge mode.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for generated outputs (default: outputs).",
    )
    args = parser.parse_args()

    input_path: Path | None = Path(args.input_path) if args.input_path else None
    bundle = run(input_path, Path(args.output_dir))
    print(
        json.dumps(
            {
                "status": "ok",
                "objects": len(bundle["objects"]),
                "geometry_features": len(bundle["geometry_features"]),
                "entities": len(bundle["entities"]),
                "relations": len(bundle["relations"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
