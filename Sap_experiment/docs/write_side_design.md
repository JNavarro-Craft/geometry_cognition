# Write-Side Design — sap_experiment

## Propósito

Este documento define cómo funcionará el lado de escritura (write-side) del `sap_bridge`. Es la consolidación de cinco decisiones arquitectónicas tomadas antes de codificar la primera primitiva write. **Toda primitiva write futura debe ajustarse a este documento.**

NO cubre: el código específico de cada primitiva (eso queda para los prompts de fase), ni el roadmap de qué primitivas se implementan en qué orden.

## Principios fundamentales

1. **Agnóstico**: ninguna primitiva interpreta dominio. El bridge expone HECHOS sobre cambios al modelo, no JUICIOS sobre su validez estructural.
2. **Primitivas atómicas pequeñas**: cada primitiva corresponde a UNA operación fundamental SAP. Sin compuestas tipo `create_and_assign`.
3. **Composición del lado cliente**: el cliente (LLM, plugin Rhino, script) compone operaciones complejas a partir de primitivas atómicas.
4. **Reporte honesto de fallos**: ante error, el bridge reporta exactamente qué se aplicó y qué no. No oculta estado parcial.

## Las cinco decisiones

### 1. Namespace por prefijo configurable

**Regla**: todo objeto creado por un consumidor del bridge lleva un prefijo en su nombre. El prefijo es configurable por consumidor (default `AI_` para el MCP de Claude; otros pueden ser `RHINO_`, `EW_AUTO_`, etc.).

**Comportamiento**:
- **Crear nuevo** sin prefijo: rechazado con error `prefix_required`.
- **Modificar/borrar** objeto sin prefijo: requiere `confirm=true`.
- **Modificar** objeto con prefijo propio: permitido sin confirm.
- **Borrar** objeto con prefijo propio: requiere `confirm=true` (borrar es siempre confirmable).

**Configuración**: variable de entorno `BRIDGE_NAMESPACE_PREFIX` al arrancar el bridge (default `AI_`), o parámetro de request avanzado para escenarios multi-consumidor.

### 2. Dry-run opcional via flag

**Regla**: cada primitiva write acepta un flag `dry_run: bool` (default `false`). Si `true`, retorna preview detallado sin aplicar cambios.

Shape del response en dry-run:
```json
{
  "dry_run": true,
  "would_apply": { "...": "detalle del cambio" },
  "validation_passed": true
}
```

Shape en ejecución real:
```json
{
  "dry_run": false,
  "applied": { "...": "mismo shape que would_apply" }
}
```

**Hint policy**: para operaciones batch que afectan >10 objetos, el bridge agrega un campo `hint` en la respuesta sugiriendo dry_run. Sugerencia, no enforcement.

### 3. Undo via savepoints explícitos

**Regla**: el bridge NO mantiene snapshots automáticos ni undo transaccional. Provee tres primitivas explícitas:

- `create_savepoint(name)` → guarda el estado actual del modelo en archivo `.sdb` separado
- `restore_savepoint(name)` → abre el archivo, reemplazando el modelo actual. Requiere `confirm=true`
- `list_savepoints()` → enumera savepoints existentes

Implementación: `cFile.Save` y `cFile.OpenFile(path)` (NO `Save_2` — no existe en SAP26, ver brechas §18). Sin serialización custom.

**Convención reservada `__sp_` (Fase 1g.8).** El sufijo `__sp_<name>` en el nombre de archivo es **reservado por el bridge** para savepoints. Tras un `restore_savepoint`, la sesión queda cargada en el archivo del savepoint (`<base>__sp_<name>.sdb`); para evitar que un siguiente create/restore anide los nombres recursivamente (`__sp_X__sp_Y` — el bug que §26 reveló), todas las primitivas de savepoint resuelven el path contra el **modelo BASE** (stripeando recursivamente cualquier `__sp_*` del nombre cargado), no contra el archivo actual. **Limitación conocida**: si un modelo legítimo del usuario tiene `__sp_` en su nombre (caso raro), el stripping lo malinterpretaría — evitar ese patrón en nombres de modelo. Para volver al modelo base tras iterar, usar `open_model(<base_path>)`.

### 3b. Lock management y open_model (Fase 1g.8)

`run_analysis` lockea el modelo; SAP rechaza modificar la definición (create/assign/modify) con el modelo locked. El bridge **no** hace auto-unlock (mantiene primitivas predecibles): cada write sigue devolviendo `oapi_call_failed` con el modelo locked, pero el cliente ahora **puede** resolverlo:

- `set_model_locked(locked, confirm)` → toggle del lock state (setting global → confirm; idempotente). Permite escapar del locked tras `run_analysis` para seguir modificando.
- `open_model(path, confirm)` → reemplaza el modelo cargado (recupera el base tras restore, cambia de modelo). El handle OAPI sobrevive a `OpenFile` (§18). `OpenFile` **descarta cambios no guardados** sin avisar — el cliente debe haber tomado savepoint si los quería.

### 3c. Workspace pattern: base inmutable + workspace transitorio (Fase 1g.9)

**Problema (§28).** El modelo del usuario y el área de trabajo del bridge eran el **mismo archivo** `.sdb`. `restore_savepoint` restauraba la memoria, no el disco base; e iterar el loop (modificar→analizar→restaurar) **contaminaba** el archivo base del usuario. Era el bloqueante que rompía el caso de uso iterativo real.

**Decisión arquitectónica.** Al primer attach (o cuando se establece/cambia el base), el bridge **inmediatamente hace `Save` a un archivo workspace separado** (`<base_dir>/<base_name>__workspace.sdb`) y opera **exclusivamente** sobre ese. El archivo base queda **congelado, inmutable, recuperable siempre** — el bridge nunca lo escribe en el flujo default.

**Cómo funciona:**
- **Auto-workspace al attach** (`_ensure_workspace_from_current_model`): lee el loaded, lo registra como `base_model_path`, computa `workspace_path`, hace `Save(workspace)` → loaded pasa a ser el workspace.
- **Re-anchor** (`_reanchor_to_workspace`): toda primitiva que mueve el loaded fuera del workspace (savepoint Save/OpenFile, open_model) vuelve el loaded al workspace al terminar. Así el filo §19 queda resuelto proactivamente: el loaded SIEMPRE es el workspace tras cualquier operación.
- **`reset_workspace(confirm)`**: regenera el workspace desde el base limpio (`OpenFile(base)` + `Save(workspace)`). Vuelve a un baseline conocido sin depender de savepoints.

**Garantía.** En el flujo default el bridge **nunca escribe al base**. Verificado en pre-vuelo: el md5 del base es idéntico antes y después de un `Save(workspace)` (§29). El base solo cambiaría vía una futura primitiva explícita `commit_workspace_to_base` (no existe).

**Implementación**: `cFile.Save` (NO `Save_2` — no existe en SAP26, §18). El `workspace_path` se computa en `_compute_workspace_path(base_path)` (función aislada, sustituible a futuro por p.ej. un dir de sesión en `%TEMP%`). `base_model_path` es **mutable** (`open_model` la mueve) y **Optional** (a futuro un modelo en blanco no tendría base). `sap_instance_origin` ∈ {`attached`, `launched`} — hoy siempre `attached`.

**Limitaciones conocidas.** El `__workspace` se sobrescribe en silencio entre sesiones (es transitorio del bridge). Single-cliente, single-proceso (multi-cliente fuera de scope). Si el directorio del base es read-only, el `Save(workspace)` falla — a futuro un dir de sesión dedicado lo resolvería.

> **Visión futura (no implementada).** El patrón anticipa orígenes alternativos de base:
> un `new_from_template` que ancle el workspace a un `.sdb` de template; un `launch_sap` que
> arranque SAP y luego haga auto-workspace. El helper de auto-workspace y el cómputo del
> workspace path se diseñaron genéricos para que esas extensiones sean naturales.

### 3d. Building from blank (Fase 1h.1)

El ciclo 1h.* arranca modelos **desde cero**, no desde un base preexistente. Dos primitivas habilitan esto sobre el workspace pattern:

- **`new_blank_model(units, confirm)`**: `InitializeNewModel(eUnits)` crea un modelo vacío en memoria (descarta lo cargado — de ahí el `confirm`). Como no hay archivo base, `base_model_path = None` y el workspace va a un **dir de sesión** (`%TEMP%/sap_bridge_sessions/<session_id>/blank_workspace.sdb`). Tras esto el bridge opera sobre ese workspace temporal como siempre.
- **`save_workspace_as(path, confirm)`**: guarda el contenido actual en `path` y lo **promueve a nuevo base** (`base_model_path = path`), derivando un workspace fresco a su lado. Es cómo un modelo construido desde blank se "materializa" en disco. Prohíbe `path == base_model_path` (eso sería un commit, primitiva separada futura) y exige `confirm` para sobrescribir un `path` existente.

**`_compute_workspace_path(base_path)` es una función pura** que ahora maneja ambos casos: con base → `<base_dir>/<base_name>__workspace.sdb`; sin base (`None`) → dir de sesión temp. El `session_id` (UUID) se asigna al primer attach y vive en el bridge state (permite cleanup por sesión y diferenciar bridges simultáneos a futuro).

**Attach sin modelo.** Si SAP está abierto sin modelo (o tras `InitializeNewModel`), `GetModelFilename` retorna un path NO absoluto (`''` o `'(Untitled)'`, §30). El attach lo maneja con gracia: **no** crea workspace, deja `base/workspace = None`, y espera un `new_blank_model` u `open_model`.

> **Hallazgos del pre-vuelo (§30):** `InitializeNewModel(eUnits)` descarta el modelo cargado en silencio (→ confirm); deja `GetModelFilename = '(Untitled)'` (placeholder, no path); `Save` sobre el modelo en memoria funciona; las units NO quedan ancladas (se pueden cambiar luego con `set_present_units`).
>
> **Future-aware:** `save_workspace_as` se construyó sobre `_save_to_path_and_update_state(path, allow_base_overwrite)` — un futuro `commit_workspace_to_base` reusa el helper con `allow_base_overwrite=True` y la restricción inversa (path == base). `new_blank_model` deja el seam para `new_from_template` (OpenFile del template + Save a workspace, base sigue None).

> ⚠️ **Corrección de raíz (§32, Fase 1h.2):** `InitializeNewModel(eUnits)` por sí solo deja el modelo **inerte** — `AddCartesian`/`AddByPoint` retornan 1 y no agregan nada, y `Save` produce un `.sdb` irreabrible (causa raíz de §31). El modelo es construible solo tras **`cFile.NewBlank()`**. `new_blank_model` ahora lo llama. El guard `empty_model` queda como defensa secundaria (un modelo con NewBlank pero sin geometría sigue dando un `.sdb` no reabrible).

### 3e. Geometry primitives (Fase 1h.2)

Las primitivas que **pueblan** un modelo (blank o existente) con geometría wireframe: joints, frames y releases. Nueve en total, sobre dos object types nuevos (point/line). Todas siguen las cinco decisiones; tres patrones propios de geometría:

**Naming híbrido.** Cada `create_*` acepta `name` **opcional**:
- Si se pasa: enforcement del prefijo `AI_` (igual que materiales/secciones, §1) + chequeo de no-colisión.
- Si no se pasa: el bridge **autogenera** `AI_J{n:03d}` (joints) / `AI_F{n:03d}` (frames) con un contador por sesión. El autogen resuelve el nombre ANTES del preview (dry_run muestra el nombre real que se asignaría). Los contadores viven en `bridge_state` y se **resetean en `reset_workspace`** (un workspace limpio reinicia la numeración). Un `name` explícito NO incrementa el contador. Este patrón es la **plantilla** para futuros `create_area`/`create_link`.

**Batch atómico.** Cada `create_*` tiene su par batch (`create_joints`/`create_frames`) que itera sobre el single con `_apply_batch_atomic` (helper generalizable a restraints/cargas de 1h.3-1h.4): pre-validación estricta → loop stop-on-first-failure → `{applied, failed_at, not_attempted}` (decisión #4). El batch se audita como UN evento con `count`.

**Delete con frame-connection check.** `delete_joint` (confirm obligatorio, §5.2) **rechaza** si el joint tiene frames conectados — pre-scan vía `_get_frames_connected_to_joint` (itera `FrameObj` + `GetPoints`, filtra por el joint). Devuelve `joint_has_connected_frames` con la lista, instruyendo "borrá los frames primero" (no cascada automática — el cliente decide). Esto además respeta la OAPI: SAP solo borra "special points" sin objetos conectados (§33), así que el check es correctness, no solo cortesía. `delete_frame` no tiene constraint de cascada (un frame no tiene sub-objetos).

**`modify_frame` in-place.** Cambiar endpoints de un frame usa `EditFrame.ChangeConnectivity` (§33), que es **in-place**: preserva el name y los releases sin delete+recreate (verificado en pre-vuelo). `modify_joint` mueve un joint con `EditPoint.ChangeCoordinates_1`; afecta a todos los frames conectados (de ahí el confirm + el preview que los lista).

> **Hallazgos del pre-vuelo (§32, §33):** `NewBlank()` obligatorio para construir; `AddCartesian(X,Y,Z, Name="", UserName, CSys)` usa UserName si Name vacío; joints se borran con `PointObj.DeleteSpecialPoint` (NO existe `.Delete`); releases en orden `[U1,U2,U3,R1,R2,R3]`; `ChangeConnectivity` preserva releases. Ver brechas §32/§33.

### 3f. Joint restraints (apoyos 6-DOF) (Fase 1h.3)

Las condiciones de contorno de un joint: qué DOFs están restringidos (apoyo). Tres primitivas que completan "construir una estructura analizable" junto con geometría (1h.2) y cargas (1h.4):

- **`set_joint_restraints(name, restraints, confirm)`**: fija los 6 flags `[U1,U2,U3,R1,R2,R3]` de un joint. La API usa **flags nombrados** (igual que `set_frame_releases`): `{U1:bool, ..., R3:bool}`, omitidos = False. El bridge mapea al array posicional que `SetRestraint` espera (orden §34). `SetRestraint` **sobrescribe** el estado completo (M1), así que el contrato es "set", no "merge". confirm obligatorio (modifica el modelo).
- **`set_joint_restraints_batch(items, confirm)`**: batch atómico sobre `apply_batch_atomic` (mismo motor que joints/frames, stop-on-first-failure), reusable para las cargas de 1h.4.
- **`get_joint_restraints(name)`**: lookup puntual de los 6 flags de UN joint (read-only, sin confirm). Simétrico con el resto del read-side; `get_joints` ya trae los restraints de TODOS, este es el lookup individual.

**Sin patrones de dominio.** El bridge NO expone `pinned`/`fixed`/`roller` — esa es interpretación del cliente (anti-patrón #4). Expone los 6 flags crudos; el cliente compone "pinned" = `{U1,U2,U3: true}`, "roller en Z" = `{U3: true}`, etc.

**"Sin apoyo" = todos los flags en False** (estado por defecto). El bridge NO usa `DeleteRestraint` para liberar un apoyo, porque (§34) `DeleteRestraint` retorna 0 pero no limpia los flags; liberar = `set_joint_restraints` con todo False.

> **Hallazgos del pre-vuelo (§34):** `SetRestraint(Name, bool[6], eItemType)` sobrescribe; `GetRestraint(Name, None) → (0, bool[6])`; orden `[U1,U2,U3,R1,R2,R3]` (= releases); ⚠️ `DeleteRestraint` no limpia los flags (no se usa). Ver brechas §34.

### 3g. Load assignment (cargas) (Fase 1h.4)

Las cargas completan el flujo "construir → cargar → analizar" desde cero. 12 primitivas sobre tres ejes: **patterns** (el contenedor de cargas), **joint loads** (fuerzas/momentos en nudos) y **frame loads** (distribuidas/puntuales en barras), cada uno con su read y su clear.

**Load patterns** (`create_load_pattern`, `list_load_patterns`). Un pattern es un grupo de cargas con un tipo (`Dead`, `Live`, `Wind`…). `create_load_pattern` lleva el prefijo `AI_` (§1), valida no-colisión y resuelve el `pattern_type` por nombre case-insensitive contra el enum vivo `eLoadPatternType` (§36, como units en 1g.3). Un modelo blank trae solo `DEAD`. ⚠️ `LoadPatterns.Add` rechaza un nombre existente (ret=1), no sobrescribe.

**Acumular, no reemplazar** (decisión de scoping #5). Todas las `assign_*_load` usan `Replace=False` en la OAPI: una segunda asignación del mismo pattern sobre el mismo objeto SE SUMA. Para "set" (reemplazar), el cliente compone `clear_*_loads` + `assign`. No hay flag `replace` — el átomo es "acumular", la composición es del cliente. Los `clear_*` SÍ limpian de verdad (a diferencia de §34, los `Delete*Load` funcionan).

**Joint loads** (`assign_joint_load`, `assign_joint_loads_batch`, `clear_joint_loads`, `get_joint_loads`). 6 componentes `{F1,F2,F3,M1,M2,M3}` (flags nombrados, default 0; orden §36 = restraints/releases) en `coord_sys` (`Global`/`Local`). Valida joint + pattern existen antes de aplicar.

**Frame loads** (`assign_frame_load_distributed(_batch)`, `assign_frame_load_point(_batch)`, `clear_frame_loads`, `get_frame_loads`). Distribuida uniforme (Val1=Val2 sobre 0%–100% del frame) o puntual (a una `distance` rel/abs). `load_type` `Force`/`Moment` (MyType 1/2). **El `direction` es el filo** (§35): el helper compartido `_resolve_load_direction(direction, coord_sys) → (Dir, CSys)` mapea los strings del cliente a los códigos OAPI, forzando `CSys=Local` para los ejes locales (que SAP exige):

| `direction` | `Dir` OAPI | `coord_sys` |
|---|---|---|
| `Local1/Local2/Local3` | 1/2/3 | forzado `Local` |
| `X/Y/Z` | 4/5/6 | el dado (default Global) |
| `XProj/YProj/ZProj` | 7/8/9 | Global |
| `Gravity` | 10 | Global |
| `GravityProj` | 11 | Global |

`get_frame_loads` devuelve `{distributed: [...], point: [...]}`, desempaquetando los arrays paralelos de SAP. **Frames sin sección admiten cargas** (decisión #6): el bridge no valida defensivamente — el error, si lo hay, emerge en `run_analysis`, no antes.

> **Hallazgos del pre-vuelo (§35, §36):** Dir enum crudo Int32 mapeado + acoplado a CSys; `eLoadPatternType` CamelCase; `Add` rechaza duplicado (ret=1); blank trae solo DEAD; orden `[F1,F2,F3,M1,M2,M3]`; `Replace=False` acumula; lecturas en arrays paralelos (CSys en MAYÚSCULAS); `Delete*Load` sí limpian. Ver brechas §35/§36.

### 3h. Ciclo 1h.* cerrado (Fase 1h.5)

El ciclo **build-from-scratch** (construir-cargar-analizar desde un modelo vacío) cierra formalmente con la validación de 1h.5. Las cuatro fases y su contribución:

| Fase | Aporte | Primitivas |
|---|---|---|
| **1h.1** | infraestructura: arrancar de vacío + materializar a disco | `new_blank_model`, `save_workspace_as` (2) |
| **1h.2** | geometría: nudos, barras, releases, edición, borrado | `create_joint(s)`, `create_frame(s)`, `delete_joint/frame`, `modify_joint/frame`, `set_frame_releases` (9) |
| **1h.3** | apoyos: condiciones de contorno 6-DOF | `set_joint_restraints(_batch)`, `get_joint_restraints` (3) |
| **1h.4** | cargas: patterns, joint/frame loads, distribuidas/puntuales | `create_load_pattern`, `assign_joint_load(_batch)`, `clear/get_joint_loads`, `assign_frame_load_distributed(_batch)`, `assign_frame_load_point(_batch)`, `clear/get_frame_loads` (11) |

**23 primitivas nuevas** (33 → **56 tools MCP**). Junto con el read-side previo (1a-1e) y el write-side de objetos (1g), el bridge cubre el **workflow estructural completo para frames**: construir un modelo de barras desde cero, apoyarlo, cargarlo (point + distributed, múltiples patterns), analizarlo y leer resultados — todo con el workspace pattern protegiendo el base, dry-run/confirm/audit en cada write, y batch atómico.

**Capacidad demostrada (1h.5):** una cercha Pratt de 8 nudos / 13 barras construida íntegramente desde blank, con releases + apoyos + dos patterns de carga, analiza y produce resultados estructuralmente correctos (equilibrio exacto, tracción/compresión donde corresponde, releases dando axial puro), itera (cambio de secciones → cambio de deflexión, equilibrio invariante), persiste cross-session de forma determinista. Validación sin un solo bug — 4ª fase consecutiva limpia (§37).

**Frontera explícita del ciclo.** El bridge soporta workflows de **frames** (barras 1D): joints, frames, releases, restraints, cargas point y distributed uniformes. Queda FUERA del ciclo, y se agrega **reactivamente** cuando un consumidor lo necesite (no preventivamente — ver brechas "Primitivas anticipadas"): áreas/shells, links, cargas trapezoidales/térmicas/prestress, presets de releases, `commit_workspace_to_base`, `launch_sap`, `new_from_template`, y los readers de stresses/envelope/modal/combinations. Esta frontera no es deuda: es el alcance deliberado del ciclo build-from-scratch para frames.

### 4. Atomicidad: stop on first failure + pre-validación del cliente

**Regla del bridge**: en operaciones batch, si una sub-operación falla, el bridge se detiene, no revierte lo ya aplicado, retorna reporte detallado:
```json
{
  "operation": "assign_section",
  "applied": ["frame_1", "frame_2", "frame_3"],
  "failed_at": "frame_4",
  "failure_reason": "frame_not_found",
  "not_attempted": ["frame_5", "frame_6", "..."]
}
```

**Patrón recomendado del cliente** (documentado en client_patterns.md):
1. Leer estado actual con primitivas read
2. Llamar con `dry_run=true` para ver impacto
3. Validar que todos los objetos referenciados existen
4. Si pre-validación pasa: llamar con `dry_run=false`
5. Si la batch reporta `failed_at`: el cliente decide

Sin primitivas compuestas. Atomicidad conjunta de "crear + asignar" se logra del lado cliente envolviendo en savepoints.

### 5. Confirmación: bool simple para operaciones destructivas

**Regla**: cada primitiva write acepta `confirm: bool` (default `false`).

**Confirm OBLIGATORIO** cuando:
1. La operación modifica o borra un objeto preexistente (sin prefijo del bridge), O
2. La operación borra cualquier objeto (incluso uno con prefijo propio), O
3. La operación modifica settings globales del modelo (active_dof, units, etc.)

**Confirm NO requerido** para:
- Crear objetos nuevos con prefijo del bridge
- Modificar objetos creados por el bridge
- Operaciones read-only

Si confirm es requerido y `confirm=false`: rechazo con error `confirm_required`.

Forma: simple `bool`. El audit trail vive en el log del bridge.

## Detalles operativos derivados

### Errores estructurados nuevos

Sumados a los existentes (sap_not_running, oapi_call_failed, oapi_unexpected_shape):

- `prefix_required` — operación crea objeto sin prefijo apropiado
- `confirm_required` — operación destructiva sin confirm=true
- `name_already_exists` — intenta crear con nombre ya tomado
- `object_not_found` — referencia a objeto que no existe
- `dry_run_validation_failed` — pre-validación detectó problema
- `savepoint_not_found` — restore o list referencia savepoint inexistente

### Logging para audit trail

El bridge loguea cada operación write con:
- Timestamp
- Operación (nombre de la primitiva)
- Parámetros completos (incluyendo dry_run, confirm)
- Resultado (applied/failed_at/error)
- Tiempo de ejecución

Destino: `Sap_experiment/sap_bridge/logs/writes_<date>.jsonl` (JSON Lines).

### Convenciones de naming para primitivas write

| Verbo | Significado |
|---|---|
| `create_<noun>` | Crea objeto nuevo (requiere prefijo) |
| `modify_<noun>` | Modifica propiedades de objeto existente |
| `delete_<noun>` | Borra objeto |
| `assign_<noun>` | Asigna relación entre objetos |
| `set_<setting>` | Modifica setting global del modelo |

### Endpoints HTTP

- POST para operaciones write
- DELETE para deletes específicos (`DELETE /v1/sections/{name}`)
- Coherente con run_analysis de Fase 1d

## Lo que este diseño NO cubre

- Multi-instance (varios consumidores escribiendo simultáneamente)
- Permisos por consumidor
- Versioning del modelo entre dry-run y write real
- Operaciones asíncronas

Cualquiera de estos puede convertirse en extensión futura.
