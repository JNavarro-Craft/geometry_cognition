# Módulos archivados

Este directorio contiene módulos que formaban parte del pipeline 
obligatorio anterior y que fueron desactivados durante la 
consolidación del núcleo.

No son invocados por workflows ni scripts activos. Se conservan 
como referencia histórica y por si se necesita rescatar lógica 
específica en el futuro.

Módulos archivados (primera consolidación — pipeline de razonamiento):
- reasoning_framework: capa de disciplina LLM (preservada como 
  docs/reasoning_rules.md)
- evidence_graph: grafo de evidencia intermedio
- hypothesis_engine: generación de hipótesis genéricas
- validation_engine: validación de hipótesis abstractas
- domain_interpreter: interpretación de hipótesis con perfiles

Módulos archivados (segunda consolidación — solo developer_server tiene
utilidad real; el resto eran MCPs hermanos sin uso activo):
- reader_server: consulta de estado del modelo. Su funcionalidad quedó
  cubierta y superada por developer_server (query_objects + describe_model
  + aggregate sobre live y snapshots).
- geometry_kernel: cómputo de features geométricas (oriented_bbox por PCA,
  etc.) sobre objetos ya extraídos. El bridge ahora expone esos hechos
  directamente (obb_*, get_faces/edges/vertices), de forma exacta y agnóstica.
- verification_planner: planificación de chequeos de relación.
- verification_executor: ejecución de esos chequeos contra el bridge.
  La verificación de relaciones se reemplaza por primitivas agnósticas
  componibles (compute_contacts, compute_distance, find_nearby) sobre las
  que el cliente razona; no por un planificador/ejecutor de dominio.

Activos (NO archivar):
- developer_server: el MCP en uso. Lee/analiza el modelo Rhino vía bridge.
- rhino_extractor: dependencia directa de developer_server (bridge_backend,
  backend_adapter). No es un MCP de cara al usuario, es la capa de transporte.

Tests/scripts/workflows de los módulos archivados se movieron junto a ellos,
bajo _archive/_tests, _archive/_scripts y _archive/_workflows, para que nada
activo quede con referencias colgantes. No se ejecutan en la suite activa.
