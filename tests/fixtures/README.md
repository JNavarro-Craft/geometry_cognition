# Fixtures de Fase 2

Estos fixtures son conceptuales (no dependen de Rhino real) y prueban fronteras del flujo minimo.

**Orden conceptual del pipeline** (al activar etapas en `workflows/run_minimal_analysis.py`):

`rhino_extractor` → `geometry_kernel` → `evidence_graph` → `hypothesis_engine` → `validation_engine` → `domain_interpreter` (esta ultima exige en memoria etapas previas; no se activa runtime de `knowledge_base` ni `automation`).

## Instancias de bloque y rhino3dm

La **creación o reescritura programática de bloques** con `rhino3dm` puede **colgarse o ser inestable** según versión y plataforma. Los tests de integración usan **JSON** o un `.3dm` real aportado por el entorno. El análisis de instancias de bloque leídas desde un `.3dm` real sigue pudiendo quedar bajo la limitación `block_definition_not_expanded` u otras señaladas en el extractor; no se requiere expandir bloques en esta fase.

`rhino_extractor -> geometry_kernel -> (geometry + entities + relations)` (etapa base; encadenado completo en el workflow con flags)

## Escenarios

- `simple_linear_elements.sample.json`
  - **Representa**: dos elementos lineales simples con posible coherencia direccional.
  - **Contratos cubiertos**: `object_schema`, `entity_schema`, `relations_schema`.
  - **Frontera conceptual**: observacion geometrica y relaciones abstractas (`parallel_to`) sin semantica de dominio.

- `simple_plate_elements.sample.json`
  - **Representa**: dos elementos tipo placa con cercania espacial.
  - **Contratos cubiertos**: `object_schema`, `entity_schema`, `relations_schema`.
  - **Frontera conceptual**: morfologia abstracta y clustering sin clasificacion funcional.

- `block_instance.sample.json`
  - **Representa**: una instancia de bloque y su entidad de ocurrencia.
  - **Contratos cubiertos**: `object_schema`, `entity_schema`, `relations_schema`.
  - **Frontera conceptual**: distincion entre observacion de instancia y abstraccion de entidad (`block_instance` / `instance_object`).

- `contradictory_metadata.sample.json`
  - **Representa**: conflicto entre señales declarativas de metadata.
  - **Contratos cubiertos**: `object_schema`, `metadata_schema`, `entity_schema`.
  - **Frontera conceptual**: conflicto observacional no se convierte automaticamente en hipotesis o verdad.

- `documentation_group.sample.json`
  - **Representa**: agrupacion declarada por documentacion/software.
  - **Contratos cubiertos**: `object_schema`, `entity_schema`, `relations_schema`.
  - **Frontera conceptual**: `group_candidate` y `grouped_with` como declarativos, no como entidad validada final.

- `mixed_system.sample.json`
  - **Representa**: mezcla de objetos, grupo declarado e instancia de bloque.
  - **Contratos cubiertos**: `object_schema`, `entity_schema`, `relations_schema`.
  - **Frontera conceptual**: coexistencia de observaciones heterogeneas sin fusionarlas en evidencia consolidada ni hipotesis.
