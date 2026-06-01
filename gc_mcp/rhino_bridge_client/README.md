# rhino_bridge_client

Capa de **transporte**, no un MCP de cara al usuario. Es el cliente del bridge HTTP
de Rhino y el normalizador de sus respuestas. `developer_server` lo importa como
librería; cualquier MCP futuro que necesite leer el modelo Rhino (p. ej. un
`automation` que lo mute) reutilizaría esta misma capa.

- Rol: transporte + normalización. No se conecta como servidor MCP en uso normal.
- Puede: hablar con el bridge (`bridge_backend`) y normalizar objetos a
  `object_schema.v1.json` (`backend_adapter`); además cargar desde `.3dm`/`.json`
  local (`tools.extract_objects`).
- NO puede: inferir verdad constructiva ni etiquetas de dominio. Estrictamente agnóstico.
- Output: objetos normalizados + advertencias de extracción.

## Contenido

- `bridge_backend.py` — cliente HTTP del bridge: funciones `live_*_bridge`
  (query, contacts, distance, nearby, elements, definitions, project…) + paginación
  interna del fetch de escena. **Usado por `developer_server`.**
- `backend_adapter.py` — `_normalize_bridge_objects` y `extract_objects`: traducen la
  respuesta del bridge al schema neutral. **Usado por `developer_server`.**
- `tools.py` — `extract_objects`: carga desde fuente local (`.3dm`/`.json`) o vía
  backend. Cubierto por tests; no lo usa `developer_server`.
- `server.py` — wrapper FastMCP histórico (`extract_objects_tool`). No se conecta hoy;
  se conserva por su test y como referencia del rol de extractor.

## Nota de nombre

Antes se llamaba `rhino_extractor` y fue un MCP propio. Hoy su valor activo es la
capa de transporte que consume `developer_server`; el rename a `rhino_bridge_client`
comunica ese rol y evita confundirlo con un MCP conectado.
