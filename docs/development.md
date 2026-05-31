# Desarrollo y pruebas

## Entorno Python

El proyecto requiere **Python 3.11+** (`pyproject.toml` → `requires-python >=3.11`).

El único Python preinstalado en algunas máquinas es el 3.9 embebido en Rhino
(`~/.rhinocode/py39-rh8/`), que **no sirve** para los tests (versión vieja, sin pytest).
No lo uses para correr la suite.

### venv: FUERA de Google Drive

El repo vive en una unidad de Google Drive (`g:\Mi unidad\geometry_cognition`). **No
crees el venv dentro del repo.** Un venv tiene miles de archivos pequeños que Drive
intentaría sincronizar: lentitud, conflictos de escritura mientras pip escribe, y quota
gastada en archivos trivialmente recreables.

El venv vive en disco local; el código se queda en Drive:

```
C:\dev\venvs\geometry_cognition   <- entorno (local, rápido, sin sync)
g:\Mi unidad\geometry_cognition   <- código (Drive)
```

### Crear el entorno (una vez)

```powershell
# 1. Instalar Python 3.12 (si no está)
winget install --id Python.Python.3.12 -e

# 2. Crear el venv en disco local (NO en Drive)
& "C:\Users\jesus\AppData\Local\Programs\Python\Python312\python.exe" -m venv "C:\dev\venvs\geometry_cognition"

# 3. Instalar dependencias (explícitas; NO usar "-e .", ver nota abajo)
& "C:\dev\venvs\geometry_cognition\Scripts\python.exe" -m pip install pytest jsonschema fastmcp mcp
```

> **No uses `pip install -e .`** en este repo. El `pyproject.toml` no declara qué
> paquetes empaquetar y hay varias carpetas top-level (`gc_mcp`, `shared`, `contracts`,
> …), así que setuptools falla con "multiple top-level packages discovered". No hace
> falta instalar el proyecto: pytest corre desde la raíz del repo y `gc_mcp` / `shared`
> se importan vía el cwd. (Los `server.py` también insertan `PROJECT_ROOT` en `sys.path`.)

## Correr los tests

Siempre desde la raíz del repo (para que `gc_mcp` y `shared` sean importables):

```powershell
cd "g:\Mi unidad\geometry_cognition"
$vpy = "C:\dev\venvs\geometry_cognition\Scripts\python.exe"

# Un módulo concreto:
& $vpy -m pytest tests/test_developer_server.py -q

# Toda la suite:
& $vpy -m pytest -q
```

O activando el entorno para una sesión interactiva:

```powershell
C:\dev\venvs\geometry_cognition\Scripts\Activate.ps1
cd "g:\Mi unidad\geometry_cognition"
pytest -q
```

## Estado conocido de la suite

A fecha de la consolidación del pipeline, `pytest -q` da aproximadamente
**92 passed, 7 failed, 1 skipped**. Los 7 fallos son **preexistentes y esperados**:
pertenecen a módulos archivados en `gc_mcp/_archive/` y a un workflow simplificado.

- `tests/test_hypothesis_engine.py`: prueba `hypothesis_engine`, hoy en `_archive/`.
- `tests/test_minimal_workflow.py`: llama `run(..., include_domain=True)`; el `run()`
  actual de `workflows/run_minimal_analysis.py` solo encadena
  `rhino_extractor → geometry_kernel` (evidence_graph / hypotheses / domain fueron
  archivados). El test quedó desincronizado con el pipeline simplificado.

Las áreas activas pasan limpio: `developer_server`, `rhino_extractor`,
`geometry_kernel`, smoke pipeline.

## Plugin Rhino (bridge C#)

Build:

```powershell
cd "g:\Mi unidad\geometry_cognition\rhino_bridge\plugin"
dotnet build RhinoPrefabGeometryPlugin.csproj
```

Compilar **no** reinstala el plugin en Rhino. Para que los cambios surtan efecto en una
sesión de Rhino hay que reinstalar el `.rhp` vía `PlugInManager → Install...` y
reiniciar (ver `rhino_bridge/README.md`).
