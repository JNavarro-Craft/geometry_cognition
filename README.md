# geometry_cognition

Sistema para **observar y analizar modelos geométricos 3D de Rhino de forma
estrictamente agnóstica al dominio**. La infraestructura entrega *hechos geométricos*
(dimensiones, topología, contactos, distancias, proyecciones); toda interpretación de
dominio —qué es una pieza, un muro, una junta, un error— la compone el cliente (un LLM)
por encima.

## Estado actual (consolidado)

El sistema se consolidó alrededor de **un único MCP activo** y su capa de transporte.
El pipeline multi-etapa original (interpretación / evidencia / hipótesis / validación /
dominio) fue archivado: en la práctica, un cliente capaz razona sobre los primitivos
geométricos sin necesidad de esas capas intermedias. Ver
[`docs/agnostic_principle.md`](docs/agnostic_principle.md) para el porqué.

### Componentes activos

| Componente | Rol |
|---|---|
| `rhino_bridge/plugin/` | Plugin Rhino (.rhp, C#) — el **bridge**: expone el modelo vivo por HTTP (`/v1/live/*`), estrictamente geométrico. |
| `gc_mcp/developer_server/` | El **MCP** (21 tools): lee y analiza el modelo vía el bridge. Observacional, no muta. |
| `gc_mcp/rhino_bridge_client/` | Capa de **transporte** (no es un MCP): cliente HTTP del bridge + normalización de respuestas. La importa `developer_server`; un futuro MCP `automation` la reusaría. |
| `contracts/` | Esquemas JSON versionados (p. ej. `object_schema.v1.json`). |
| `gc_mcp/_archive/` | Módulos del pipeline anterior, preservados con su historial. No activos. |

### Familias de tools del MCP

Todas agnósticas — operaciones geométricas, no interpretaciones:

- **Descubrimiento / consulta**: `describe_model`, `query_objects` (filtros + paginación),
  `inspect_object`, `aggregate`.
- **Medición**: `obb_*` y `longest_edge` (vía bridge), `get_vertices` / `get_edges` /
  `get_faces` (geometría + topología por elemento).
- **Relación espacial**: `compute_contacts` (contacto real con ubicación),
  `compute_distance`, `find_nearby`, `project_to_plane`.
- **Bloques**: `list_block_definitions`, `expand_block`, `bill_of_materials`.
- **Snapshots y cambios**: `take_snapshot` / `list` / `delete` / `prune_snapshots`,
  `diff_snapshots`, `diff_object`, `assert_change`.

El inventario de estado vivo está en
[`docs/system_capabilities.md`](docs/system_capabilities.md); el histórico de cambios en
[`docs/CHANGELOG.md`](docs/CHANGELOG.md).

## Reglas de diseño no negociables

- **El núcleo es agnóstico al dominio.** El bridge y el MCP reportan tipos Rhino,
  user_text y geometría; nunca nombran "viga", "muro" ni "error".
- **Falla ruidosa, no silenciosa.** Ningún fallback devuelve datos distintos a los
  pedidos haciéndolos pasar por correctos; los filtros reportan honestamente si
  aplicaron.
- **Primitivos, no usos.** Se exponen operaciones geométricas; los casos de uso
  (despiece, detección de aberturas, cubicación, clasificación de roles) los compone el
  cliente. El test ácido para decidir qué entra está en
  [`docs/agnostic_principle.md`](docs/agnostic_principle.md).
- **El MCP es observacional.** No muta el modelo. La mutación sería un MCP `automation`
  aparte (no existe aún), que reutilizaría `rhino_bridge_client`.
- **Comunicación por contratos.** Los objetos normalizados cumplen `contracts/*.json`.

## Cómo correr

```bash
# Suite de tests (solo módulos activos)
pytest -q                    # 86 passed

# El MCP requiere Rhino abierto con el plugin (bridge en :8765).
# Ver docs/usage_bridge_mcp.md para el flujo MCP <-> bridge,
# y docs/development.md para build/instalación del plugin C#.
```

## Documentación

- [`docs/agnostic_principle.md`](docs/agnostic_principle.md) — el principio rector + test ácido (por qué se diseña así).
- [`docs/system_capabilities.md`](docs/system_capabilities.md) — qué hay hoy (checklist de estado) + qué falta.
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — qué cambió y cuándo (commit a commit).
- [`docs/usage_bridge_mcp.md`](docs/usage_bridge_mcp.md) — uso del bridge desde el MCP.
- [`docs/development.md`](docs/development.md) — build del plugin, suite, entorno.
- [`docs/plan_bridge_developer_v2.md`](docs/plan_bridge_developer_v2.md) — plan por fases del developer_server.

## Nota sobre directorios heredados

`domain_profiles/`, `knowledge_base/`, `workflows/` y varios esquemas de `contracts/`
(`hypothesis_`, `validation_`, `evidence_`, `domain_interpretation_`) pertenecen al
pipeline original archivado. Se conservan como referencia; no participan del flujo
activo, que es exclusivamente **bridge ↔ rhino_bridge_client ↔ developer_server**.
