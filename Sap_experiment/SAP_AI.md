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
| Composición de UN load case | `GET /v1/load_cases/{name}/details` | `get_load_case_details` | ✅ LinearStatic → loads con SF; MODAL → unsupported_case_type=true; cierra asimetría con combos |
| Distributed loads en UN frame | `GET /v1/frames/{name}/loads/distributed` | `get_distributed_loads_on_frame` | ✅ 78/180 frames; Dir int→nombre (Gravity/Local 2); refs a patterns OK; camino vacío OK |
| Point loads en UN joint | `GET /v1/joints/{name}/loads/point` | `get_point_loads_on_joint` | ✅ camino vacío (0/112 en TEST_01); shape F1-3/M1-3 vs firma OAPI |
| Estado de análisis por case | `GET /v1/analysis/status` | `get_analysis_status` | ✅ 7 cases; status int→nombre; has_run; model_is_locked |
| 🔶 **Correr análisis (MUTA)** | `POST /v1/analysis/run` | `run_analysis` | ✅ 7 cases en 5.8s → Finished, modelo locked; subset con restauración de flags; idempotente; case inexistente → error |
| Desplazamientos de UN nudo | `GET /v1/joints/{name}/displacements/{case}` | `get_joint_displacements` | ✅ joint 9 restringido: u1-u3=0, solo r2≠0; vs UI |
| Reacciones de UN nudo | `GET /v1/joints/{name}/reactions/{case}` | `get_joint_reactions` | ✅ joint 9: F1/F3≠0 (coherente con restraints); equilibrio global F3=1290.86 kgf |
| Fuerzas internas de UNA barra | `GET /v1/frames/{name}/forces/{case}` | `get_frame_forces` | ✅ frame 4133: 2 stations, M3≠0, P axial cte; ?station opcional |
| Errores estructurados `{error,code,message}` | todos | envelope `bridge_unavailable` | ✅ 409/502 honestos; `case_not_run`, `unsupported_case_type` (MODAL), case inexistente |

**Lo que el cliente puede componer sobre estos hechos** (sin que el bridge lo haga):
unir frames↔joints por nombre de punto para reconstruir geometría; cruzar
`get_sections` ∩ `get_frames` para ver qué secciones se *definen* vs se *usan* (el
modelo define 6, usa 2 — el bridge expone ambos hechos, el cliente saca la diferencia).

---

## ◾ Explícitamente fuera de esta fase (por diseño)

No es deuda: es alcance acotado deliberadamente (ver el PROMPT MAESTRO de la sesión).

- ◾ **Escritura al MODELO** (create_joint/frame, set_section…). Read-only excepto correr
  análisis — ver nota del cruce abajo. La escritura al modelo es Fase 1g (tras design doc).
- ◾ **Stresses** (tensiones, 1e.2), **resultados de envelope/combos** (1e.3), **modal/
  spectrum** (1f). Los resultados LinearStatic (displ, react, forces) ya están — ver abajo.
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
> cases (tipo) y combos (tipo + items consolidados). Como hechos: 'ENVOLVENTE' se reporta
> combo_type 'Envelope', nunca una etiqueta sísmica; nombres en español relayados verbatim.

> Actualización sesión 4 (Fase 1c.2): las **cargas APLICADAS** y la **composición de case**
> ya **no** están fuera — `get_distributed_loads_on_frame`, `get_point_loads_on_joint`,
> `get_load_case_details` (LinearStatic; otros tipos → `unsupported_case_type`). Cierra el
> lado de inputs: con 11 primitivas se responde "qué define este modelo" sin correr
> análisis. Sigue fuera: point loads en frames, temperature/displacement loads (1c.3),
> detalles de cases no-LinearStatic. Hecho, no interpretación: `VIENTO` con dirección
> `Gravity` se reporta tal cual (anti-patrón #4); el nombre del pattern no implica función.

> Actualización sesión 5 (Fase 1d — CRUCE ARQUITECTÓNICO): primera operación que **MUTA**
> estado. `run_analysis` (`POST /v1/analysis/run`) corre el análisis — cambia el estado de
> *cómputo* (produce resultados, puede lockear el modelo), **no** la definición del modelo.
> `get_analysis_status` (`GET`) lee. El método HTTP señala intent: POST muta, GET lee. NO
> confirm (no destructivo, re-correr es idempotente); el confirm se exigirá en Fase 1g
> (escritura al modelo). Errores de análisis (singular matrix…) se relayan como
> `oapi_call_failed` con el código — el bridge nunca dice "tu modelo está mal".

> Actualización sesión 6 (Fase 1e — CICLO VERTICAL COMPLETO): los **resultados** ya **no**
> están fuera. `get_joint_displacements`, `get_joint_reactions`, `get_frame_forces` leen lo
> que el análisis produjo (LinearStatic), read-only post-análisis. Con **16 primitivas** el
> ciclo input→análisis→output está cerrado: el cliente puede preguntar qué define el modelo,
> correrlo, y leer solicitaciones. Dependen del estado de cómputo: case no corrido →
> `case_not_run` (el cliente llama run_analysis); no-LinearStatic → `unsupported_case_type`.
> Hecho, no juicio: un displacement grande es un número, no "falla" (anti-patrón #4); las
> reacciones equilibran las cargas pero ese cross-check lo compone el cliente, no el bridge.
> Sigue fuera: stresses (1e.2), envelope (1e.3), modal/spectrum (1f).

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
