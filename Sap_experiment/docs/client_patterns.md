# Client Patterns — sap_experiment

Patrones recomendados para consumidores del `sap_bridge` (MCP de Claude, plugins Rhino, scripts standalone, etc.).

Estos patrones NO son enforced por el bridge — son responsabilidad del cliente. El bridge provee primitivas seguras y reporta honestamente; el cliente compone.

## Patrón 1: Pre-validación antes de write

Antes de cualquier operación write (especialmente batches), el cliente debe:

1. **Consultar estado actual** con primitivas read (`get_frames`, `get_sections`, etc.)
2. **Llamar con `dry_run=true`** para ver impacto exacto
3. **Verificar** que todos los objetos referenciados existen y son válidos
4. **Solo si pre-validación pasa**: llamar con `dry_run=false`

Esto reduce dramáticamente la probabilidad de fallos a la mitad. El bridge tiene safety net (stop-on-first-failure + reporte) para los casos donde la pre-validación no fue suficiente, pero la primera línea de defensa es el cliente.

## Patrón 2: Savepoint antes de batch riesgoso

Para operaciones que afectan a múltiples objetos o que serían difíciles de revertir manualmente:
```
create_savepoint("before_batch_X")
... operación batch ...
# Si reporta failed_at o el resultado es indeseado:
restore_savepoint("before_batch_X", confirm=True)
```

Costo: una llamada extra antes y opcional después. Beneficio: rollback garantizado vía SAP.

## Patrón 3: Confirm sólo después de revisión

Cuando el bridge requiere `confirm=true`, el cliente NO debe pasarlo automáticamente. El flujo correcto es:

1. Construir la operación
2. (Opcional pero recomendado) Llamar primero con `dry_run=true`
3. Presentar al usuario o decisor: "esto es lo que va a pasar"
4. Recibir confirmación explícita
5. Construir el request con `confirm=true`

Un LLM que pasa `confirm=true` por defecto sin revisión está bypaseando la salvaguarda.

## Patrón 4: Composición de operaciones complejas

El bridge no expone primitivas compuestas. Para componer:
```
# Crear y asignar una sección
create_savepoint("before_section_setup")
result_create = create_section(name="AI_45x95", dimensions=...)
if result_create.success:
    result_assign = assign_section(name="AI_45x95", frames=[...])
    if not result_assign.success or result_assign.failed_at:
        restore_savepoint("before_section_setup", confirm=True)
```

El cliente maneja la lógica condicional. El bridge solo provee átomos.

## Patrón 5: Manejo de batches con failed_at

Cuando una batch retorna `failed_at`, las opciones del cliente:

A) **Retry**: arreglar la causa del fallo (el frame faltante, etc.) y volver a llamar con los items no completados (`not_attempted` + `failed_at`).

B) **Aceptar parcial**: el cliente decide que lo aplicado es suficiente. Reporta al usuario el estado.

C) **Restaurar**: si el estado parcial es inaceptable, restore_savepoint si se creó uno antes.

No hay opción D (revertir lo ya aplicado mediante el bridge), porque el bridge no implementa undo transaccional. El cliente debe haber tomado savepoint.

## Patrón 6: Crear objeto + configurar propiedades (atómicas separadas)

El bridge expone `create_<noun>` y `set_<noun>_properties_*` como primitivas **separadas** (no hay un `create_with_properties` compuesto). Un objeto recién creado tiene solo propiedades por defecto; configurarlo es un segundo paso del cliente. Ejemplo validado (Fase 1g.4), creando un material isotrópico:
```
# 1. (opcional) savepoint si el resultado debe ser reversible
create_savepoint("before_material_setup")

# 2. crear el objeto — DEBE llevar el prefijo del bridge (AI_)
r = create_material(name="AI_MGP10_Custom", material_type="NoDesign")
#    -> prefix_required si falta el prefijo
#    -> unknown_material_type si el tipo no es miembro de eMatType
#    -> name_already_exists si el nombre ya existe (SAP sobrescribiría en silencio)

# 3. configurar sus propiedades — sin confirm (es objeto propio del bridge)
#    valores en las PRESENT UNITS del modelo: el cliente debe saber cuáles son
if "applied" in r:
    set_material_properties_isotropic(
        "AI_MGP10_Custom", E=1.02e9, poisson_ratio=0.4, thermal_coef=1.17e-5
    )

# 4. si algo no cuadra: restore_savepoint("before_material_setup", confirm=True)
```

Notas:
- **El prefijo es obligatorio al crear.** El bridge solo crea en su namespace; modificar un objeto preexistente del usuario (sin prefijo) exige `confirm=true`, modificar uno propio no.
- **Las unidades son responsabilidad del cliente.** `E`, etc. van en las present units del modelo (consultar `get_model_settings`); el bridge no convierte. En `kgf_m_C`, `E` va en kgf/m².
- **Atómicas, no compuestas.** Si `set_properties` falla tras un `create` exitoso, el material queda creado con defaults — el cliente decide si reintentar, dejarlo, o restaurar.

## Patrón 7: Loop completo de verificación (crear → asignar → analizar → leer → restaurar)

Desde Fase 1g.9 este flujo end-to-end es **ejecutable, robusto e iterable** — el caso de uso central de un cliente que prueba hipótesis de diseño. Dos cosas a saber: (1) el bridge opera sobre un **workspace transitorio** (el modelo base del usuario nunca se toca), y (2) `run_analysis` **lockea** el modelo, así que hay que **desbloquear entre analizar y modificar**:
```
# 0. (implícito) al primer attach el bridge ya hizo auto-workspace.
#    Al inicio de CADA iteración, volver al baseline limpio:
reset_workspace(confirm=True)              # regenera el workspace desde el base inmutable

# 1. red de seguridad opcional (alternativa a reset entre iteraciones)
create_savepoint("hypothesis_X")

# 2. analizar el baseline y leer la referencia
run_analysis()                             # esto LOCKEA el modelo
ref = get_joint_displacements("1966", "MUERTA")   # u3 de referencia

# 3. DESBLOQUEAR para poder modificar (bloqueante de §26, resuelto en 1g.8)
set_model_locked(False, confirm=True)

# 4. crear la pieza nueva (prefijada) y asignarla (dry_run primero, client_patterns #1)
create_rectangular_section("AI_45x95", material="MGP10", depth=0.045, width=0.095)
assign_section_to_frames("AI_45x95", target_frames, dry_run=True)    # revisar changes/hint
assign_section_to_frames("AI_45x95", target_frames, confirm=True)

# 5. re-analizar y leer el efecto
run_analysis()
mod = get_joint_displacements("1966", "MUERTA")
# razonar el delta (dominio del cliente, no del bridge)

# 6. siguiente iteración: reset_workspace(confirm=True) vuelve al baseline limpio
#    (o restore_savepoint("hypothesis_X", confirm=True)). El bridge re-anchora al
#    workspace solo; no hace falta open_model manual.
```
El bridge provee los átomos (crear, asignar, analizar, leer, lock/unlock, savepoint, reset_workspace); el **cliente compone el experimento y razona sobre los resultados**. El bridge no decide si la sección "mejora" la estructura — eso es dominio del cliente (anti-patrón #4).

> ✅ **§28 resuelto (Fase 1g.9, workspace pattern).** El modelo base del usuario es **inmutable**: el bridge trabaja sobre `<base>__workspace.sdb` y nunca escribe el base en el flujo default. `reset_workspace` y `restore_savepoint` ambos dejan la sesión en el workspace, listo para la siguiente iteración. Validado: dos iteraciones del caso real dan baseline y resultados idénticos, y el `.sdb` base queda byte-intacto.

## Patrón 8: Construir desde cero (build-from-blank)

Desde Fase 1h.1 el cliente puede arrancar de un modelo vacío en vez de un base preexistente. El flujo: inicializar vacío → construir (geometría, secciones, cargas — primitivas de fases 1h.2+) → materializar en disco como nuevo base.
```
# 1. modelo vacío con las units de trabajo (DESTRUCTIVO: descarta lo cargado)
new_blank_model(units="kgf_m_C", confirm=True)
#    -> base_model_path = None; workspace en %TEMP%/sap_bridge_sessions/<id>/blank_workspace.sdb
#    -> 0 joints, 0 frames, materiales default de SAP

# 2. construir el modelo (estas primitivas llegan en 1h.2-1h.4)
#    create_material(...), create_rectangular_section(...),
#    create_joint(...), create_frame(...), set_joint_restraints(...), ...
#    Todo opera sobre el workspace temporal, como siempre.

# 3. materializar en disco: el workspace se promueve a nuevo base
save_workspace_as("C:/models/mi_cercha.sdb", confirm=True)
#    -> base_model_path = mi_cercha.sdb; workspace fresco = mi_cercha__workspace.sdb al lado
#    -> a partir de aquí, el patrón normal: reset_workspace, savepoints, etc. funcionan
```
Notas:
- `new_blank_model` es **destructivo** (descarta lo cargado, sin guardar) → `confirm` obligatorio. Las units NO quedan ancladas: `set_present_units` las cambia luego.
- `save_workspace_as` **prohíbe** `path == base actual` (eso sería un commit al base, primitiva separada futura) y exige `confirm` para sobrescribir un archivo existente.
- Tras `save_workspace_as`, el modelo construido es un base normal: reabrible en otra sesión, con su workspace inmutable. Es el puente entre "construir desde cero" y el patrón workspace del Objetivo 1.

## Patrón 9: Construir una cercha desde blank (build truss from blank)

Desde Fase 1h.2, el cliente compone geometría real sobre el ciclo build-from-blank. El flujo concreto (cercha triangular de 3 nudos / 3 frames como ejemplo mínimo):
```
# 1. modelo vacío y construible
new_blank_model(units="kgf_m_C", confirm=True)

# 2. nudos — batch (autogen AI_J001.. o name explícito por elemento)
create_joints([
    {"x": 0, "y": 0, "z": 0},                       # -> AI_J001
    {"x": 4, "y": 0, "z": 0, "name": "AI_apoyo"},   # name explícito
    {"x": 2, "y": 0, "z": 1.5},                     # -> AI_J002
], confirm=True)

# 3. material + sección (para tener algo asignable; átomos de 1g.4/1g.5)
create_material("AI_MGP10", "NoDesign")
create_rectangular_section("AI_45x95", "AI_MGP10", depth=0.045, width=0.095)

# 4. frames — validan que los joints existen ANTES de crear
create_frames([
    {"joint_i": "AI_J001",  "joint_j": "AI_apoyo", "section": "AI_45x95"},  # -> AI_F001
    {"joint_i": "AI_J001",  "joint_j": "AI_J002",  "section": "AI_45x95"},  # -> AI_F002
    {"joint_i": "AI_apoyo", "joint_j": "AI_J002",  "section": "AI_45x95"},  # -> AI_F003
], confirm=True)

# 5. releases — comportamiento de cercha 2D (pin: M3 libre en ambos extremos)
pin = {"U1": False, "U2": False, "U3": False, "R1": False, "R2": False, "R3": True}
set_frame_releases("AI_F002", releases_i=pin, releases_j=pin, confirm=True)

# 6. apoyos (1h.3) — el cliente compone el patrón de dominio a partir de los 6 flags crudos
#    "pinned" = U1,U2,U3 restringidos; "roller en Z" = solo U3 (deja U1 libre)
set_joint_restraints("AI_J001",  {"U1": True, "U2": True, "U3": True}, confirm=True)   # pinned
set_joint_restraints("AI_apoyo", {"U3": True}, confirm=True)                            # roller Z
#    o en batch atómico:
# set_joint_restraints_batch([
#     {"name": "AI_J001",  "restraints": {"U1": True, "U2": True, "U3": True}},
#     {"name": "AI_apoyo", "restraints": {"U3": True}},
# ], confirm=True)

# 7. materializar (requiere geometría — el guard empty_model rechazaría un blank vacío)
save_workspace_as("C:/models/cercha.sdb", confirm=True)
# 1h.4+ añadirá cargas, luego run_analysis sobre la estructura completa.
```
Notas:
- **Naming híbrido**: dejá que el bridge numere (`AI_J###`/`AI_F###`) salvo cuando un nombre semántico ayude (`AI_apoyo`). Un name explícito NO incrementa el contador. Los contadores se resetean con `reset_workspace`.
- **Orden importa**: los joints antes que los frames (un frame valida sus dos joints al crearse); el material+sección antes de asignarla a un frame. El bridge da los átomos; el cliente ordena.
- **Batch atómico**: si un elemento del batch falla, el bridge para ahí y reporta `applied`/`failed_at`/`not_attempted` — el cliente decide reintentar el resto o restaurar.
- **Delete con cuidado**: `delete_joint` rechaza si el joint tiene frames conectados (`joint_has_connected_frames` con la lista) — borrá los frames primero. `delete_frame` no tiene esa restricción.
- **`modify_frame` preserva releases** al cambiar endpoints (in-place, §33). `modify_joint` mueve el nudo y afecta a todos sus frames conectados (el preview los lista).
- **Apoyos son dominio del cliente**: el bridge expone los 6 flags `[U1..R3]`, nunca "pinned"/"fixed"/"roller". "Sin apoyo" = todos False. Liberar un apoyo = `set_joint_restraints` con todo False (no hay un "delete restraint" — §34).

## Patrón 10: Cargar y analizar (load and analyze workflow)

Desde Fase 1h.4, sobre una estructura ya construida (geometría + apoyos, Patrón 9) el cliente asigna cargas y la analiza — cerrando el flujo construir→cargar→analizar desde cero:
```
# (a) load pattern — si necesitás uno custom (el blank ya trae DEAD)
create_load_pattern("AI_LIVE", "Live", self_weight_multiplier=0, confirm=True)

# (b) cargas. assign_*_load ACUMULA (no reemplaza) — semántica SAP-native
#     joint: fuerza puntual de 1000 kgf hacia abajo en el peak
assign_joint_load("AI_J002", "AI_LIVE", forces={"F3": -1000.0}, confirm=True)
#     frame distribuida gravitacional (la dirección "Gravity" = Global -Z proyectada)
assign_frame_load_distributed("AI_F002", "AI_LIVE", value=-200.0,
                              direction="Gravity", confirm=True)
#     frame puntual a media barra, en Global Z
assign_frame_load_point("AI_F001", "AI_LIVE", value=-500.0, distance=0.5,
                        direction="Z", coord_sys="Global", rel_distance=True, confirm=True)

# (c) ¿ajustar una carga? como assign ACUMULA, para "reemplazar" hay que limpiar primero:
clear_frame_loads("AI_F001", pattern_name="AI_LIVE", confirm=True)   # limpia y...
assign_frame_load_point("AI_F001", "AI_LIVE", value=-800.0, distance=0.5,
                        direction="Z", confirm=True)                  # ...re-asigna

# (d) analizar (run_analysis lockea el modelo — Patrón 7)
run_analysis()

# (e) leer resultados (dominio del cliente razonar si son aceptables)
get_joint_displacements("AI_J002", "AI_LIVE")
get_frame_forces("AI_F001", "AI_LIVE")
```
Notas:
- **Acumular es el default**: dos `assign` del mismo pattern sobre el mismo objeto SE SUMAN. El bridge no expone un flag `replace`; "set" = `clear_*_loads` + `assign` (el cliente compone). Los `clear_*` sí limpian de verdad.
- **`direction` de frame loads** (§35): `"X"/"Y"/"Z"` (en el `coord_sys` dado), `"Local1/2/3"` (ejes del frame, el bridge fuerza coord local), `"Gravity"` (Global −Z). Un nombre desconocido → `unknown_load_direction`.
- **coord_sys**: joint loads y frame loads aceptan `"Global"` (default) o `"Local"`. Para las direcciones locales de frame, el bridge ya fuerza `Local` aunque pases otra cosa.
- **Frames sin sección admiten cargas** — el bridge no lo impide; si falta algo para analizar, el error sale en `run_analysis`, no en el assign.
- **Batch**: `assign_joint_loads_batch`, `assign_frame_load_distributed_batch`, `assign_frame_load_point_batch` — atómicos (stop-on-first-failure), igual que el resto.

## Patrón 11: Cercha multi-panel completa (build → restraint → load → analyze → iterate → save)

Validado en Fase 1h.5 con una cercha Pratt de 8 nudos / 13 barras. Es el flujo de referencia para un consumidor (easywood_mcp) que construye una estructura real desde cero y la verifica. Junta todos los patrones anteriores a escala:
```
# 1. arrancar vacío + material/sección
new_blank_model(units="kgf_m_C", confirm=True)
create_material("AI_MGP10", "NoDesign")
create_rectangular_section("AI_45x95", "AI_MGP10", depth=0.045, width=0.095)

# 2. geometría EN BATCH (naming híbrido: explícitos para los nudos clave)
create_joints([{ "x":0,"y":0,"z":0,"name":"AI_L0"}, ... 8 nudos ...], confirm=True)
create_frames([{ "joint_i":"AI_L0","joint_j":"AI_L1","section":"AI_45x95","name":"AI_BC0"}, ...], confirm=True)

# 3. releases (one-by-one — no hay batch de releases): R3 en barras de cercha (todas menos cuerda inferior)
for f in diagonales + montantes + cuerda_superior:
    set_frame_releases(f, releases_i={"R3":True}, releases_j={"R3":True}, confirm=True)

# 4. apoyos EN BATCH. ⚠️ En 3D con cercha plana X-Z, restringir U2 (fuera de plano) en TODOS los
#    nudos para evitar inestabilidad fuera del plano (física estándar, el cliente lo compone).
set_joint_restraints_batch([
    {"name":"AI_L0","restraints":{"U1":True,"U2":True,"U3":True}},   # pin
    {"name":"AI_L4","restraints":{"U2":True,"U3":True}},             # roller
    {"name":"AI_L1","restraints":{"U2":True}}, ... (resto: solo U2)
], confirm=True)

# 5. cargas en MÚLTIPLES patterns, en batch
create_load_pattern("AI_LIVE_ROOF", "Live", confirm=True)
assign_frame_loads_distributed_batch([{ "frame_name":"AI_TC0","pattern_name":"DEAD","value":-100,"direction":"Gravity"}, ...], confirm=True)
assign_joint_loads_batch([{ "joint_name":"AI_U2","pattern_name":"AI_LIVE_ROOF","forces":{"F3":-500}}, ...], confirm=True)

# 6. analizar y verificar coherencia (dominio del cliente)
run_analysis()
react_L0 = get_joint_reactions("AI_L0", "AI_LIVE_ROOF")   # Σ reacciones ≈ -Σ cargas (equilibrio)
get_frame_forces("AI_BC0", "AI_LIVE_ROOF")                # cuerda inf: tracción
get_frame_forces("AI_TC0", "AI_LIVE_ROOF")                # cuerda sup: compresión; m3≈0 (release)

# 7. iterar: probar otras secciones (savepoint para volver)
create_savepoint("pre_iteration")
set_model_locked(False, confirm=True)                     # run_analysis lockeó
assign_section_to_frames("AI_38x73", cuerda_inferior, confirm=True)
run_analysis()                                            # nueva deflexión; equilibrio invariante
restore_savepoint("pre_iteration", confirm=True)          # volver al baseline (workspace pattern aguanta)

# 8. materializar el diseño final
save_workspace_as("C:/models/cercha_pratt_v1.sdb", confirm=True)
```
Notas:
- **Inestabilidad fuera de plano**: el síntoma típico es que `run_analysis` reporte un caso no convergido o resultados absurdos. La cura para una cercha plana es restringir el DOF perpendicular al plano en todos los nudos. El bridge no lo hace por vos (no asume dimensionalidad) — es composición del cliente.
- **Determinismo**: tras `save_workspace_as` → `open_model`, re-`run_analysis` da resultados idénticos (validado hasta ~1e-17). El `.sdb` es un modelo completo y reproducible.
- **Escala**: batch ops, naming híbrido y workspace pattern se validaron a 8 joints / 13 frames sin fricción; el patrón escala linealmente a cerchas más grandes.
