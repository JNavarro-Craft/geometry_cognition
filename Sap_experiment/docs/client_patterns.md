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

Desde Fase 1g.7 este flujo end-to-end es **ejecutable** con primitivas del bridge — el caso de uso central de un cliente que prueba una hipótesis de diseño sin tocar el modelo permanentemente:
```
# 1. red de seguridad
create_savepoint("hypothesis_X")

# 2. crear la pieza nueva (prefijada) y configurarla
create_rectangular_section("AI_45x95", material="MGP10", depth=0.045, width=0.095)

# 3. PRE-VALIDAR + dry_run antes del batch (client_patterns #1)
target_frames = [...]                      # del cliente: get_frames + su lógica de dominio
assign_section_to_frames("AI_45x95", target_frames, dry_run=True)   # revisar changes/hint
# 4. aplicar (confirm: toca frames preexistentes)
assign_section_to_frames("AI_45x95", target_frames, confirm=True)

# 5. analizar con la nueva config
run_analysis()                             # corre lo pendiente
# 6. leer resultados y razonar (esto es dominio del cliente, no del bridge)
for f in target_frames:
    get_frame_forces(f, "ENVOLVENTE")      # P, V, M en las nuevas secciones

# 7. SIEMPRE restaurar: la hipótesis se probó, el modelo del usuario vuelve a baseline
restore_savepoint("hypothesis_X", confirm=True)
#    (tras restore, reabrir el modelo original — la sesión queda en el archivo del savepoint)
```
El bridge provee los átomos (crear, asignar, analizar, leer, restaurar); el **cliente compone el experimento y razona sobre los resultados**. El bridge no decide si la sección "mejora" la estructura — eso es interpretación de dominio (anti-patrón #4).
