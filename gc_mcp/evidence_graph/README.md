# evidence_graph

- Rol: `graph` (fijo).
- Puede: convertir observaciones (geometría, entidades, relaciones y metadata opcional) en evidencia trazable.
- NO puede: crear hipótesis, imponer verdad final ni clasificar dominio.
- Input esperado: `geometry_schema.v2.json`, `entity_schema.v1.json`, `relations_schema.v2.json`, `metadata_schema.v1.json` (opcional).
- Output esperado: `evidence_schema.v1.json` (en `evidence_items`) + estructura auxiliar de `nodes` y `edges`.
- Diferencia clave:
  - `observation_refs`: referencias de observación emitidas por etapas previas.
  - `evidence_items`: formalización trazable de claims observados con `source_mcp`, `claim`, `confidence` y `limitations`.
- Prohibiciones: saltarse trazabilidad de origen o convertir evidencia en hipótesis.
- Relación con otros MCPs: puente entre observación estructurada y futuras etapas de hipótesis/validación.

## Evidencia formal emitida

El grafo emite evidencia oficial y trazable por tipo:
- `ev-geom-{object_id}` para features geométricos (`evidence_type=geometry`)
- `ev-ent-{entity_id}` para formación de entidades (`evidence_type=derived`)
- `ev-rel-{relation_id}` para relaciones observadas (`evidence_type=relation`)

`claim` se mantiene conservador (observación), por ejemplo:
- "geometry feature observed for object"
- "entity formation observed from extraction"
- "candidate relation observed between objects"
- "measured relation observed between objects"
- "confirmed relation observed between objects"

Para `ev-rel-*`, el grafo preserva campos de certeza provenientes de relaciones v2
en `observed_value`:
- `assertion_level`
- `inference_basis`
- `measurement_method`
- `verification_status`
- `verification_required`
- `confidence_basis`

Las relaciones derivadas de metadata (`declared_related_to`) siguen siendo observacionales;
no implican clasificación de dominio.
