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
