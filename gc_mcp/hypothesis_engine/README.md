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
