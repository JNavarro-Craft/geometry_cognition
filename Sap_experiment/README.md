# Sap_experiment

> **Experimento, no producción.** Réplica para SAP2000 de la arquitectura agnóstica de
> `geometry_cognition`: un **bridge HTTP** (integración única con SAP) y un **MCP** que
> lo consume. Read-only, 3 primitivas, validadas en vivo contra un modelo real.

## Qué hace (Objetivo 1)

El LLM (Claude) consulta SAP2000 a través de un MCP que llama a un bridge HTTP — igual
que `geometry_cognition` hace con Rhino. El bridge expone **hechos** del modelo
(coordenadas, conectividad, propiedades) y **no interpreta** dominio estructural.

```
  SAP2000 + cSapModel (COM)
        │  OAPI vía pythonnet
  ┌─────▼─────────────┐
  │  sap_bridge       │  FastAPI :8766 — integración única, contrato estable
  └─┬─────────┬───────┘
    │ HTTP    │ HTTP        (plugins Rhino / scripts: Objetivo 2, futuro)
  ┌─▼───────┐ │
  │ MCP     │ │
  │ sap_dev │ │
  │ _server │ │
  └─┬───────┘
    │ MCP protocol
  ┌─▼────┐
  │ LLM  │   ← esta sesión (Objetivo 1)
  └──────┘
```

El bridge **no** es "el backend del MCP": es un servicio compartido cuyo contrato debe
ser estable porque varios consumidores dependerán de él. El MCP es solo el primero.

## Estructura

```
Sap_experiment/
├── README.md                  ← este archivo
├── SAP_AI.md                  ← síntesis del dominio (✅/◾/🔶)
├── sap_bridge/                ← servicio HTTP sobre la OAPI
│   ├── main.py                  FastAPI app, :8766
│   ├── sap_session.py           sesión OAPI attach-only (pythonnet)
│   ├── contracts.py             modelos pydantic del contrato
│   ├── error_codes.py           modos de fallo honestos
│   ├── path_resolver.py         localizar SAP2000v1.dll
│   ├── primitives/              units, joints, frames, sections
│   └── README.md                ← CONTRATO HTTP (API pública)
├── sap_developer_server/      ← MCP que consume el bridge (primer cliente)
│   ├── server.py  tools.py  bridge_backend.py  README.md
├── docs/
│   ├── agnostic_principle.md    copia de geometry_cognition (el filtro)
│   └── brechas.md               hallazgos + pendientes de esta sesión
├── tests/                     ← validación manual contra modelo real
├── test_models/               ← .sdb (no versionados)
└── RhinoSAP/                  ← código C# heredado (referencia, no se reusa textual)
```

## Las 3 primitivas (read-only)

| MCP tool | Endpoint | Hecho |
|---|---|---|
| `get_joints` | `GET /v1/joints` | puntos: nombre, coords globales, restraints 6-DOF |
| `get_frames` | `GET /v1/frames` | frames: nombre, conectividad i/j, sección |
| `get_sections` | `GET /v1/sections` | catálogo de secciones: nombre + tipo SAP |

Contrato completo en [`sap_bridge/README.md`](sap_bridge/README.md).

## Cómo correr

```powershell
# 1) instalar deps del bridge
python -m pip install -r Sap_experiment/sap_bridge/requirements.txt

# 2) abrir SAP2000 con un modelo (attach-only: el bridge NO lo lanza)

# 3) levantar el bridge
$env:PYTHONPATH = "i:\Mi unidad\geometry_cognition"
python -m uvicorn Sap_experiment.sap_bridge.main:app --host 127.0.0.1 --port 8766

# 4) probar
Invoke-RestMethod http://127.0.0.1:8766/v1/joints
```

Registrar el MCP en Claude Desktop: ver [`sap_developer_server/README.md`](sap_developer_server/README.md).

## Validación

Sin tests sintéticos. Cada primitiva se validó **contra el modelo SAP real** del usuario,
cruzada contra la UI (112 joints, 180 frames, 6 secciones). Ver
[`tests/README.md`](tests/README.md) y [`docs/brechas.md`](docs/brechas.md).

## Límites (por diseño en esta fase)

Solo lectura. **Sin** escritura al modelo, cargas, análisis, resultados, modal,
snapshots/diff, ni dimensiones de sección. **Sin** dominio estructural en el código
(materiales, normas, factores): eso vive en el cliente. Próximas fases y deuda de
contrato (paginación, filtros, start-instance) en [`docs/brechas.md`](docs/brechas.md).

Eventualmente: migración a repo propio `sap_cognition`.
