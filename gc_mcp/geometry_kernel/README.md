# geometry_kernel

- Rol: `kernel` (fijo).
- Puede: calcular features geométricos abstractos y relaciones básicas.
- NO puede: usar vocabulario de dominio ni concluir función constructiva.
- Input esperado: `object_schema.v1.json`.
- Output esperado: `geometry_schema.v1.json` y `relations_schema.v1.json`.
- Prohibiciones: términos de dominio dentro del kernel.
- Relación con otros MCPs: produce observaciones geométricas estructuradas para `evidence_graph`.

## geometry_schema v1 vs v2 (preparación conceptual)

- `geometry_schema.v1.json`: contrato estable actual, con `bbox`, `centroid`, dimensiones, morfología y advertencias geométricas básicas.
- `geometry_schema.v2.json`: extensión opcional para integración futura (sin exigir cálculo complejo en esta fase):
  - `oriented_bbox` (`center`, `axes`, `extents`)
  - `face_analysis` (`face_count`, `dominant_faces`, `area_distribution`)
  - `normal_vectors` (`dominant_normals`, `clusters` opcional)
  - `proximity_metrics` (`min_distance_to_neighbors`, `contact_candidates`)
  - `geometry_quality` (`warnings`)

Compatibilidad:
- v1 se mantiene intacto y sigue siendo el output operativo actual del kernel.
- v2 agrega campos opcionales y permite tests de formato/contrato para preparación de `geometry_kernel_v2`, sin cambiar la lógica vigente.
