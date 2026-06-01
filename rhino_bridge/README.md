# Rhino Plugin Bridge (MVP)

Backend Rhino `.rhp` para `geometry_cognition`.

## Estructura

- `rhino_bridge/plugin/`: proyecto C# del plugin Rhino (`RhinoPrefabGeometryPlugin.csproj`).
- `gc_mcp/`: MCPs Python del pipeline cognitivo.
- `/geometry/*`: bridge neutral para extracción geométrica.
- Endpoints legacy fuera de `/geometry/*` se conservan por compatibilidad.

## Build del plugin

Entrar a `rhino_bridge/plugin` y compilar:

```bash
dotnet build RhinoPrefabGeometryPlugin.csproj
```

Artefacto esperado del plugin: `rhino_bridge.dll` / `rhino_bridge.rhp`.

En Rhino, el comando `RhinoAI` levanta el servidor HTTP local.

## Instalación persistente en Rhino (PlugInManager)

Para que el comando `RhinoAI` siga disponible al cerrar y abrir Rhino:

1. Compila el plugin:
   - `./build.ps1`
2. En Rhino abre `PlugInManager`.
3. Usa **Install...** y selecciona `rhino_bridge/dist/rhino_bridge.rhp`.
4. Verifica que el plugin quede listado como instalado y habilitado.
5. En opciones del plugin, deja habilitada carga automática / startup (el plugin también declara `LoadTime=AtStartup`).
6. Reinicia Rhino y ejecuta `RhinoAI` sin volver a cargar manualmente.

Importante:
- No uses drag & drop / carga manual como mecanismo de instalación persistente.
- Para persistencia, siempre instala desde `PlugInManager -> Install...`.

Si se compiló en una ruta temporal o movible, reinstala desde una ruta estable del repo para evitar pérdida de registro.

Notas de empaquetado:
- Para Rhino, un `.rhp` es una librería .NET con extensión `.rhp`. En este flujo, `build.ps1` compila el `.dll` y genera el `.rhp` por copia de extensión.
- No se requiere `.rui` para registrar el comando en este plugin.
- `.yak` es opcional (distribución), no necesario para instalación local persistente por PlugInManager.

## Endpoints MVP (legacy + bridge actual)

- `GET /health`
- `GET /doc-info`
- `GET /summarize-model`
- `GET /list-named-families`
- `GET /summarize-family?name=...`
- `GET /get-family-instances?name=...`
- `GET /list-groups`
- `GET /inspect-metadata-coverage`
- `GET /get-instance-frame-candidates?instance_id=grp:12`
- `GET /get-instance-geometry?instance_id=grp:12`
- `GET /get-instance-local-frame?name=...&group_id=...`

## Endpoints neutrales `/geometry/*`

- `GET /geometry/health`
- `POST /geometry/extract_scene` (**legacy**: carga completa en un solo POST; mantener como respaldo)
- `POST /geometry/extract_objects`
- `POST /geometry/verify_relations`

## API incremental `/v1/live/*` (recomendada para exploración)

Estos endpoints evitan volcar toda la escena en un único payload. El cliente Python (`gc_mcp`) usa por defecto `GC_BRIDGE_FETCH_STRATEGY=live`: lista ids vía query paginada y rehidrata con `POST /geometry/extract_objects` por lotes. Si falla, puede volver a `extract_scene` con `GC_BRIDGE_FALLBACK_EXTRACT_SCENE=1` (por defecto).

- `GET /v1/live/scene/summary?sample_limit=20` — conteos, `global_bbox`, `type_counts`, `sample_objects` ligeros (sin normales/áreas por cara ni geometría pesada).
- `POST /v1/live/objects/query` — cuerpo JSON: `filters` (layers, types, name_contains, has_user_text, user_text_key/value, bbox_intersects), `fields`, `limit`, `cursor`. Respuesta: `objects`, `matched_count`, `next_cursor` opcional.
- `GET /v1/live/objects/{object_id}?detail_level=basic|full&user_text=none|keys|full` — detalle bajo demanda; `basic` usa resumen geométrico ligero (sin `face_normals` / `face_areas`). Con `detail_level=full`, las anotaciones incluyen `annotation_text {kind, plain_text, rich_text?}`.
- `GET /v1/live/definitions` — definiciones de bloque: `definition_name`, `definition_id`, `object_count` (miembros), `instance_count` (instancias en el doc), `bbox`.
- `GET /v1/live/definition_objects?name=<definition_name>[&instances=true]` — objetos que componen una definición (vía `InstanceDefinition.GetObjectIds()`), extraídos con el mismo shape que un objeto normal, `transform_applied=false` (contenido crudo, sin posicionar). `name` case-sensitive. Con `instances=true` añade `instances`: una fila por instancia colocada con el bbox de cada miembro transformado por la `InstanceXform` de esa instancia (liviano, no mueve geometría).
- `raw_geometry_summary` incluye `length` para curvas (longitud real vía `Curve.GetLength()`), además de bbox / volume / area / face_count / edge_count / is_closed.
- La respuesta de `POST /v1/live/objects/query` incluye `filter_warnings.unknown_filter_keys` si se envían claves de filtro no reconocidas (en vez de ignorarlas en silencio).

### Variables de entorno (lado Python `gc_mcp/rhino_extractor`)

- `GC_BACKEND_MODE`: `bridge` para usar bridge HTTP; cualquier otro valor mantiene extractor local.
- `GC_BRIDGE_BASE_URL`: base URL del bridge (default `http://127.0.0.1:8765`).
- `GC_BRIDGE_TIMEOUT_SECONDS`: timeout HTTP en segundos.
- `GC_BRIDGE_FETCH_STRATEGY`: `live` (default, camino principal incremental) o `extract_scene` (legacy explícito).
- `GC_BRIDGE_LIVE_QUERY_LIMIT`: tamaño de página para `POST /v1/live/objects/query`.
- `GC_BRIDGE_EXTRACT_BATCH_SIZE`: tamaño de lote para `POST /geometry/extract_objects`.
- `GC_BRIDGE_FALLBACK_EXTRACT_SCENE`: `1/true` permite fallback de `live` a `/geometry/extract_scene` si falla el flujo incremental.
- `GC_BRIDGE_FALLBACK_LOCAL`: `1/true` permite fallback final a extractor local de archivo cuando falla backend bridge.

Camino principal actual: `live` (summary/query/detail + extracción por ids).  
Camino legacy/fallback: `POST /geometry/extract_scene`.

### `POST /geometry/verify_relations`

Verifica relaciones geometricas con chequeos neutrales. Este endpoint mide/verifica geometria y **no** interpreta dominio.

Input ejemplo:

```json
{
  "relations": [
    {
      "relation_id": "rel-001",
      "subject_id": "11111111-1111-1111-1111-111111111111",
      "object_id": "22222222-2222-2222-2222-222222222222",
      "check": "mesh_distance_check"
    }
  ],
  "tolerance": {
    "linear_tolerance": 0.05,
    "angular_tolerance": 2.0,
    "unit_system": "model_unit"
  }
}
```

Output ejemplo:

```json
{
  "source": "rhino_bridge",
  "results": [
    {
      "relation_id": "rel-001",
      "subject_id": "11111111-1111-1111-1111-111111111111",
      "object_id": "22222222-2222-2222-2222-222222222222",
      "check": "mesh_distance_check",
      "verification_status": "verified",
      "assertion_level": "confirmed",
      "method": "mesh_distance",
      "measurements": {
        "distance": 0.0,
        "intersection_count": 0,
        "contact_area_estimate": null
      },
      "confidence": 0.88,
      "limitations": [],
      "notes": []
    }
  ]
}
```

Checks minimos implementados:
- `mesh_distance_check`
- `brep_contact_check`
- `brep_intersection_check`
- `face_adjacency_check` (estado inicial inconclusive)
- `tolerance_review`

## Notas

- El acceso a `RhinoDoc.ActiveDoc` se ejecuta en UI thread para seguridad.
- El bridge devuelve JSON compacto, sin dumps de geometría cruda.

