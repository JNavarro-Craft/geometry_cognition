# developer_server

- Rol: `observador` (variable, herramienta de desarrollo).
- Puede: capturar snapshots del modelo Rhino activo vía el bridge HTTP, persistirlos por label, y comparar dos snapshots para detectar objetos creados / borrados / modificados por GUID.
- NO puede: ejecutar comandos en Rhino, mutar el modelo, ni invocar al plugin C#. Es estrictamente observacional.
- Input esperado: estado actual del modelo Rhino expuesto por el bridge en `GC_BRIDGE_BASE_URL`.
- Output esperado: snapshots persistidos en `${GC_OUTPUTS_DIR}/dev_snapshots/` y diffs estructurados.
- Prohibiciones: no introducir semántica de dominio. Detecta cambios, no interpreta su causa. No comparte estado con `reader_server` (es hermano, no hijo).
- Relación con otros MCPs: importa primitivos compartidos (`gc_mcp.rhino_extractor.bridge_backend`, `gc_mcp.rhino_extractor.backend_adapter._normalize_bridge_objects`). No depende de `reader_server`.

## Flujo soportado

1. Abrir Rhino con el plugin cargado y el bridge en `:8765`.
2. `take_snapshot("antes")` desde el cliente MCP.
3. Ejecutar manualmente el comando del plugin que se está probando.
4. `take_snapshot("despues")`.
5. `diff_snapshots("antes", "despues")` → lista de GUIDs creados / borrados / modificados, con detalle por campo.
6. Opcional: `assert_change("antes", "despues", {...expectations...})` para validar expectativas concretas.

## Tools

| Tool | Comportamiento |
|---|---|
| `take_snapshot(label, sample_limit=20, layers, types, name, user_text_key, bbox)` | Captura escena live (vía `fetch_scene_via_live_query_and_extract_objects` con fallback a `extract_scene`) + `summarize-model`. Persiste por label (sobrescribe si existe). Filtros opcionales AND-combinados aplicados en el bridge. Devuelve `status` + `filter_report` honesto (ver abajo). |
| `list_snapshots()` | Lista snapshots en `dev_snapshots/`. |
| `delete_snapshot(label)` | Borra todos los snapshots de un label. `status: not_found` si no había. |
| `prune_snapshots(keep_latest_n=1)` | Conserva los `keep_latest_n` más recientes por label, borra los más viejos. `keep_latest_n=0` borra todos. |
| `diff_snapshots(label_a, label_b, bbox_tolerance=1e-6, detail="full")` | Diff por GUID. Reporta created / deleted / modified con detalle. Detecta cambios en `object_kind`, `material` y `block_context` además de layer/name/raw_type/user_text/grupos/bbox/geometría. |
| `diff_object(label_a, label_b, guid)` | Diff de un solo GUID, mismo detalle que `diff_snapshots(detail='full')`. |
| `inspect_object(guid, detail_level="full", user_text="values")` | Pass-through a `/v1/live/objects/{guid}` del bridge. |
| `assert_change(label_a, label_b, expectations)` | Valida expectativas (`created.min`, `created.in_layer`, `created.with_user_text_key`, etc.) contra el diff. |

## Campos persistidos por objeto en el snapshot

`object_id`, `layer`, `name`, `raw_type`, `object_kind`, `material`, `user_text`,
`group_ids`, `group_names`, `block_context` (`is_block_instance`, `block_name`,
`instance_definition_id`), `transform` (matriz 16, no se diffea — el cambio de pose se
ve en `bbox`), `bbox`, `bbox_center`, y escalares geométricos (`volume`, `area`,
`face_count`, `edge_count`, `is_closed`).

## `filter_report` (honestidad de filtros)

`take_snapshot` nunca devuelve un filtrado falso. El `status` y `filter_report` indican:

- `ok`: sin filtro, o filtro aplicado tal cual.
- `filter_valid_empty`: el filtro se aplicó en el bridge y coincidió con 0 objetos.
  Es un "no hay nada" confiable, no un error.
- `filter_not_applied`: la estrategia live falló y el fallback a `extract_scene`
  devolvió el modelo **completo sin filtrar**. NO confíes en `matched_count` como
  resultado filtrado; trata el snapshot como no filtrado.

## Variables de entorno

Mismas que `reader_server`:

- `GC_BACKEND_MODE=bridge`
- `GC_BRIDGE_BASE_URL` (default `http://127.0.0.1:8765`)
- `GC_BRIDGE_TIMEOUT_SECONDS` (default `10`)
- `GC_OUTPUTS_DIR` (default `C:\geometry_cognition\outputs`)

## Definición de "modificado"

Un GUID presente en ambos snapshots cuenta como modificado si difiere en cualquiera de: `layer`, `name`, `raw_type`, `user_text` (clave/valor), `group_ids`, `group_names`, o `bbox` (comparación componente a componente con tolerancia `bbox_tolerance`).
