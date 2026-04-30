from __future__ import annotations

from typing import Any

from shared.contracts import validate_payload


def _node(node_id: str, node_type: str, refs: list[str] | None = None) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, "refs": refs or []}


def _edge(edge_type: str, source_id: str, target_id: str) -> dict[str, str]:
    return {"edge_type": edge_type, "source_id": source_id, "target_id": target_id}


def _evidence_item(
    evidence_id: str,
    evidence_type: str,
    source_object_ids: list[str],
    claim: str,
    observed_value: Any,
    confidence: float,
    limitations: list[str],
) -> dict[str, Any]:
    item = {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "source_mcp": "evidence_graph",
        "source_object_ids": source_object_ids,
        "claim": claim,
        "observed_value": observed_value,
        "confidence": confidence,
        "supports": [],
        "contradicts": [],
        "limitations": limitations,
    }
    validate_payload("evidence_schema.v1.json", item)
    return item


def build_evidence_graph(payload: dict[str, Any]) -> dict[str, Any]:
    objects = payload.get("objects", [])
    geometry_features = payload.get("geometry_features", [])
    entities = payload.get("entities", [])
    relations = payload.get("relations", [])
    metadata = payload.get("metadata", [])

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    evidence_items: list[dict[str, Any]] = []

    for obj in objects:
        object_id = str(obj["object_id"])
        nodes.append(_node(f"obj:{object_id}", "object", [object_id]))

    for feature in geometry_features:
        object_id = str(feature["object_id"])
        feature_node_id = f"geom:{object_id}"
        nodes.append(_node(feature_node_id, "geometry_feature", [object_id]))
        edges.append(_edge("has_feature", f"obj:{object_id}", feature_node_id))
        edges.append(_edge("derived_from", feature_node_id, f"obj:{object_id}"))
        evidence_items.append(
            _evidence_item(
                evidence_id=f"ev-geom-{object_id}",
                evidence_type="geometry",
                source_object_ids=[object_id],
                claim="geometry feature observed for object",
                observed_value={
                    "morphology": feature.get("morphology"),
                    "principal_dimensions": feature.get("principal_dimensions"),
                },
                confidence=float(feature.get("morphology_confidence", 0.5)),
                limitations=["geometry_kernel_mvp_approximation"],
            )
        )

    for ent in entities:
        entity_id = str(ent["entity_id"])
        member_ids = [str(x) for x in ent.get("member_object_ids", [])]
        entity_node_id = f"ent:{entity_id}"
        nodes.append(_node(entity_node_id, "entity", [entity_id] + member_ids))
        for object_id in member_ids:
            edges.append(_edge("member_of", f"obj:{object_id}", entity_node_id))
            edges.append(_edge("supports_observation", entity_node_id, f"obj:{object_id}"))
        evidence_items.append(
            _evidence_item(
                evidence_id=f"ev-ent-{entity_id}",
                evidence_type="derived",
                source_object_ids=member_ids or [entity_id],
                claim="entity formation observed from extraction",
                observed_value={
                    "entity_type": ent.get("entity_type"),
                    "formation_method": ent.get("formation_method"),
                    "status": ent.get("status"),
                },
                confidence=float(ent.get("confidence", 0.5)),
                limitations=[str(x) for x in ent.get("limitations", [])],
            )
        )

    for rel in relations:
        relation_id = str(rel["relation_id"])
        subject_id = str(rel["subject_id"])
        object_id = str(rel["object_id"])
        rel_node_id = f"rel:{relation_id}"
        nodes.append(_node(rel_node_id, "relation", [relation_id, subject_id, object_id]))
        edges.append(_edge("has_relation", f"obj:{subject_id}", rel_node_id))
        edges.append(_edge("has_relation", rel_node_id, f"obj:{object_id}"))
        edges.append(_edge("supports_observation", rel_node_id, f"obj:{subject_id}"))
        assertion_level = str(rel.get("assertion_level", "candidate"))
        conservative_claim = f"{assertion_level} relation observed between objects"
        predicate = str(rel.get("predicate", "declared_related_to"))
        if predicate == "touches" and assertion_level == "candidate":
            conservative_claim = "candidate touching relation observed between objects"
        evidence_items.append(
            _evidence_item(
                evidence_id=f"ev-rel-{relation_id}",
                evidence_type="relation",
                source_object_ids=[subject_id, object_id],
                claim=conservative_claim,
                observed_value={
                    "predicate": predicate,
                    "relation_type": rel.get("relation_type"),
                    "directionality": rel.get("directionality"),
                    "assertion_level": assertion_level,
                    "inference_basis": rel.get("inference_basis"),
                    "measurement_method": rel.get("measurement_method"),
                    "verification_status": rel.get("verification_status"),
                    "verification_required": rel.get("verification_required", []),
                    "confidence_basis": rel.get("confidence_basis", []),
                },
                confidence=float(rel.get("confidence", 0.5)),
                limitations=[str(x) for x in rel.get("limitations", [])],
            )
        )

    for item in metadata:
        object_id = str(item["object_id"])
        node_id = f"meta:{object_id}"
        nodes.append(_node(node_id, "metadata_signal", [object_id]))
        edges.append(_edge("supports_observation", node_id, f"obj:{object_id}"))
        evidence_items.append(
            _evidence_item(
                evidence_id=f"ev-meta-{object_id}",
                evidence_type="metadata",
                source_object_ids=[object_id],
                claim="metadata_signal_observed",
                observed_value={
                    "consistency_score": item.get("consistency_score"),
                    "conflicts": item.get("conflicts", []),
                },
                confidence=float(item.get("consistency_score", 0.5)),
                limitations=[str(x) for x in item.get("limitations", [])],
            )
        )

    return {
        "mcp_name": "evidence_graph",
        "role": "graph",
        "status": "ok",
        "message": "Evidence graph built from observations and relations.",
        "expected_input_contract": "geometry_schema.v2.json + entity_schema.v1.json + relations_schema.v2.json (+ metadata_schema.v1.json optional)",
        "output_contract": "evidence_schema.v1.json",
        "nodes": nodes,
        "edges": edges,
        "evidence_items": evidence_items,
    }
