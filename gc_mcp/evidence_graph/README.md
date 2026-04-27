# evidence_graph

- Rol: `graph` (fijo).
- Puede: convertir observaciones (geometría, entidades, relaciones y metadata opcional) en evidencia trazable.
- NO puede: crear hipótesis, imponer verdad final ni clasificar dominio.
- Input esperado: `geometry_schema.v1.json`, `entity_schema.v1.json`, `relations_schema.v1.json`, `metadata_schema.v1.json` (opcional).
- Output esperado: `evidence_schema.v1.json` (en `evidence_items`) + estructura auxiliar de `nodes` y `edges`.
- Diferencia clave:
  - `observation_refs`: referencias de observación emitidas por etapas previas.
  - `evidence_items`: formalización trazable de claims observados con `source_mcp`, `claim`, `confidence` y `limitations`.
- Prohibiciones: saltarse trazabilidad de origen o convertir evidencia en hipótesis.
- Relación con otros MCPs: puente entre observación estructurada y futuras etapas de hipótesis/validación.
