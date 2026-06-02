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
