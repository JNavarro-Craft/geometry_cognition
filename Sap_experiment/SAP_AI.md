# SAP_AI.md — síntesis del experimento SAP

Complemento de [`docs/agnostic_principle.md`](docs/agnostic_principle.md): aquél explica
*por qué* el bridge se diseña agnóstico; este registra *qué se logró* en esta sesión y
*qué queda fuera*, manteniendo el límite agnóstico como filtro de toda mejora futura.

Marcadores: ✅ logrado y validado en vivo · ◾ fuera por diseño en esta fase ·
🔶 hallazgo / pendiente documentado.

---

## Qué es esto (y qué no)

**Experimento, no producción.** Replica para SAP2000 la arquitectura agnóstica de
`geometry_cognition`: un **bridge HTTP** (integración única con SAP, contrato estable)
y un **MCP** que lo consume como primer cliente. El bridge expone **hechos** del modelo
SAP (coordenadas, conectividad, propiedades) y **no interpreta** nada estructural.

El bridge **no** es "el backend del MCP": es un servicio compartido. Hoy lo consume el
MCP; mañana lo consumirán plugins de Rhino y scripts (Objetivo 2), y eventualmente el
LLM operará esos plugins (Objetivo 3). Por eso su contrato se diseña estable desde el
día uno.

---

## ✅ Logrado y validado en vivo (SAP2000 v26, modelo real del usuario)

| Capacidad | Endpoint | MCP tool | Validación |
|---|---|---|---|
| Sesión OAPI attach-only vía pythonnet | — | — | ✅ attach a instancia abierta |
| Unidades activas como hecho | `GET /v1/units` | (interno) | ✅ `kgf_m_C` (code 8) |
| Salud del bridge (sin attach) | `GET /health` | — | ✅ `sap_attached` + dll resuelta |
| Puntos: nombre, coords globales, restraints 6-DOF | `GET /v1/joints` | `get_joints` | ✅ 112 joints, 30 con restraint, vs UI |
| Frames: nombre, conectividad i/j, sección | `GET /v1/frames` | `get_frames` | ✅ 180 frames, conectividad 180/180 vs UI |
| Catálogo de secciones: nombre + tipo SAP | `GET /v1/sections` | `get_sections` | ✅ 6 secciones Rectangular, Count()==6, vs UI |
| Catálogo de materiales: nombre, tipo, mecánicas | `GET /v1/materials` | `get_materials` | ✅ 5 materiales; MGP10=NoDesign E=1e9 W=480; Rebar/Tendon mecánicas null (no fabricadas) |
| Dimensiones + props de UNA sección | `GET /v1/sections/{name}/properties` | `get_section_properties` | ✅ MGP10_33x73 depth=0.073 width=0.033 area=0.002409 (=0.073×0.033) vs cálculo manual |
| Catálogo de load patterns | `GET /v1/load_patterns` | `get_load_patterns` | ✅ 6 patterns (DEAD/PESO PROPIO/MUERTA/VIVA/VIENTO/NIEVE); types + SW multiplier vs UI |
| Catálogo de load cases | `GET /v1/load_cases` | `get_load_cases` | ✅ 7 cases (incl. MODAL); overload sin filtro vs UI |
| Catálogo de combos + composición | `GET /v1/combinations` | `get_combinations` | ✅ 8 combos; arrays paralelos consolidados; ENVOLVENTE=Envelope; combo-of-combo; integridad referencial OK |
| Errores estructurados `{error,code,message}` | todos | envelope `bridge_unavailable` | ✅ 409/502 honestos; sección no soportada → `oapi_unexpected_shape` con el tipo |

**Lo que el cliente puede componer sobre estos hechos** (sin que el bridge lo haga):
unir frames↔joints por nombre de punto para reconstruir geometría; cruzar
`get_sections` ∩ `get_frames` para ver qué secciones se *definen* vs se *usan* (el
modelo define 6, usa 2 — el bridge expone ambos hechos, el cliente saca la diferencia).

---

## ◾ Explícitamente fuera de esta fase (por diseño)

No es deuda: es alcance acotado deliberadamente (ver el PROMPT MAESTRO de la sesión).

- ◾ **Escritura al modelo** (create_joint/frame, set_section…). Solo lectura.
- ◾ **Cargas APLICADAS a objetos** (point/distributed loads), **análisis, resultados, modal.**
- ◾ **Snapshots / diff.** (Cuando los read-only maduren.)
- ◾ **Plugins de Rhino sobre el bridge** (Objetivo 2) y **wrappers MCP de plugins**
  (Objetivo 3).

> Actualización sesión 2 (Fase 1b): **dimensiones geométricas de sección** ya **no** están
> fuera — `get_section_properties` resuelve `GetRectangle` (depth/width) + `GetSectProps`
> (área, inercias, etc.) para `Rectangular`. Otras formas devuelven `oapi_unexpected_shape`
> hasta añadir su extractor (aditivo). Y **materiales** (`get_materials`) exponen tipo +
> mecánicas básicas. Ambas como hechos: MGP10 se reporta `NoDesign`, no 'timber'.

> Actualización sesión 3 (Fase 1c): las **DEFINICIONES de carga** ya **no** están fuera —
> `get_load_patterns`, `get_load_cases`, `get_combinations` exponen patterns (tipo + SW),
> cases (tipo) y combos (tipo + items consolidados). Sigue fuera lo **aplicado** a objetos
> (Fase 1c.2) y los detalles internos de un case. Como hechos: 'ENVOLVENTE' se reporta
> combo_type 'Envelope', nunca una etiqueta sísmica; nombres en español relayados verbatim.

## 🚫 Fuera por principio (leaks — nunca van en el bridge ni el MCP)

Destilado de `RhinoSAP/` (el código C# heredado en [`RhinoSAP/`](RhinoSAP/)), que mezcla
bridge agnóstico con dominio Easywood. **No se replica:**

- 🚫 **`SapConfigurator`**: materiales (MGP10 con E/ν), 6 secciones predefinidas, 5 load
  patterns chilenos, 7 combinaciones NCh, DOFs XZ hardcodeados. → Todo eso es **dominio**;
  vive en markdown/YAML del cliente, no en código del bridge. El bridge no ofrece un
  `RunAllConfigurations`.
- 🚫 **`EW_Check_TensionParallel` / `_Bending` / `_Compression`**: NCh1198 codificada en
  C# (tablas Ftp, factores Kh/Kct, criterio OK). → El MCP **no** tiene `verify_*`,
  `check_*`, `is_overstressed_*`. El LLM razona la verificación sobre los hechos +
  conocimiento normativo del prompt.
- 🚫 **Sección por defecto** (`DefaultSectionName = "MGP10_33x73"` en `GH_PushCurvesToSAP`):
  cuando llegue la escritura, la sección será **parámetro obligatorio**, sin default.

## ✅ Patrones de `RhinoSAP/` que SÍ se reutilizaron (patrón, no copia)

- ✅ **`SapConnector`** → `sap_session.py`: attach / health-probe (`GetModelIsLocked`) /
  release COM disciplinado. Sesión attach-only con seam para "start" futuro.
- ✅ **`ErrorCodes`** → `error_codes.py`: enumeración honesta de modos de fallo.
- ✅ **`PathResolver`** → `path_resolver.py`: localizar la instalación SAP (aquí el
  `.dll` del OAPI en vez del `.exe`).
- 🔶 **`UnitConversion`**: NO se portó la conversión silenciosa. El bridge **expone**
  las unidades (`/v1/units`) y deja la conversión al cliente.
- 🔶 **`AssignFrameDistributedLoads`**: el mejor ejemplo agnóstico del código previo
  (todo desde inputs externos). Referencia para la fase de cargas, no para ahora.

---

## Dónde vive el conocimiento de dominio (no en el código)

El dominio estructural (madera MGP10, NCh1198, factores, recetas de verificación) **no**
entra al bridge ni al MCP. Cuando se pueble (fase posterior, ver brechas), irá a algo
como `docs/domains/structural/` — catálogos (`materiales/`, `secciones/`), reglas
(`codigos/NCh1198.md`), factores y recetas — que el **LLM cliente** consume para razonar.
El bridge sigue dando solo hechos.

---

## Cómo correr

Ver [`README.md`](README.md) (alcance + arranque) y
[`sap_bridge/README.md`](sap_bridge/README.md) (contrato HTTP). En una línea: abre
SAP2000 con un modelo (attach-only), levanta el bridge en `:8766`, registra el MCP en
Claude Desktop.

---

## 🔶 Hallazgos de esta sesión

Detalle en [`docs/brechas.md`](docs/brechas.md). Resumen:

- 🔶 pythonnet exige castear `Helper` → interfaz `cHelper` para ver `GetObject`.
- 🔶 los `ref`/`out` de la OAPI vuelven como **tupla** tras el valor de retorno.
- 🔶 `cPropFrame.GetNameList` **filtra** por tipo; no hay llamada "todos los tipos" →
  se itera el enum y se cruza contra `Count()`.
- 🔶 las coordenadas vienen con muchos decimales aun en `kgf_m_C` (modelo construido en
  otras unidades / desde Rhino): se **exponen tal cual**, el cliente convierte.
