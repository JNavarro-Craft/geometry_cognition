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
- `POST /geometry/extract_scene`
- `POST /geometry/extract_objects`

## Notas

- El acceso a `RhinoDoc.ActiveDoc` se ejecuta en UI thread para seguridad.
- El bridge devuelve JSON compacto, sin dumps de geometría cruda.

