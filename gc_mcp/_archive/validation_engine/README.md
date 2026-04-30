# validation_engine

- Rol: `validation` (fijo).
- Puede: evaluar reglas de consistencia sobre hipótesis existentes y su trazabilidad.
- NO puede: ejecutar acciones ni crear hipótesis nuevas.
- Input esperado (payload de tool):  
  - `hypotheses` (`hypothesis_schema.v1.json[]`)  
  - `evidence_items` (`evidence_schema.v1.json[]`)  
  - `entities` (`entity_schema.v1.json[]`)  
  - `relations` (`relations_schema.v1.json[]`)  
  Nota: `entities` y `relations` son requeridos para evaluaciones completas (ej. R2).
- Output esperado: `validation_schema.v1.json`.
- Prohibiciones: validar sin evidencias o sin explicar estados `skipped/inconclusive`.
- Relación con otros MCPs: puerta previa a persistencia y automatización.

Diferencias conceptuales:

- Hipótesis: propuesta tentativa y refutable.
- Validación: evaluación de calidad/coherencia de la hipótesis, sin cambiar su naturaleza.
- Acción: ejecución operativa posterior; no ocurre en este MCP.
