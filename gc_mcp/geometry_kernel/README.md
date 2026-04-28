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

## oriented_bbox (primer paso v2)

Implementación actual (conservadora / aproximada):
- `center`: se toma del centro geométrico actualmente calculado por el kernel.
- `extents`: se toma de las dimensiones actuales (`principal_dimensions` proxy vigentes).
- `axes`: se toman de la base del `transform` del objeto cuando está disponible; si no, identidad.

Notas:
- En esta fase no se calcula OBB exacta por intersección/casco convexo/PCA de malla completa.
- Se agrega advertencia `oriented_bbox_approximation` en `geometric_warnings`.
- `bbox` axis-aligned actual se mantiene sin cambios para no romper compatibilidad funcional previa.
