# El principio agnóstico

El bridge y el MCP exponen **hechos geométricos y de atributo universales**. Nunca
interpretan qué representa un objeto. Toda semántica de dominio ("esto es una cercha",
"este es el largo de corte", "esto es una abertura") vive en el cliente.

Este documento es el filtro para decidir si una capacidad nueva entra o no.

## Las cuatro preguntas del test ácida

Antes de añadir cualquier tool, campo o capacidad:

1. **¿Existiría esta propiedad en un dominio totalmente distinto** (un escaneo médico,
   un personaje 3D, un ensamblaje mecánico)?
2. **¿Requiere que el sistema sepa qué representa el objeto** para computarla?
3. **¿El cliente puede derivarla con primitivos crudos** si se los doy?
4. **¿Un LLM razonablemente capaz puede llegar a esa conclusión** si le doy los datos
   geométricos crudos?

Si la (4) es **sí** → NO construir la tool. Solo asegurar que los datos crudos estén
disponibles, y dejar que el LLM razone.

## Caso de estudio — `obb_longest` vs `longest_edge`

Validado contra un modelo de cubierta SIP real.

Ambas primitivas pasan el test ácida individualmente: existen en cualquier sólido,
ninguna interpreta qué representa la pieza, ambas requieren un engine geométrico para
computarse.

Al cruzarlas contra las listas de despiece (LDP) reales del modelo:

- **`obb_longest`** cuadró con la LDP en el **95%** de los casos. Es el *largo de
  tronza*: el OBB encierra la pieza completa, incluida la punta del bisel.
- **`longest_edge`** cuadró en el **72%**. Es la *arista más larga del sólido*; en una
  pieza con corte a inglete, esa arista es la **cara corta** del bisel, no el largo de
  tronza.

Si hubiéramos construido una sola tool `get_cut_length()`, habría estado **mal en
algunos casos**: "largo de corte" depende del proceso de fabricación (¿se mide la
tronza o la cara?), y eso es **dominio**. Exponer las dos primitivas dejó que el cliente
eligiera cuál aplica a su proceso.

**Lección:** cuando dos primitivas geométricas similares miden cosas distintas, expón
las dos. No las interpretes ni elijas por el cliente.

## Ejemplos de uso correcto

Operaciones geométricas puras; el cliente compone el significado:

- `obb_dimensions`, `obb_longest` / `obb_mid` / `obb_shortest`, `longest_edge`,
  `volume`, `area`
- `compute_contacts(object_ids)` → pares en contacto **con la ubicación** del contacto
- `project_to_plane(elements, plane)` → polígonos 2D
- `get_vertices` / `get_edges` / `get_faces(object_id)` → geometría detallada
- `aggregate`, operaciones SQL-like sobre los datos

## Ejemplos de leak (NO construir)

Cada uno lo deduce un LLM a partir de los primitivos de arriba:

- `find_extremity_contacts` — el LLM lo deduce con OBB + `compute_contacts`
- `detect_apertures` — "aperture" describe un **uso**, no una operación
- `find_subgraphs(pattern="cercha")` — "cercha" es dominio
- `analyze_coverage` — el LLM compara áreas si lo necesita
- `build_contact_graph` — el LLM construye el grafo desde `compute_contacts`
- `find_enclosed_regions` — el LLM ve los huecos en la proyección 2D

## Heurística del nombre

- Si el nombre describe un **USO** específico (`apertures`, `extremity_contacts`),
  probablemente es leak.
- Si describe una **OPERACIÓN** geométrica (`contacts`, `projection`, `edges`), está
  bien.

## Regla final

Si te encuentras pensando *"esto sería útil para [caso de uso]"*, **para**. Construye
el primitivo que habilita ese uso, no el uso mismo.
