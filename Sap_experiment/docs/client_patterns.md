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

Desde Fase 1g.8 este flujo end-to-end es **ejecutable y robusto para iteración** — el caso de uso central de un cliente que prueba hipótesis de diseño. El orden importa: `run_analysis` **lockea** el modelo, y SAP rechaza modificar la definición mientras está locked, así que hay que **desbloquear entre analizar y modificar**:
```
# 0. (recomendado al inicio de cada iteración) asegurar el modelo base limpio
open_model("<base>/TEST_01.sdb", confirm=True)

# 1. red de seguridad — del modelo LIMPIO, antes de cualquier cambio
create_savepoint("hypothesis_X")

# 2. analizar el baseline y leer la referencia
run_analysis()                             # esto LOCKEA el modelo
ref = get_joint_displacements("1966", "MUERTA")   # u3 de referencia

# 3. DESBLOQUEAR para poder modificar (bloqueante #1 de §26, resuelto)
set_model_locked(False, confirm=True)

# 4. crear la pieza nueva (prefijada) y asignarla (dry_run primero, client_patterns #1)
create_rectangular_section("AI_45x95", material="MGP10", depth=0.045, width=0.095)
assign_section_to_frames("AI_45x95", target_frames, dry_run=True)    # revisar changes/hint
assign_section_to_frames("AI_45x95", target_frames, confirm=True)

# 5. re-analizar y leer el efecto
run_analysis()
mod = get_joint_displacements("1966", "MUERTA")
# razonar el delta (dominio del cliente, no del bridge)

# 6. restaurar + desbloquear; tras restore la sesión queda en el savepoint
set_model_locked(False, confirm=True)
restore_savepoint("hypothesis_X", confirm=True)
# para volver al modelo base: open_model("<base>/TEST_01.sdb", confirm=True)
```
El bridge provee los átomos (crear, asignar, analizar, leer, lock/unlock, restaurar, open); el **cliente compone el experimento y razona sobre los resultados**. El bridge no decide si la sección "mejora" la estructura — eso es dominio del cliente (anti-patrón #4).

> ⚠️ **Limitación conocida (brechas §28).** El modelo del usuario y el workspace del bridge son el **mismo archivo**. `restore_savepoint` restaura la memoria, no el archivo base en disco, y `create_savepoint` puede dejar modificaciones asociadas al base. **Iterar el loop puede contaminar el `.sdb` base.** Hasta que exista un workspace base-inmutable: tomar un savepoint del baseline limpio ANTES de cualquier cambio, y recuperar desde ahí si el base se ensucia. El cliente solo no se recupera de una contaminación del base sin ese savepoint limpio.
