# geometry_cognition

`geometry_cognition` es un monorepo modular para construir MCPs que observan, estructuran, validan y razonan sobre modelos geométricos 3D de forma agnóstica al dominio.

## Por qué existe

Los modelos 3D suelen mezclar señales geométricas, metadata declarativa y supuestos de dominio. Este proyecto separa esas capas para mantener trazabilidad, portabilidad y evolución independiente de cada MCP.

## Separación conceptual obligatoria

El sistema separa estrictamente:

1. Observación
2. Interpretación
3. Evidencia
4. Hipótesis
5. Validación
6. Conocimiento persistente
7. Acción / automatización

Ninguna etapa debe colapsar las demás.

## Orden de pipeline (mínimo)

Fase por dependencia, tal como se encadena en `workflows/run_minimal_analysis.py`:

1. `rhino_extractor` (o JSON de prueba)  
2. `geometry_kernel`  
3. `evidence_graph` (cuando se pide una etapa que lo requiere)  
4. `hypothesis_engine`  
5. `validation_engine`  
6. `domain_interpreter` (sigue a validación en el mismo `run` cuando se incluye dominio)

`knowledge_base` y `automation` no forman parte del análisis mínimo de estabilización salvo invocación explícita de sus MCPs.

## Arquitectura MCP

Los MCPs se comunican exclusivamente con contratos JSON versionados en `contracts/`.

- MCPs fijos de plataforma:
  - `geometry_kernel`
  - `metadata_context`
  - `evidence_graph`
  - `hypothesis_engine`
  - `validation_engine`
  - `knowledge_base`
- MCPs variables:
  - extractores (ej. `rhino_extractor`)
  - automatización (`automation`)
  - perfiles de dominio (`domain_profiles/`)

## Qué es fijo vs variable

- **Fijo**: estructura del pipeline, contratos base, reglas de separación conceptual, trazabilidad evidencia->hipótesis.
- **Variable**: fuentes de extracción, vocabulario de perfiles de dominio, reglas específicas de validación por contexto.

## Cómo agregar un nuevo extractor

1. Crear carpeta en `gc_mcp/<extractor_name>/`.
2. Definir `README.md`, `server.py`, `tools.py`.
3. Emitir objetos normalizados conformes a `contracts/object_schema.v1.json`.
4. No introducir lógica de interpretación de dominio en el extractor.

## Cómo agregar un nuevo domain profile

1. Crear `domain_profiles/<profile_name>/profile.json`.
2. Declarar vocabulario permitido para hipótesis y términos prohibidos en core.
3. Definir patrones típicos de evidencia y nombres de reglas de validación.
4. Mantener aislamiento: los perfiles no deben contaminar el `geometry_kernel`.

## Reglas de diseño no negociables

- El core es agnóstico al dominio.
- El geometry kernel no contiene vocabulario de dominio.
- Los MCPs no se importan lógica entre sí de forma directa.
- Comunicación entre MCPs solo vía contratos JSON versionados.
- Todo MCP declara su rol explícito.
- El sistema expresa incertidumbre, conflicto y evidencia insuficiente.
- Toda hipótesis es trazable a evidencia.
- Los domain profiles no contaminan el core.
