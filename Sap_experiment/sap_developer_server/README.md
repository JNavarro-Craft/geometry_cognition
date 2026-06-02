# sap_developer_server

MCP que consume el [`sap_bridge`](../sap_bridge/) sobre HTTP. **Primer consumidor** del
bridge (Objetivo 1). Read-only y estrictamente agnóstico: relaya hechos del bridge al
LLM y **no añade interpretación estructural**.

## Tools (3, read-only)

| Tool | Hecho que expone | Llama a |
|---|---|---|
| `get_joints` | puntos: nombre, coords globales, restraints 6-DOF | `GET /v1/joints` |
| `get_frames` | frames: nombre, conectividad `point_i`/`point_j`, sección | `GET /v1/frames` |
| `get_sections` | catálogo de secciones: nombre + tipo SAP | `GET /v1/sections` |

Cada tool devuelve el JSON del bridge esencialmente verbatim, o un envelope honesto
`{error: bridge_unavailable, message, hint}` si el bridge no responde. Ningún tool
clasifica, verifica ni nombra dominio (sin `is_*`, `verify_*`, `check_*`).

## Contenido

- `bridge_backend.py` — cliente HTTP del bridge (transporte; espeja
  `gc_mcp/rhino_bridge_client/bridge_backend.py`; surface el `{code,message}` del bridge
  en errores no-2xx).
- `tools.py` — lógica de los tools (relay + envelope de error).
- `server.py` — entrypoint FastMCP (`mcp.run()`), registra los 3 tools.

## Variables de entorno

- `SAP_BRIDGE_BASE_URL` — base URL del bridge (default `http://127.0.0.1:8766`).
- `SAP_BRIDGE_TIMEOUT_SECONDS` — timeout HTTP (default `10`).

## Registrar en Claude Desktop

En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sap_developer_server": {
      "command": "python",
      "args": ["-m", "Sap_experiment.sap_developer_server.server"],
      "env": {
        "PYTHONPATH": "i:\\Mi unidad\\geometry_cognition",
        "SAP_BRIDGE_BASE_URL": "http://127.0.0.1:8766"
      }
    }
  }
}
```

El bridge debe estar corriendo y SAP2000 abierto con un modelo (attach-only).
