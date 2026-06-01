# Changelog

Registro de cambios commit-a-commit. Responde "¿qué cambió y cuándo?".
Para "¿qué tenemos hoy?", ver el checklist al final de
[`system_capabilities.md`](system_capabilities.md).

Formato: cada entrada es un commit en `main`, del más reciente al más antiguo.
Las categorías siguen el principio agnóstico — un cambio es *primitivo* (geometría/
transporte pura), *fix* (corrección), *doc* o *higiene*.

---

## Ciclo: primitivos geométricos agnósticos + higiene de transporte

Base del ciclo: `7d5e80b` (estado previo del bridge/MCP).

### `ef5663b` — Primitivo: `compute_distance` + `find_nearby`
Primitivas de proximidad — el complemento de `compute_contacts` (que solo ve lo que ya
toca): miden la separación entre objetos que NO se tocan. `MinDistanceBetween` estima la
mínima distancia superficie-a-superficie por muestreo bidireccional de puntos
(sin Brep-Brep closest-point directo en RhinoCommon). Bridge C# + MCP.
**Validado en vivo**: junta OSB de 3.000 mm; `find_nearby` con broad-phase por bbox.

### `578df18` — Higiene: `compute_contacts(summary=True)`
Última tool pesada que volcaba a disco. Colapsa cada contacto a
`{pair, contact_type, approx_area, location}` con un punto representativo, eliminando
las polilíneas voluminosas. Post-proceso Python; sin cambio de bridge.

### `c3ed591` — Higiene/fix: paginación de `list_block_definitions`
El `summary` solo no escalaba: a 410 definiciones el `definition_id` (GUID) + nombres
seguían reventando el límite. Se añadió paginación (`limit`/`offset`) y el summary ahora
también descarta el `definition_id`. **Diagnosticado en vivo** (el modelo creció a 410).

### `f73b213` — Higiene: paginación + summary en tools pesadas
`query_objects` con `offset`/`next_offset`/`has_more`; `expand_block(summary=True)` →
`content_summary` sin geometría por miembro; `list_block_definitions(summary=True)`.
Resuelve la fricción del volcado a disco. **Validado**: paginación 2+2+1 sin solape.

### `88aa004` — Doc: `system_capabilities.md`
Qué reconstruyeron los primitivos agnósticos + qué falta, separado por el test ácido
(primitivos a construir vs recetas de cliente que nunca deben ser tools).

### `b8c8a0c` — Fix (bug silencioso): errores 4xx honestos
Un 400 del bridge (tipo no soportado) se enmascaraba como `live_mode_unavailable`.
Ahora `_bridge_json_request` propaga el `{error,code}` del bridge y `_get_elements`
clasifica: 4xx = `bridge_request_rejected`; solo conexión/5xx = live unavailable.
**Hallado durante validación en vivo de `get_faces` sobre InstanceReference.**

### `62ba279` — Fix (bug silencioso): degeneración de `project_to_plane`
Una cara perpendicular al plano colapsa a línea, pero el warning no se emitía: el
criterio comparaba el bbox 2D (que una línea aún llena en un eje). Cambiado a área
shoelace del polígono proyectado. **Hallado en vivo** sobre F2.

### `e50cce4` — Primitivo: `project_to_plane`
Proyección 3D→2D: un polígono por cara en coordenadas UV del plano. Cara perpendicular
→ polígono degenerado + warning (no error). Bridge C# + MCP.

### `d8c41cf` — Primitivo: `get_vertices` / `get_edges` / `get_faces`
Geometría detallada por elemento, universal (Brep/Extrusion/Mesh). `get_faces` liga cada
cara a sus aristas vía `edge_indices` (topología). Bridge C# + MCP.
**Validado en vivo**: Euler V−E+F=2 en F2.

### `df78217` — Doc/fix: caso de estudio `obb_longest` corregido a 100%
El "95%" era artefacto de parsear el perímetro de una celda de viñeta como largo de
pieza. Recruzado en vivo: 100% por tipo, error medio 0.22 mm.

### `27b8f44` — Primitivo: `compute_contacts`
Detección de contacto real entre sólidos con ubicación (point/curve/surface) — la
primitiva de razonamiento topológico. Broad-phase por AABB + `Intersection.BrepBrep`.
Bridge C# + MCP.

### `5bc3787` — Doc: `agnostic_principle.md`
Test ácido de 4 preguntas + caso de estudio `obb_longest` vs `longest_edge` (dos
primitivas que miden cosas distintas → exponer ambas, no interpretar).

### `552f662` — Primitivo + fix: OBB / `longest_edge` + proyección de `fields`
`obb_dimensions`/`obb_*` (extents orientados, independientes de la pose) y
`longest_edge`. Fix de dos bugs silenciosos de proyección de `fields` (C# `ProjectRow`
y MCP `_project_query_fields`) que devolvían null en geometría.
**Validado**: cruce despiece↔3D 64%→100%.

---

## Convención

- Una entrada por commit, encabezada por su hash corto.
- Prefijo de categoría: **Primitivo** / **Fix** / **Higiene** / **Doc**.
- Si se validó contra modelo vivo, se marca **Validado en vivo**.
- Los bugs silenciosos encontrados durante validación se marcan como tales (la
  disciplina "falla ruidosa, no silenciosa" deja rastro aquí).
