# SAP_AI.md — síntesis del experimento SAP

Complemento de [`docs/agnostic_principle.md`](docs/agnostic_principle.md): aquél explica
*por qué* el bridge se diseña agnóstico; este registra *qué se logró* en esta sesión y
*qué queda fuera*, manteniendo el límite agnóstico como filtro de toda mejora futura.

Marcadores: ✅ logrado y validado en vivo · ◾ fuera por diseño en esta fase ·
🔶 hallazgo / pendiente documentado.

> **Cruce al write-side (sesión 8).** Tras 17 primitivas read-only, el experimento cruza
> a escritura. Las reglas del write-side están consolidadas en
> [`docs/write_side_design.md`](docs/write_side_design.md) — **autoridad arquitectónica:
> toda primitiva write debe ajustarse a ella** (namespace por prefijo, dry-run, savepoints,
> stop-on-first-failure, confirm). Los patrones del consumidor en
> [`docs/client_patterns.md`](docs/client_patterns.md). La Fase 1g.1 implementa solo la
> **infraestructura de undo** (savepoints); las primitivas write "reales" (set_active_dof,
> create_section…) vienen después, apoyadas en ella.

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
| Config del modelo (DOFs + units) | `GET /v1/model/settings` | `get_model_settings` | ✅ active_dof [T,F,T,F,T,F]; locked; present+database units; sin nombrar el patrón (cliente reconoce Plane Frame) |
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
| 🔶 **Savepoint: crear (WRITE fs)** | `POST /v1/savepoints` | `create_savepoint` | ✅ escribe `<model>__sp_<name>.sdb`; dry_run; rechaza duplicado; Save+reabrir original |
| 🔶 **Savepoint: restaurar (WRITE destr.)** | `POST /v1/savepoints/{name}/restore` | `restore_savepoint` | ✅ confirm obligatorio; dry_run; ciclo undo validado (revierte cambio real de active_dof) |
| Savepoint: listar | `GET /v1/savepoints` | `list_savepoints` | ✅ scan de filesystem; [] si ninguno; sin OAPI |
| 🔶 **set_active_dof (MUTA modelo)** | `POST /v1/model/settings/active_dof` | `set_active_dof` | ✅ confirm obligatorio; dry_run con diff legible; locked → rechaza; ciclo cliente validado |
| 🔶 **set_present_units (MUTA modelo)** | `POST /v1/model/settings/present_units` | `set_present_units` | ✅ name→enum; confirm + dry_run; TEST KEY: propagación a read-side (fuerzas ×9.80665, distancias intactas) |
| 🔶 **create_material (CREA objeto)** | `POST /v1/materials` | `create_material` | ✅ prefijo AI_ obligatorio; tipo→eMatType (no 'Wood'); rechaza duplicado (overwrite silencioso); dry_run |
| 🔶 **set_material_properties_isotropic** | `POST /v1/materials/{name}/properties/isotropic` | `set_material_properties_isotropic` | ✅ confirm solo si preexistente (§5.1); dry_run con diff; G derivado por SAP; present units |
| 🔶 **create_rectangular_section (CREA)** | `POST /v1/sections` | `create_rectangular_section` | ✅ prefijo + material existe + dims>0; rechaza duplicado (overwrite silencioso); lee color real de SAP |
| 🔶 **modify_rectangular_section** | `PATCH /v1/sections/{name}` | `modify_rectangular_section` | ✅ merge selectivo; confirm si preexistente; section_type_mismatch / nothing_to_modify |
| 🔶 **assign_section_to_frames (BATCH)** | `POST /v1/sections/{name}/assign-to-frames` | `assign_section_to_frames` | ✅ 1 sección→N frames; pre-validación estricta; confirm; hint >10; applied/failed_at/not_attempted |
| 🔶 **assign_sections_to_frames (BATCH het.)** | `POST /v1/sections/assign-batch` | `assign_sections_to_frames` | ✅ mapping frame→sección; loop interno (sin batch nativo OAPI); mismo shape |
| 🔶 **set_model_locked (estado global)** | `POST /v1/model/locked` | `set_model_locked` | ✅ unlock tras analyze (cierra loop iterativo); confirm; idempotente; NO auto-unlock |
| 🔶 **open_model (reemplaza modelo)** | `POST /v1/model/open` | `open_model` | ✅ valida path en fs antes de OpenFile (evita estado fantasma); confirm; el modelo abierto pasa a ser base + workspace fresco |
| 🔶 **reset_workspace (regenera)** | `POST /v1/workspace/reset` | `reset_workspace` | ✅ regenera workspace desde base inmutable; confirm; base byte-intacto verificado |
| 🔶 **new_blank_model (modelo vacío)** | `POST /v1/model/new_blank` | `new_blank_model` | ✅ InitializeNewModel(units) **+ NewBlank() (§32, lo hace construible)**; DESTRUCTIVO→confirm; workspace temp sin base file; 0 joints/frames |
| 🔶 **save_workspace_as (materializa)** | `POST /v1/workspace/save_as` | `save_workspace_as` | ✅ guarda workspace→nuevo base inmutable; prohíbe path==base actual (commit futuro); confirm solo si sobrescribe; re-anchora workspace fresco; **rechaza modelo vacío** (`empty_model`, §31) |
| 🔶 **create_joint / create_joints** | `POST /v1/joints` `/batch` | `create_joint(s)` | ✅ AddCartesian; naming híbrido (AI_ o autogen AI_J###); confirm; batch atómico; M2 read-back |
| 🔶 **create_frame / create_frames** | `POST /v1/frames` `/batch` | `create_frame(s)` | ✅ AddByPoint; valida ambos joints; sección opcional; autogen AI_F###; batch atómico |
| 🔶 **delete_joint** | `DELETE /v1/joints/{name}` | `delete_joint` | ✅ DeleteSpecialPoint (§33); rechaza si tiene frames conectados (`joint_has_connected_frames`, lista); confirm |
| 🔶 **delete_frame** | `DELETE /v1/frames/{name}` | `delete_frame` | ✅ FrameObj.Delete; sin constraint de cascada; confirm; dry_run reporta endpoints |
| 🔶 **modify_joint (mueve)** | `PATCH /v1/joints/{name}` | `modify_joint` | ✅ ChangeCoordinates_1; lista frames afectados; confirm; M2 |
| 🔶 **modify_frame (in-place)** | `PATCH /v1/frames/{name}` | `modify_frame` | ✅ ChangeConnectivity in-place (preserva releases, §33) + SetSection; ≥1 campo; confirm |
| 🔶 **set_frame_releases** | `POST /v1/frames/{name}/releases` | `set_frame_releases` | ✅ flags nombrados {U1..R3}→array [orden §33]; confirm; dry_run diff; SAP rechaza inestables→oapi_call_failed |
| 🔶 **set_joint_restraints / _batch** | `POST /v1/joints/{name}/restraints` `/restraints/batch` | `set_joint_restraints(_batch)` | ✅ apoyos 6-DOF, flags nombrados {U1..R3}; SetRestraint sobrescribe (M1); confirm; batch atómico; sin dominio (pinned/fixed los compone el cliente) |
| Restraints de UN joint | `GET /v1/joints/{name}/restraints` | `get_joint_restraints` | ✅ los 6 flags crudos; lookup puntual (get_joints trae los de todos) |
| 🔶 **create_load_pattern** | `POST /v1/load_patterns` | `create_load_pattern` | ✅ prefijo AI_; tipo case-insensitive off el enum (§36); confirm; blank trae solo DEAD; Add rechaza duplicado |
| 🔶 **assign_joint_load / _batch** | `POST /v1/joints/{name}/loads` `/loads/batch` | `assign_joint_load(s_batch)` | ✅ {F1..M3} nombrados; ACUMULA (Replace=False); valida joint+pattern; confirm; batch atómico |
| 🔶 **clear_joint_loads** | `DELETE /v1/joints/{name}/loads` | `clear_joint_loads` | ✅ por pattern o todos; DeleteLoadForce limpia de verdad (≠§34); confirm |
| Cargas de UN joint | `GET /v1/joints/{name}/loads` | `get_joint_loads` | ✅ una entrada por carga (acumula como entradas separadas); 6 componentes + coord_sys |
| 🔶 **assign_frame_load_distributed / _batch** | `POST /v1/frames/{name}/loads/distributed` `/batch` | `assign_frame_load_distributed(_batch)` | ✅ uniforme; direction→(Dir,CSys) §35; Force/Moment; ACUMULA; confirm |
| 🔶 **assign_frame_load_point / _batch** | `POST /v1/frames/{name}/loads/point` `/batch` | `assign_frame_load_point(_batch)` | ✅ distancia rel/abs; mismo mapeo direction §35; ACUMULA; confirm |
| 🔶 **clear_frame_loads** | `DELETE /v1/frames/{name}/loads` | `clear_frame_loads` | ✅ por pattern/kind (distributed/point/ambos); Delete*Load limpian de verdad; confirm |
| Cargas de UN frame | `GET /v1/frames/{name}/loads` | `get_frame_loads` | ✅ {distributed:[...], point:[...]}; direction (nombre+Dir code), extents/distancia, valores |
| Errores estructurados `{error,code,message}` | todos | envelope `bridge_unavailable` | ✅ 409/502 honestos; `case_not_run`, `confirm_required`, `savepoint_not_found`, `invalid_path`, `empty_model`, `joint_has_connected_frames` |

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

> Actualización sesión 15 (Fase 1g.9 — workspace pattern, §28 RESUELTO): el bridge hace
> auto-`Save(workspace)` al primer attach y opera SIEMPRE sobre el `<base>__workspace.sdb`;
> el modelo base del usuario **nunca se escribe** en el flujo default (verificado: md5 del
> base byte-idéntico tras una iteración doble completa). `reset_workspace` regenera el
> workspace desde el base limpio; savepoints y open_model **re-anchoran** al workspace tras
> cada operación (resuelve el filo §19 proactivamente). **31 primitivas.** El test crítico
> de §28 PASA: dos iteraciones del caso real (cuerda 33x73→41x95) dan baseline y resultados
> IDÉNTICOS (-0.66363 / -0.68435 mm), donde en 1g.8 la iteración 2 leía estado contaminado.
> Diseñado future-aware: helpers genéricos (`ensure_workspace_from_current_model`,
> `reanchor_to_workspace`, `_compute_workspace_path`), `base_model_path` mutable+Optional,
> `sap_instance_origin` para un futuro `launch_sap`. El loop de verificación iterativo del
> Objetivo 1 queda completo y robusto.

> Actualización sesión 16 (Fase 1h.1 — construir desde cero, infraestructura): el bridge ya
> **no** requiere un modelo base preexistente. Dos primitivas nuevas abren y cierran el ciclo
> build-from-blank: `new_blank_model(units)` (`InitializeNewModel` → modelo vacío en memoria;
> DESTRUCTIVO, descarta lo cargado sin guardar → confirm; monta un **workspace temporal**
> en `%TEMP%/sap_bridge_sessions/<session_id>/` con `base_model_path=None`) y
> `save_workspace_as(path)` (materializa el workspace a disco como **nuevo base inmutable** y
> re-anchora sobre un workspace fresco al lado — el patrón normal resume). **33 primitivas.**
> Future-aware: `_compute_workspace_path` ahora es función PURA que maneja base=None;
> `_save_to_path_and_update_state(path, allow_base_overwrite)` es el helper compartido del que
> un futuro `commit_workspace_to_base` colgará con el flag invertido; `session_id` (UUID al
> construir la sesión) ancla el workspace temp y habilita un futuro cleanup por sesión;
> `_initialize_from(source)` deja el seam para `new_from_template`. El attach ya tolera "SAP
> abierto sin modelo" (GetModelFilename no-absoluto → base/workspace=None, esperando
> new_blank_model u open_model). Fuera de esta fase: `launch_sap`, `new_from_template`,
> `commit_workspace_to_base`, cleanup automático del temp, y las primitivas de **construcción**
> (create_joint/frame, restraints — 1h.2+) que poblarán el modelo vacío.
>
> **Validado end-to-end en vivo** (SAP26, attach sin modelo): fases attach-graceful, new_blank
> (dry_run + gate confirm + apply), operar sobre el blank (0 joints/frames, 3 materiales default),
> save_workspace_as (dry_run + apply + los 3 gates de path + overwrite con/sin confirm). La
> validación por uso real **descubrió** (§31): (a) `Save` sobre un modelo vacío crea un `.sdb`
> que `OpenFile` rechaza y que **cuelga la OAPI con un diálogo modal** → se agregó el guard
> `empty_model` (rechaza guardar un modelo sin geometría antes de tocar disco); (b) un bug real
> (`import os` faltante en `workspace.py`) que solo saltaba en el segundo `save_workspace_as`.
> Ambos invisibles a los tests por-primitiva — exactamente el valor del anti-patrón #6.

> Actualización sesión 17 (Fase 1h.2 — geometry primitives + §31 RESUELTO DE RAÍZ): el bridge
> ya **construye wireframe estructural desde cero**. 9 primitivas nuevas (**42 en total**):
> `create_joint(s)`, `create_frame(s)`, `delete_joint`, `delete_frame`, `modify_joint`,
> `modify_frame`, `set_frame_releases`. Tres patrones propios: **naming híbrido** (name explícito
> con prefijo AI_, o autogen `AI_J###`/`AI_F###` por contador de sesión reseteable en
> reset_workspace), **batch atómico** (`apply_batch_atomic`, stop-on-first-failure generalizado de
> 1g.7, reusable por 1h.3-1h.4), y **delete con frame-connection check** (`delete_joint` rechaza un
> joint con frames conectados, listándolos). `modify_frame` cambia endpoints **in-place** con
> `EditFrame.ChangeConnectivity` (§33, preserva releases). **El pre-vuelo (anti-patrón #5)
> descubrió la CAUSA RAÍZ de §31**: `InitializeNewModel` deja el modelo INERTE — falta
> `cFile.NewBlank()` para que `AddCartesian`/`AddByPoint` funcionen y el `Save` produzca un `.sdb`
> reabrible (§32). Se arregló `new_blank_model` (lo llama ahora); el guard `empty_model` queda como
> defensa secundaria. Otras firmas verificadas (§33): joints se borran con `DeleteSpecialPoint` (NO
> `.Delete`), releases en orden `[U1,U2,U3,R1,R2,R3]`. **Validación end-to-end: construir una cercha
> triangular desde blank (3 joints + 3 frames + releases + material + sección), las 7 fases A-G
> PASARON**, incluido el test crítico: `save_workspace_as` → `open_model` **reabre limpio, sin el
> diálogo modal de §31** (con geometría el `.sdb` pesa 9 KB + `.$2k`, es un modelo real); la
> geometría persiste tras reabrir. **§31 resuelto de raíz, no solo con el guard.** La validación NO
> reveló bugs nuevos — las 9 primitivas funcionaron a la primera. Future-aware: `apply_batch_atomic`
> y `get_frames_connected_to_joint` (patrón "referencias a X") listos para 1h.3 (restraints) /
> 1h.4 (cargas). Fuera de fase: restraints, cargas, `launch_sap`, `commit_workspace_to_base`.

> Actualización sesión 18 (Fase 1h.3 — joint restraints / apoyos 6-DOF): 3 primitivas (**45 en
> total**): `set_joint_restraints` + `set_joint_restraints_batch` (write) + `get_joint_restraints`
> (read puntual). Con esto la cercha de 1h.2 ya puede **apoyarse** — falta solo 1h.4 (cargas) para
> analizar desde cero. Mismo patrón que `set_frame_releases`: **flags nombrados** `{U1..R3}` (el
> cliente no recuerda el orden), el bridge mapea al array posicional. **Sin patrones de dominio**:
> el bridge expone los 6 flags crudos, "pinned"/"fixed"/"roller" los compone el cliente
> (anti-patrón #4). Pre-vuelo (§34): `SetRestraint` sobrescribe el estado completo (M1); orden
> `[U1,U2,U3,R1,R2,R3]` (= releases); ⚠️ **`DeleteRestraint` retorna 0 pero NO limpia los flags** →
> el bridge libera un apoyo con `SetRestraint(all-False)`, no `DeleteRestraint` (no se expone).
> **Validación end-to-end** (apoyar la cercha: AI_J001 pinned U1/U2/U3 + AI_apoyo_der roller U3):
> dry_run + apply (single y batch), `get_joint_restraints` puntual coincide, `get_joints` masivo
> refleja los apoyos, **persisten tras save→reopen**, y liberar (all-False) limpia correctamente
> (§34 confirmado). Sin bugs nuevos — las 3 primitivas a la primera. Reusó `apply_batch_atomic` de
> 1h.2. Fuera de fase: cargas (1h.4), springs/constraints/local-axes.

> Actualización sesión 19 (Fase 1h.4 — loads / cargas; CIERRE del ciclo construir-cargar-analizar):
> **el prompt aspiracional del ciclo 1h.* es ejecutable**: una cercha construida ÍNTEGRAMENTE desde
> un blank (geometría + sección + apoyos + cargas) se ANALIZA y da resultados físicamente correctos.
> 12 primitivas (**56 tools MCP** — el `list_load_patterns` ya era `get_load_patterns` de 1c):
> `create_load_pattern`; `assign_joint_load(_batch)`/`clear_joint_loads`/`get_joint_loads`;
> `assign_frame_load_distributed(_batch)`/`assign_frame_load_point(_batch)`/`clear_frame_loads`/
> `get_frame_loads`. **Semántica ACUMULAR** (`Replace=False`, decisión de scoping): re-asignar suma;
> "set" = `clear_*` + `assign` (el cliente compone). El pre-vuelo (el más cargado de anti-patrón #5
> del ciclo) mapeó el **enum `Dir` de frame loads** (§35): Int32 crudo ACOPLADO a CSys (1-3 ejes
> locales exigen CSys=Local; 4-6 X/Y/Z; 10 Gravity), resuelto por `resolve_load_direction(direction,
> coord_sys)→(Dir,CSys)`. Otros hallazgos (§36): `eLoadPatternType` CamelCase (Dead/Live, NO LTYPE_*),
> `Add` rechaza duplicado, blank trae solo DEAD, orden `[F1,F2,F3,M1,M2,M3]`, `Delete*Load` SÍ
> limpian (≠§34). **Validación A-G**: cercha completa, `create_load_pattern` + gate
> unknown_load_pattern_type, joint/frame loads assign/get/clear/batch, y el test culminante:
> **`run_analysis` → Finished; AI_J002 u3=-0.485 mm; AI_F002 axial -833 kgf constante (cercha:
> axial dominante, momentos ~0), coherente con el equilibrio del nudo a 37°**; cargas persisten tras
> save→reopen; 12 ops auditadas. **Sin bugs nuevos — 3a fase consecutiva a la primera.** Nota: la
> acumulación de joint loads crea entradas SEPARADAS (el `get` las reporta múltiples; SAP las suma en
> el análisis; el bridge relaya, no consolida — agnóstico). Fuera de fase: trapezoidal/temperature
> loads, load combinations, springs, 1h.5 (validación multi-panel + extras).

> Actualización sesión 14 (Fase 1g.8 — workflow iterativo robusto + tercer bloqueante):
> resuelve los 2 bloqueantes de §26: `set_model_locked` (unlock tras analyze → cierra el loop
> modificar→analizar→modificar) + `open_model` (recupera el modelo base tras restore; valida
> path en fs antes de OpenFile para evitar el estado fantasma de SAP) + fix de naming de
> savepoints (resolver contra el modelo BASE, no anidar — §26). **30 primitivas.** Validado en
> vivo: savepoint reflow (checkpoint tras restore no anida, restore lo encuentra), y el caso
> real ejecutado ITERATIVAMENTE. **PERO la iteración doble reveló un TERCER bloqueante más
> profundo (§28): el modelo base en DISCO se contamina** — restore protege la memoria, no el
> archivo base; el modelo del usuario y el workspace del bridge son el mismo archivo. Requiere
> decisión arquitectónica (modelo base inmutable / workspace separado) — candidato a 1g.9, más
> urgente que deletes. Anti-patrón #6 confirmado de nuevo: solo la iteración real lo reveló.

> Actualización sesión 13 (Fase 1g.7 — primera operación BATCH sobre preexistentes):
> `assign_section_to_frames` (homogénea, 1 sección→N frames) + `assign_sections_to_frames`
> (heterogénea, mapping). **28 primitivas**. La OAPI no tiene batch heterogéneo nativo →
> el bridge compone un loop sobre `SetSection` (§25); la API externa es la misma. Ejercita
> la decisión #4 (applied/failed_at/not_attempted, stop-on-first-failure): **pre-validación
> estricta** antes del loop → en flujo normal nunca hay failed_at (reservado para fallo OAPI
> a mitad de loop). confirm obligatorio; hint >10; idempotencia reportada como aplicada;
> lee de vuelta cada frame (M2). **Cierra el loop práctico de verificación** (crear sección →
> asignar → analizar → leer → restaurar), ahora ejecutable — ver client_patterns Patrón 7.
> Meta-principios M1/M2 formalizados en brechas.

> Actualización sesión 12 (Fase 1g.5 — el patrón create+modify generaliza): segundo object
> type, secciones rectangulares. `create_rectangular_section` (prefijo + material existente +
> dims>0; rechaza duplicado porque `SetRectangle` sobrescribe en silencio como SetMaterial;
> lee el color real de SAP de vuelta) + `modify_rectangular_section` (merge de campos provistos
> con el current state; confirm solo si preexistente §5.1; `section_type_mismatch`,
> `nothing_to_modify`). **26 primitivas**. La plantilla de 1g.4 se replicó sin fricción —
> queda validada como reusable para object types. PATCH para modify, POST para create.

> Actualización sesión 11 (Fase 1g.4 — SALTO CUALITATIVO, primer write sobre objetos):
> `namespace.py` lleva el prefijo del bridge (`AI_`, configurable por `BRIDGE_NAMESPACE_PREFIX`)
> a código por primera vez — enforcement universal en todo `create_<noun>`. `create_material`
> (crea en el namespace propio; tipo→eMatType, **no hay 'Wood'**, madera es `NoDesign`;
> rechaza duplicado porque SAP sobrescribe en silencio) + `set_material_properties_isotropic`
> (confirm solo si el material es preexistente del usuario, §5.1; G derivado por SAP; valores
> en present units, el bridge no convierte). **24 primitivas**. Atómicas separadas (crear vs
> configurar). Ciclo de 13 pasos validado, incl. que el savepoint revierte en bloque el
> material nuevo Y la modificación a un preexistente.

> Actualización sesión 10 (Fase 1g.3 — generalización de la plantilla write):
> `set_present_units` (`POST /v1/model/settings/present_units`) cambia el sistema de
> unidades de *display* por NOMBRE (name→enum vía getattr; `unknown_unit_system` si no
> existe). Setting global → confirm + dry_run + audit, siguiendo la plantilla de 1g.2 sin
> fricción. **22 primitivas**. **TEST KEY validado**: tras cambiar a N_m_C, el read-side
> reporta consistentemente — distancias intactas (metros), fuerzas ×9.80665 (kgf→N); el
> bridge NO convierte, SAP reformatea y el bridge relaya. database_units no se toca.

> Actualización sesión 9 (Fase 1g.2 — primer write que MUTA el modelo): `set_active_dof`
> (`POST /v1/model/settings/active_dof`) cambia los DOFs activos en memoria. Setting global
> → **confirm obligatorio** (design doc §5.3, primera vez que se USA en código); dry_run
> previsualiza con diff legible (`U2: false → true`). El bridge valida **shape** (6 booleans),
> NO juzga el patrón (SAP acepta hasta all-false) ni auto-deslockea (locked → relay
> `oapi_call_failed`). Más **audit logging** compartido (`audit_log.py` → JSONL por op,
> errores incluidos) con retrofit a savepoints. **21 primitivas**. Ciclo del patrón cliente
> validado end-to-end: savepoint → preview → rechazo-sin-confirm → aplicar → restore.

> Actualización sesión 8 (Fase 1g.1 — primer write-side): `create_savepoint`,
> `restore_savepoint`, `list_savepoints` — la **infraestructura de undo**. Escriben el
> **filesystem** (`<model>__sp_<name>.sdb`), NO el modelo en memoria. **20 primitivas**
> (17 read + run_analysis + savepoints). Gobernadas por `write_side_design.md`. Hallazgos:
> `Save_2` no existe (solo `Save`, que actúa como "Save As" → create reabre el original);
> el handle sobrevive a `OpenFile` (no re-attach); restore deja la sesión en el archivo del
> savepoint (filo documentado). Ciclo de undo validado: revierte un cambio real de
> active_dof. confirm obligatorio en restore; rechazo de duplicado; dry_run en ambos.

> Actualización sesión 7 (Fase 1e.5 — último gap de read): `get_model_settings`
> (`GET /v1/model/settings`) expone el envelope estructural (active_dof + locked) y unidades
> (present + database). **17 primitivas**; cierra el lado de read antes del diseño del
> write-side. `active_dof` se relaya como vector crudo [U1..R3] (misma convención que joint
> restraints) — el bridge **no** lo nombra "Plane Frame"/"2D" (leak interpretativo; el
> cliente lo deriva). **Gap consciente, no olvido**: otras categorías de settings (solver,
> mass source, coord systems custom, project info, damping, design prefs) serán primitivas
> independientes cuando aparezca su caso de uso — no se agruparon en un "settings" genérico
> para no comprometer un shape antes de tiempo.

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
