# automation

- Rol: `automation` (variable).
- Puede: ejecutar acciones posteriores a validación.
- NO puede: actuar con hipótesis no validadas.
- Input esperado: resultados explícitos de `validation_schema.v1.json` con estado evaluado por regla.
- Output esperado: estado de ejecución de acciones.
- Prohibiciones: automatizar sin puerta de validación y sin criterio explícito de elegibilidad (`status=pass` o política equivalente).
- Relación con otros MCPs: consumidor terminal del pipeline.
