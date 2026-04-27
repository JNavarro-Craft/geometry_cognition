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
