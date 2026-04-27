# domain_interpreter

- Rol: `domain_interpretation` (semivariable por perfil).
- Puede: traducir hipotesis abstractas a etiquetas de interpretacion conservadora de dominio.
- NO puede: clasificar identidad final, validar reglas ni ejecutar acciones.
- Input esperado: `hypothesis_schema.v1.json` + `domain_profiles/<profile>/interpretation_rules.json`.
- Output esperado: `domain_interpretation_schema.v1.json`.
- Prohibiciones:
  - no usar vocabulario prohibido (`beam`, `panel`, `truss`, `SIP`, `connector`)
  - no declarar verdad definitiva
  - no usar `knowledge_base/imports/prefab/*` como fuente de runtime
- Relacion con otros MCPs: consume hipotesis y produce interpretaciones tentativas para revision humana.

## Diferencia conceptual

- No es clasificacion: no determina "que es" una entidad como verdad.
- No es validacion: no emite pass/fail de reglas.
- No es automatizacion: no dispara acciones ni side-effects.
- Es interpretacion conservadora: solo mapea hipotesis a lenguaje `compatible_with_*`, `suggests_*` o `requires_human_review`.
