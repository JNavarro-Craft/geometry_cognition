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

**Antes de usar el MCP, arranca el bridge con:** `./scripts/start_bridge.ps1`
(desde `Sap_experiment/`; deja la terminal ocupada — el bridge corre en primer plano).

```powershell
# 1) instalar deps del bridge (una vez)
python -m pip install -r Sap_experiment/sap_bridge/requirements.txt

# 2) abrir SAP2000 con un modelo (attach-only: el bridge NO lo lanza)

# 3) levantar el bridge (one-liner)
./scripts/start_bridge.ps1

# 4) probar
Invoke-RestMethod http://127.0.0.1:8766/v1/joints
```

Registrar el MCP en Claude Desktop: ver [`sap_developer_server/README.md`](sap_developer_server/README.md).

### Orden operacional recomendado

1. **Abrir SAP2000** con el modelo.
2. **Arrancar el bridge** (`./scripts/start_bridge.ps1`).
3. **Registrar el MCP / abrir Claude.**

Técnicamente el bridge puede arrancarse antes o después de SAP — el attach a la sesión OAPI
es *lazy* (ocurre en la primera llamada `/v1/*`, no al arrancar), así que el orden no rompe
nada hoy. Pero como práctica operacional conviene seguir ese orden: deja un punto único de
diagnóstico si SAP no abre bien, y evita confusión en casos futuros donde el orden sí importe.

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
