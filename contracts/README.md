# Contracts

Los contratos en esta carpeta son la interfaz estable del sistema. Cada MCP debe producir y consumir payloads JSON compatibles con estos schemas versionados.

Principios:

- Comunicación entre MCPs solo por JSON versionado.
- Cambios incompatibles requieren nueva versión de contrato.
- El contrato define forma y semántica mínima de intercambio.
- La lógica interna de cada MCP puede evolucionar sin romper integraciones mientras respete el contrato.
- `entity_schema.v1.json` permite representar entidades analíticas intermedias sin colapsarlas en hipótesis o hechos.

## Diferencias conceptuales clave

- `object`: observación normalizada cruda proveniente de extractor (nivel fuente).
- `entity`: agrupación/abstracción analítica basada en observaciones y relaciones; no equivale a verdad validada.
- `relation`: vínculo observado o derivado entre objetos/entidades, con contexto de tolerancia y limitaciones.
- `evidence`: formalización trazable de claims observacionales para sustentar o contradecir hipótesis.
- `hypothesis`: propuesta interpretativa probabilística y refutable, nunca hecho definitivo por sí sola.

## Relaciones v1 vs v2

- `relations_schema.v1.json`: relación observacional básica (predicado, confianza y tolerancias).
- `relations_schema.v2.json`: misma base + certeza epistemológica explícita:
  - `assertion_level`: `candidate` | `measured` | `confirmed`
  - `inference_basis` y `measurement_method`
  - `verification_status` y `verification_required`
  - `confidence_basis`

Notas de interpretación:
- `candidate` no equivale a verdad geométrica confirmada.
- `bbox overlap` no implica intersección Brep real.
- `near` no implica contacto.
- relaciones por metadata siguen siendo observacionales y no funcionales.
