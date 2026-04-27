from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.hypothesis_engine.tools import generate_hypotheses

logger = logging.getLogger(__name__)

mcp = FastMCP("hypothesis_engine")


def _normalize_generate_hypotheses_args(
    *,
    entities: list[Any] | None = None,
    evidence_items: list[Any] | None = None,
    relations: list[Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    MCP may send a flat tool JSON ``{entities, evidence_items, relations}``.
    A single ``payload`` parameter forces nesting; merge both shapes like rhino_extractor.
    """
    merged: dict[str, Any] = {}
    if isinstance(payload, dict):
        merged.update(payload)
    if entities is not None:
        merged["entities"] = entities
    if evidence_items is not None:
        merged["evidence_items"] = evidence_items
    if relations is not None:
        merged["relations"] = relations
    logger.info(
        "hypothesis_engine MCP: merged keys=%s entity_count=%s evidence_count=%s relation_count=%s",
        sorted(merged.keys()),
        len(merged.get("entities") or []),
        len(merged.get("evidence_items") or []),
        len(merged.get("relations") or []),
    )
    return merged


@mcp.tool(name="generate_hypotheses")
def generate_hypotheses_tool(
    entities: list[Any] | None = None,
    evidence_items: list[Any] | None = None,
    relations: list[Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build hypotheses from evidence_graph outputs (include relations to attach ev-rel-*)."""
    return generate_hypotheses(
        _normalize_generate_hypotheses_args(
            entities=entities,
            evidence_items=evidence_items,
            relations=relations,
            payload=payload,
        )
    )


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
