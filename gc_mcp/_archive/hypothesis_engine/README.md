# hypothesis_engine

- Rol: `hypothesis` (fijo en estructura, variable por perfil).
- Puede: generar hipótesis abstractas, probabilísticas y trazables a `evidence_items`.
- NO puede: declarar verdades absolutas sin validación.
- Input esperado: `evidence_schema.v1.json` (y entidades analíticas para anclar `entity_id`).
- Output esperado: `hypothesis_schema.v1.json`.
- Prohibiciones: hipótesis sin evidencia asociada ni estados equivalentes a "hecho definitivo".
- Relación con otros MCPs: consume evidencia y entrega candidatos al validador.

Diferencia conceptual:

- Evidencia: observaciones trazables (`claim`, `observed_value`, `confidence`) sin concluir significado final.
- Hipótesis: interpretación tentativa y refutable basada en evidencia, con alternativas y faltantes.
- Validación: etapa posterior que evalúa reglas/consistencia; no ocurre dentro de este MCP.

## Enlace de supporting_evidence

Para cada entidad, el motor prioriza IDs oficiales de evidencia:
- `ev-ent-{entity_id}`
- `ev-geom-{member_object_id}`
- `ev-rel-{relation_id}` cuando el `subject_id` u `object_id` pertenece a la entidad

Esto mantiene trazabilidad para R1/R2/R3 sin introducir términos de dominio.

## Ponderación por certeza de relaciones

Cuando existe evidencia relacional (`ev-rel-*`), la confianza de hipótesis pondera
`assertion_level`:
- `confirmed` aporta mayor peso
- `measured` aporta peso intermedio
- `candidate` aporta peso menor

Si una hipótesis depende solo de evidencia relacional candidata, se conserva limitación explícita:
- `verified geometric interaction required`

Esto evita tratar relaciones geométricas como verdades binarias.
