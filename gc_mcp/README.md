# MCPs

Cada subcarpeta define un MCP con responsabilidad explícita y límites conceptuales.

Reglas:

- Sin imports directos de lógica entre MCPs.
- Intercambio exclusivamente por contratos JSON versionados en `contracts/`.
- Cada MCP publica claramente su rol (`extractor`, `kernel`, `context`, `graph`, `hypothesis`, `validation`, `knowledge`, `automation`).
