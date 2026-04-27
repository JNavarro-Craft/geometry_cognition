# knowledge_base

- Rol: `knowledge` (fijo).
- Puede: persistir conocimiento validado y su trazabilidad.
- NO puede: persistir ocurrencias accidentales sin validación suficiente.
- Input esperado: `validation_schema.v1.json`, `hypothesis_schema.v1.json`.
- Output esperado: registros persistentes versionados.
- Prohibiciones: almacenar hipótesis no validadas o sin estado aprobado/aceptado por política como hechos.
- Relación con otros MCPs: recibe validación, habilita reutilización histórica.
