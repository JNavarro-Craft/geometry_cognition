# rhino_extractor

- Rol: `extractor` (variable).
- Puede: leer Rhino y normalizar objetos a `object_schema.v1.json`.
- NO puede: inferir verdad constructiva o etiquetas de dominio.
- Input esperado: modelo/fuente Rhino.
- Output esperado: objetos normalizados y advertencias de extracción.
- Prohibiciones: no introducir semántica de dominio en el output base.
- Relación con otros MCPs: entrega contratos al pipeline; no importa lógica de otros MCPs.
