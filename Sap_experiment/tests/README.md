# tests — validación manual contra modelo SAP real

No hay suite sintética (decisión de la sesión, igual que geometry_cognition). El **test
es el modelo real**: se valida cada primitiva contra la UI de SAP2000.

## Cómo se validó esta sesión

Con SAP2000 v26 abierto en el modelo del usuario (guardado en
[`../test_models/`](../test_models/)) y el bridge en `:8766`:

1. `GET /health` → `{status: ok, sap_attached, oapi_dll}` sin attach.
2. `GET /v1/units` → unidades activas (`kgf_m_C`).
3. `GET /v1/joints` → conteo, rangos de coords, patrones de restraint; cruzado contra
   la UI (Define/seleccionar joint → coords + restraints).
4. `GET /v1/frames` → conteo, secciones por frame, **integridad**: todos los i/j
   resuelven a un joint (0 huérfanos).
5. `GET /v1/sections` → catálogo; cruzado contra Define → Frame Sections; `Count()`
   coincide con la enumeración.

Resultados confirmados con el usuario: 112 joints, 180 frames, 6 secciones. Detalle en
[`../docs/brechas.md`](../docs/brechas.md).

## Reproducir

```powershell
$env:PYTHONPATH = "i:\Mi unidad\geometry_cognition"
# 1) abrir SAP2000 con un modelo (attach-only: el bridge no lo lanza)
# 2) levantar el bridge:
python -m uvicorn Sap_experiment.sap_bridge.main:app --host 127.0.0.1 --port 8766
# 3) en otra terminal, golpear los endpoints y cruzar contra la UI:
Invoke-RestMethod http://127.0.0.1:8766/v1/joints
```

Si un valor contradice la UI (coord, unidad, campo null que debería tener dato):
**detener, reportar con evidencia, esperar dirección.** Es la clase de bug silencioso
que se caza aquí.
