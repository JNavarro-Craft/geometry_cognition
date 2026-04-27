# Prefab Extraction Report (Knowledge-Only, Inactive)

## Scope

This extraction imported only user-provided structured knowledge into allowed non-core paths:

- `domain_profiles/prefab/**`
- `knowledge_base/imports/prefab/**`
- `knowledge_base/audit/**`

No executable legacy logic was migrated. No runtime activation was performed.

## Imported Artifacts

- `domain_profiles/prefab/rules/geometry_member_summary_rules.imported.json`
- `domain_profiles/prefab/examples/group_classification_cases.imported.json`
- `domain_profiles/prefab/examples/geometry_validation_cases.imported.json`
- `domain_profiles/prefab/counterexamples/known_failure_modes.imported.json`
- `knowledge_base/imports/prefab/context_rules_and_guidelines.imported.json`
- `knowledge_base/audit/prefab_extraction_trace.json`

## Layer Separation Notes

- Observation and metadata signals were stored as references, not runtime code.
- Validation rules were stored as inactive imported knowledge.
- Domain interpretation examples remain in-review and conservative.
- No automation recipe was created or activated.

## Language Safety

- No definitive identity claims were used.
- Conservative language was used (`suggests_*`, `compatible_with_*`, `requires_human_review`).

## Traceability Check

All imported items include:

- `id`
- `description`
- `source`
- `conceptual_layer`
- `signals_used`
- `assumptions`
- `limitations`
- `contamination_risk`
- `status`
- `notes`

## Activation Check

All imported items are marked either:

- `inactive`, or
- `in_review`

No automatic registration, no runtime hooks, no automation side-effects.

## Post-Migration Audit

### A) Traceability

- Result: pass (for newly imported artifacts in this migration scope).
- All imported artifacts contain source references and extraction date at artifact level.

### B) Vocabulary Contamination Outside Allowed Paths

- Result: **needs_refactor** (global workspace check).
- Detected prefab/domain terms outside allowed migration paths in pre-existing files, including:
  - `tests/test_minimal_workflow.py`
  - `tests/test_validation_engine.py`
  - `tests/test_hypothesis_engine.py`
  - `tests/test_evidence_graph.py`
  - `tests/test_contracts.py`
  - `gc_mcp/hypothesis_engine/tools.py`
  - `gc_mcp/validation_engine/tools.py`
  - `gc_mcp/metadata_context/README.md`
  - `domain_profiles/generic/profile.json`
- Action: no changes were applied to those files in this migration; flagged for follow-up review.

### C) Conceptual Layer Mixing

- Result: pass for imported items.
- No imported item mixes incompatible layers such as `domain_interpretation` + `automation_recipe`.

### D) Core Integrity

- Result: pass.
- No changes were applied to:
  - `geometry_kernel/**`
  - `evidence_graph/**`
  - `hypothesis_engine/**`
  - `validation_engine/**`
  during this migration execution.
