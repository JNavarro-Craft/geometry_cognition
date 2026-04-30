from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.reader_server.tools import (
    find_orphans,
    get_analysis_summary,
    get_confirmed_relations,
    get_evidence_for_relation,
    get_groups,
    get_inventory_summary,
    get_layers,
    get_object_details,
    get_objects,
    get_objects_by_group,
    get_objects_by_layer,
    get_objects_by_user_text,
    get_reasoning_output,
    get_relations_for_object,
    get_user_text_keys_summary,
)


def _print(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=True))


def main() -> None:
    _print("get_analysis_summary", get_analysis_summary())
    _print("get_inventory_summary", get_inventory_summary())
    layers = get_layers()
    _print("get_layers()", layers)
    groups = get_groups()
    _print("get_groups()", groups)
    key_summary = get_user_text_keys_summary()
    _print("get_user_text_keys_summary()", key_summary)

    layer_para_test = None
    if isinstance(layers, dict):
        layer_rows = layers.get("layers", [])
        if isinstance(layer_rows, list) and layer_rows and isinstance(layer_rows[0], dict):
            layer_para_test = str(layer_rows[0].get("name", ""))

    group_para_test = None
    if isinstance(groups, dict):
        group_rows = groups.get("groups", [])
        if isinstance(group_rows, list) and group_rows and isinstance(group_rows[0], dict):
            names = group_rows[0].get("group_names", [])
            if isinstance(names, list) and names:
                group_para_test = str(names[0])

    key_para_test = None
    value_para_test = None
    if isinstance(key_summary, dict):
        key_rows = key_summary.get("keys", [])
        if isinstance(key_rows, list) and key_rows and isinstance(key_rows[0], dict):
            key_para_test = str(key_rows[0].get("key", ""))
            if key_rows[0].get("example_value") is not None:
                value_para_test = str(key_rows[0].get("example_value"))

    if layer_para_test:
        layer_out = get_objects_by_layer(layer_para_test)
        _print(f"get_objects_by_layer({layer_para_test})", layer_out)
        print(f"layer objects count: {layer_out.get('count', 0)}")
    else:
        print("skip: no layers in model")

    if group_para_test:
        group_out = get_objects_by_group(group_para_test)
        _print(f"get_objects_by_group({group_para_test})", group_out)
        print(f"group objects count: {group_out.get('count', 0)}")
    else:
        print("skip: no groups in model")

    if key_para_test:
        key_out = get_objects_by_user_text(key_para_test)
        _print(f"get_objects_by_user_text({key_para_test})", key_out)
        print(f"user_text key count: {key_out.get('count', 0)}")
        key_val_out = get_objects_by_user_text(key_para_test, value_para_test)
        _print(f"get_objects_by_user_text({key_para_test}, {value_para_test})", key_val_out)
        print(f"user_text key+value count: {key_val_out.get('count', 0)}")
    else:
        print("skip: no user_text keys in model")

    no_group = find_orphans("no_group")
    _print("find_orphans(no_group)", no_group)
    print(f"orphans no_group count: {no_group.get('count', 0)}")
    no_user_text = find_orphans("no_user_text")
    _print("find_orphans(no_user_text)", no_user_text)
    print(f"orphans no_user_text count: {no_user_text.get('count', 0)}")
    unsupported = find_orphans("unsupported_xxx")
    _print("find_orphans(unsupported_xxx)", unsupported)
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
    _print(
        "get_objects_by_layer(layer_que_no_existe_xyz_123)",
        get_objects_by_layer("layer_que_no_existe_xyz_123"),
    )


if __name__ == "__main__":
    main()

