# Plan: puente Rhino↔Claude robusto de lectura y análisis de cambios

Objetivo: robustecer `rhino_bridge` (C#) y `developer_server` (MCP Python) para que
Claude pueda, desde una sesión, **leer el modelo Rhino al detalle, descubrir su
estructura sin adivinar, y analizar cambios** de forma confiable. Todo estrictamente
**observacional y agnóstico al dominio**: el MCP entrega hechos geométricos y de
metadata; el conocimiento de negocio (precios, cubicación, qué es un error) vive en
la sesión de Claude.

Este plan NO incluye mutación del modelo (eso es un MCP `automation` aparte) ni
interpretación de dominio (archivado en `gc_mcp/_archive/`).

---

## Principios de diseño (no negociables)

1. **Descubrir antes de filtrar.** Todo filtro debe poder validarse contra el modelo
   real. El MCP nunca debe devolver "0 resultados" sin distinguir *"el filtro era
   válido pero no hubo match"* de *"el filtro no aplica a este modelo"*.
2. **Falla ruidosa, no silenciosa.** Ningún fallback puede devolver datos distintos a
   los pedidos haciéndolos pasar por correctos (hoy `extract_scene` ignora filtros).
3. **El snapshot es la fuente de verdad para análisis.** Todo lo consultable en vivo
   debe ser consultable también sobre un snapshot persistido.
4. **Agnóstico.** El bridge y el MCP no nombran dominio. Reportan tipos Rhino, claves
   de user_text, y geometría. "Esto es una ventana que cuesta $X" lo pone Claude.

---

## Estado actual (línea base verificada)

**Bridge C# — endpoints útiles ya existentes:**
- `/v1/live/scene/summary`, `/v1/live/objects/query` (filtros: layers, types,
  name_contains, has_user_text, user_text key/value, bbox_intersects),
  `/v1/live/objects/{id}`.
- `/geometry/extract_scene` (legacy), `/geometry/extract_objects`, `/geometry/verify_relations`.
- Endpoints legacy con vocabulario de dominio (`/get-truss-geometry`, `/get-connector-summary`,
  `TrussService`, `FrameService`, `ConnectorService`): **a deprecar/aislar**, contradicen el core agnóstico.

**developer_server — tools actuales:**
- `take_snapshot`, `list_snapshots`, `diff_snapshots`, `diff_object`, `inspect_object`, `assert_change`.

**Huecos confirmados (raíz de los síntomas reportados):**
| Hueco | Capa | Síntoma que causa |
|---|---|---|
| Definiciones de bloque no se expanden | bridge C# | "no encontró info que sí había" (contenido del bloque invisible) |
| Snapshot proyecta solo ~8 campos (pierde transform, block_context, material, visibilidad, object_kind) | MCP Python | "información oculta" |
| Fallback `live→extract_scene` ignora filtros silenciosamente | MCP Python | "filtró antes de tiempo / asumió filtros" |
| No hay warning "filtro válido pero 0 matches" vs "clave inexistente" | MCP Python | "asumió filtros que no eran reales" |
| No hay tool de descubrimiento (layers/keys/tipos reales) | MCP Python | "adivinó filtros" |
| No hay agregación group-by/sum | MCP Python | bloquea cómputos/cubicaciones |
| Visibilidad (objeto/layer oculto) no se extrae | bridge C# (verificar) | "información oculta" |
| Consulta solo en vivo, no sobre snapshot | MCP Python | no se puede analizar un estado pasado |

---

## Fases (orden por dependencia)

### Fase 0a — Limpieza de dominio (HECHA)
*Bridge C#. Dejar la base agnóstica antes de construir encima.*

Ejecutado:
- Borrados los placeholders vacíos `TrussService.cs`, `ConnectorService.cs`,
  `ValidationService.cs` (7 líneas c/u, sin lógica ni referencias).
- Quitados del router los endpoints de dominio `/get-truss-geometry`,
  `/get-connector-summary`, `/classify-instance-materials`.
- `FamilyService.DetectRole()`: eliminada la inferencia de dominio
  (`structural`/`cladding` por palabras truss/viga/panel/osb). Conservados los flags
  agnósticos (`empty_group`, `low_object_count`, `single_geometry_type`,
  `duplicate_candidate`). Eliminado el helper `ContainsAny` que quedó sin uso.
- Conservados (son agnósticos): `/detect-duplicate-groups`, `/inspect-usertext-schema`
  (encajan con Fases 1 y 4), `FrameService` (frames locales por PCA), el resto de
  `FamilyService` (agrupación por prefijo de nombre).
- Build del plugin verificada: 0 warnings, 0 errores.

Pendiente (fuera del alcance "solo basura muerta", decisión futura):
- Renombrar `FamilyService`→`GroupingService` y limpiar el término "family" de endpoints.
- Renombrar el plugin `RhinoPrefabGeometryPlugin`→nombre agnóstico (invasivo: namespace,
  .rhp, comando, reinstalación en Rhino).
- `gc_mcp/_archive/` (domain_interpreter, hypothesis_engine, validation_engine): se deja
  donde está, fuera del pipeline activo.

### Fase 0 — Higiene y honestidad (HECHA)
*Solo MCP Python. Desbloquea confianza inmediata.*

- **0.1 (hecho)** `take_snapshot` ya no disfraza el fallback: si cae a `extract_scene`
  con filtros pedidos → `status: filter_not_applied` explícito, no `ok`.
- **0.2 (hecho parcial)** `filter_report` con `matched_count` y clasificación
  `ok` / `filter_valid_empty` / `filter_not_applied`. La distinción
  `filter_unknown_key` (clave inexistente) queda para Fase 1 (necesita el catálogo de
  `describe_model`); hoy una clave inexistente cae en `filter_valid_empty`.
- **0.3 (hecho)** `delete_snapshot(label)` y `prune_snapshots(keep_latest_n)`.
- **0.4 (hecho)** Snapshot proyecta `transform`, `block_context`, `object_kind`,
  `material`; el diff detecta cambios en `object_kind`, `material` y `block_context`.

Tests: añadidos en `tests/test_developer_server.py` (delete/prune, proyección, diff de
bloque/material, los 3 estados de `filter_report`). Verificados con runner directo
contra la normalización real del bridge (pytest no corre aquí: el único Python del
sistema es el 3.9 de Rhino sin pytest; el proyecto requiere 3.11+).

### Fase 1 — Descubrimiento ("describe antes de filtrar") (HECHA)
*MCP Python, apoyándose en lo que el bridge ya da.*

- **1.1 (hecho)** `describe_model()`: layers reales con conteos, tipos Rhino con
  conteos, grupos, catálogo de claves de user_text (`occurrence_count`,
  `distinct_values_count`, `example_value`), y definiciones de bloque con nº de
  instancias. Es el tool que elimina la adivinación de filtros. Pendiente Fase 5:
  visibilidad de layer/objeto y FullPath explícito (requiere campo del bridge).
- **1.2 (hecho)** `query_objects(filters, source="live"|<label>, limit, fields)` sobre
  vivo Y sobre snapshot. Filtros agnósticos AND-combinados: `layers`, `types`,
  `name_contains`, `user_text_key`, `user_text` (key=value), `is_block_instance`.
  El filtrado se hace en Python (no se empuja al bridge) → resultado honesto
  independiente de la estrategia de fetch. Paso clave hacia el reemplazo de
  reader_server. (Pendiente: paginación por cursor; hoy solo `limit`.)

Tests: 7 nuevos en `tests/test_developer_server.py` (catálogo, live-unavailable,
filtros live por layer/type/user_text/name, valor de filtro inexistente → vacío,
query sobre snapshot pasado, snapshot_not_found, filtro is_block_instance).

### Fase 2 — Expansión de bloques + texto de anotaciones (PARCIAL: 2.1, 2.2, 1.2 HECHAS)
*Bridge C# primero, luego MCP. Sin esto no hay cómputo real con bloques.*

- **2.1 (hecho)** Bridge: `GET /v1/live/definitions` → lista de definiciones
  (`definition_name`, `definition_id`, `object_count`, `instance_count`, `bbox`).
- **2.2 (hecho, = 1.3a)** Bridge: `GET /v1/live/definition_objects?name=...` → objetos que
  componen la definición vía `InstanceDefinition.GetObjectIds()`, cada uno extraído con
  `ExtractObject` (geometría, material, user_text, **texto de anotación**), `transform_applied=false`.
  MCP: tools `list_block_definitions()` y `expand_block(definition_name)`.
- **1.2 (hecho)** Bridge: texto de anotaciones. `ExtractObject` ahora añade
  `annotation_text {kind, plain_text, rich_text?}` para `TextEntity` / `AnnotationBase`
  (cotas, leaders) / `TextDot`. Se propaga por el adapter (schema v1 actualizado), se
  proyecta al snapshot y es diffeable. Resuelve la brecha 🔴 "leer texto del modelo".
- **2.3 (pendiente, = 1.3b)** `resolve_blocks` con transform aplicado en contexto (caro).
  Flag `expand_blocks=true` en `query_objects`/`take_snapshot`. No hecho aún.

### Fase 3 — Primitivas de cómputo (habilita cotización/cubicación)
*MCP Python, agnóstico. Bridge solo si falta una métrica geométrica.*

- **3.1** Bridge (si falta): longitud de curvas, área por cara, volumen real de Breps
  cerrados — verificar qué ya da `raw_geometry_summary` (hoy: bbox, volume, area,
  face/edge count, is_closed).
- **3.2** MCP: `aggregate(source, group_by=[campos], metrics=[count|sum:campo|...])`.
  Agnóstico: agrupa por cualquier campo (incl. `user_text.<clave>`) y suma cualquier
  escalar. Claude pide "group_by user_text.Material, sum volume" → el MCP no sabe qué
  es "Material", solo agrupa. Esto convierte datos sueltos en cómputos pedibles.
- **3.3** MCP: `bill_of_materials()` = atajo sobre 3.2 + Fase 2: por definición de
  bloque, nº instancias × desglose del contenido.

### Fase 4 — Análisis de cambios robusto
*MCP Python. Extiende diff/assert con lo nuevo.*

- **4.1** `assert_change` con reglas sobre **valores** (no solo conteos): "volume del
  GUID X bajó ≥10%", "ningún objeto cambió de layer A→B", "ninguna definición perdió
  instancias". Los datos ya están en el diff.
- **4.2** `diff` consciente de bloques: detectar instancias añadidas/quitadas por
  definición, no solo por GUID.
- **4.3** Detección de anomalías observacionales (para "analizar errores"): duplicados
  exactos (mismo bbox+tipo+transform), geometría degenerada, instancias con definición
  vacía, objetos sin las claves user_text que el resto de su layer/tipo sí tiene.
  Reporta hechos sospechosos; Claude decide si son errores.

### Fase 5 — Visibilidad y campos finos
*Verificar bridge primero; puede ser 1 o 2 capas.*

- **5.1** Confirmar si el bridge expone `IsHidden`/visibilidad de objeto y layer. Si no,
  añadirlo en C#. Exponerlo en el snapshot. (Causa probable de "información oculta".)
- **5.2** Color, display mode, otros atributos que Claude pueda necesitar para análisis.

---

## Lo que va en `.md` (no código)

- Catálogo semántico del dominio (qué significa `CF.PartId`, `AssemblyId`, etc.) →
  vive en la sesión/prompt de Claude, NO en el MCP.
- Recetas de orquestación: "para cotizar: `describe_model` → `expand_block` →
  `aggregate`". Claude las aprende del `.md`, no son lógica del MCP.
- Sintaxis de filtros: AND-combinados, case-sensitive, layer = FullPath con `::`.

---

## Reemplazo de reader_server

Tras Fase 1.2 + 3.2, `developer_server` cubre todo lo de `reader_server` (consulta de
estado) MÁS análisis de cambios. En ese punto `reader_server` puede deprecarse. Hasta
entonces conviven.

---

## Orden recomendado de ejecución

1. **Fase 0** (confianza inmediata, solo Python, sin tocar Rhino).
2. **Fase 1** (descubrimiento — mata la adivinación de filtros).
3. **Fase 2** (bloques — el desbloqueo estructural; requiere build del plugin C#).
4. **Fase 3** (cómputos — habilita el caso de cotización).
5. **Fases 4 y 5** en paralelo según necesidad.
