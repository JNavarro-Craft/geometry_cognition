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
- Si hay `raw_geometry_summary.bbox_corners`: se ejecuta PCA simple sobre esos puntos para estimar `center`, `axes` y `extents`.
- Si no hay corners pero hay `raw_geometry_summary.sample_points`: se ejecuta PCA simple sobre esos samples.
- Si no hay puntos suficientes: fallback al modo previo (ejes desde `transform` o identidad, extents proxy).

Notas:
- Aun no se calcula OBB exacta de Brep/malla completa; el PCA depende de puntos de extractor.
- Si los puntos provienen de AABB (`bbox_corners`), la OBB resultante sigue siendo una aproximación basada en AABB.
- Advertencias emitidas:
  - `oriented_bbox_pca_from_bbox_corners`
  - `oriented_bbox_pca_from_sample_points`
  - `oriented_bbox_approximation` (fallback sin puntos suficientes)
- `bbox` axis-aligned actual se mantiene sin cambios para no romper compatibilidad funcional previa.

## Relaciones observacionales mínimas (bridge/local)

Cuando hay información suficiente por objeto, el kernel puede emitir relaciones mínimas:
- `near` (distancia de centroides y/o gap de bbox bajo tolerancia proxy)
- `aligned_with` (similitud de ejes dominantes, incluyendo OBB cuando está disponible)
- `parallel_to` (orientación de eje dominante)
- `grouped_with` (coincidencia observada de `group_ids`/`group_names`)
- `declared_related_to` (señales compartidas de metadata neutral como `AssemblyId`, `EnvelopeId`, `CF.PartId`)

Importante:
- Estas relaciones son observacionales y trazables.
- `declared_related_to` representa coincidencia metadata, no inferencia de dominio constructivo.
- Límites actuales: aproximaciones desde bbox/OBB; no hay contacto/intersección geométrica exacta.
