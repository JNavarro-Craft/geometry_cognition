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

En Rhino, el comando `RhinoAI` levanta el servidor HTTP local.

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
- `POST /geometry/extract_scene`
- `POST /geometry/extract_objects`

## Notas

- El acceso a `RhinoDoc.ActiveDoc` se ejecuta en UI thread para seguridad.
- El bridge devuelve JSON compacto, sin dumps de geometría cruda.

