from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.reader_server.tools import (
    get_analysis_summary,
    get_confirmed_relations,
    get_evidence_for_relation,
    get_object_details,
    get_objects,
    get_reasoning_output,
    get_relations_for_object,
)


def _print(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=True))


def main() -> None:
    _print("get_analysis_summary", get_analysis_summary())
    objs = get_objects(limit=5)
    _print("get_objects(limit=5)", objs)

    first_object_id = None
    if isinstance(objs, dict):
        rows = objs.get("objects", [])
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            first_object_id = str(rows[0].get("object_id", ""))

    if first_object_id:
        _print(f"get_object_details({first_object_id})", get_object_details(first_object_id))
        _print(f"get_relations_for_object({first_object_id})", get_relations_for_object(first_object_id))
        _print(
            f"get_relations_for_object({first_object_id}, assertion_level='confirmed')",
            get_relations_for_object(first_object_id, assertion_level="confirmed"),
        )
    else:
        print("\nNo objects available to test object-specific tools.")

    confirmed = get_confirmed_relations()
    _print("get_confirmed_relations()", confirmed)
    _print("get_confirmed_relations(predicate='intersects')", get_confirmed_relations(predicate="intersects"))

    first_relation_id = None
    if isinstance(confirmed, dict):
        rels = confirmed.get("relations", [])
        if isinstance(rels, list) and rels and isinstance(rels[0], dict):
            first_relation_id = str(rels[0].get("relation_id", ""))
    if first_relation_id:
        _print(
            f"get_evidence_for_relation({first_relation_id})",
            get_evidence_for_relation(first_relation_id),
        )
    else:
        print("\nNo confirmed relations available to test get_evidence_for_relation.")

    _print("get_reasoning_output()", get_reasoning_output())


if __name__ == "__main__":
    main()

