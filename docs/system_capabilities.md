# Capacidades del sistema: qué se logró y qué falta

Complemento de [`agnostic_principle.md`](agnostic_principle.md): aquel explica *por qué*
se diseña agnóstico; este muestra *qué se logró* con esos primitivos y *qué falta* —
manteniendo el límite agnóstico como filtro de toda mejora futura.

---

## Lo que el sistema demostró ser capaz de hacer

Partiendo de **geometría cruda y cero semántica de dominio en la infraestructura**, el
stack permitió reconstruir un **edificio completo y su cadena de producción**:

- **Cubicar y validar despiece** de madera contra documentación al 100% por tipo
  (error medio 0.22 mm; ver caso de estudio en `agnostic_principle.md`).
- **Reconstruir la anatomía estructural** de un frontón —cordón inferior empalmado en
  dos tramos, faldones, montantes— por grado de conexión, y **corregir un error de
  análisis** con el mismo dato que ya estaba en `compute_contacts`.
- **Medir la pendiente de cubierta** (30.4°) por tres caminos independientes que
  convergieron: `get_faces`, `obb`, `project_to_plane`.
- **Caracterizar el sistema constructivo entero**: muros SIP portantes
  (75 mm = 56 EPS + 2×9.5 OSB) coronados por cubierta de cerchas, con el **camino de
  cargas verificado** (cubierta → conector Hurricane + ángulos → muro SIP → fundación).
- **Reconstruir el pipeline diseño→fabricación→documentación**: del modelo 3D a las
  elevaciones de fabricación (rebajes, refuerzos, clavijas, etiquetas), al plano de
  aprovechamiento (verificado dimensión a dimensión contra el 3D), a las láminas.

## El valor real de cada tool

| Tool | Qué desbloqueó |
|---|---|
| `obb_*` | Largo/sección reales de piezas rotadas. Validación de despiece 64%→100%. |
| `longest_edge` | "Largo de tronza" vs "arista del bisel" — por qué exponer dos primitivas, no un `get_cut_length()` interpretativo. |
| `compute_contacts` | **Pieza central del razonamiento topológico.** Sin la *ubicación* del contacto no hay grafo estructural, ni empalmes, ni anclajes, ni envolvente. |
| `get_faces/edges/vertices` | Topología consistente (Euler V−E+F=2 verificado): caras con sus aristas. |
| `project_to_plane` | Puente 3D→2D para siluetas, pendientes y posiciones 2D. |
| `inspect_object` (transform + OBB) | Orientación y cota real → distinguir muro vertical de cubierta inclinada, situar fijaciones. |
| `expand_block` | Leer el *interior* de las láminas de producción (rebajes, clavijas, etiquetas). |

## La tesis, validada a escala de edificio

El **principio agnóstico funcionó de punta a punta**: la infraestructura entregó
*hechos* y todo el análisis —cerchas, frontones, muros portantes, camino de cargas,
nesting, flujo de producción— lo compuso el cliente por encima. Los mismos primitivos
servirían para un chasis mecánico, un mueble o un escaneo médico.

**El patrón más valioso**: el sistema no solo describe geometría, permite **reconstruir
intención de diseño** a partir de hechos (dos piezas colineales con contacto
tope-con-tope = cordón empalmado; un panel con más objetos en su elevación = vanos/
refuerzos; `instance_count=0` = documentación pendiente). Eso es razonamiento sobre
hechos, no lectura de etiquetas — y **ocurre en el cliente, no en el MCP.**

## La disciplina sostuvo la confianza

Se detectaron y corrigieron, con datos que el sistema ya producía: dos bugs silenciosos
(parseo de viñeta, warning de degeneración), un error de análisis (empalme de cordones),
un dato erróneo (el "gap de 35 mm", refutado por la posición real de las fijaciones) y
una **sobre-afirmación retirada** (un "79.8% de aprovechamiento" que venía de un empaque
mal reconstruido → sustituido por un rango honesto 80–93%). La regla "falla ruidosa, no
silenciosa" aplicó al código y a las propias conclusiones: donde el modelo no alcanzaba
(el nesting óptimo), se dio un **rango honesto, no un número falso.**

---

## Oportunidades — y el filtro agnóstico que las separa

> **Regla rectora:** que el cliente pudiera reconstruir un edificio entero es la
> *prueba de que los primitivos bastan*, no una lista de features a construir. La
> tentación tras un buen análisis es cristalizarlo en tools (`detect_truss`,
> `compute_nesting`, `audit_cladding`). **Eso es exactamente lo que el principio
> prohíbe.** Si una capacidad solo es útil "para SIP" o "para cubiertas", no entra.

### ✅ Primitivos a construir (agnósticos — pasan el test ácido)

Operaciones geométricas/de transporte puras; el cliente compone el significado:

- **`compute_distance(a, b)` / `find_nearby(id, radius)`** — `compute_contacts` solo ve
  lo que ya se toca; falta medir *separaciones* y proximidad sin contacto.
- **`compute_2d_boolean`** sobre polígonos de `project_to_plane` — unión/intersección/
  diferencia. (El cliente la usa para aprovechamiento o detección de huecos; el MCP no
  nestea ni nombra "vano".)
- **Posiciones 2D reales de piezas proyectadas** — exponer *dónde* cae cada pieza, no
  "el plan de corte". El cálculo de aprovechamiento es del cliente.
- **`compute_contacts` entre dos conjuntos (A×B)** — acota el set, evita enumerar GUIDs
  a mano y el O(n²); sigue siendo detección de contacto pura.
- **Higiene de transporte**: paginación por cursor (el bridge ya expone `next_cursor`),
  modo resumen en tools pesadas, `bbox_center`/geometría no-null en la ruta de `fields`.
- **Anomalías estrictamente observacionales** (Fase 4.3, con cuidado): duplicados
  exactos (mismo bbox+tipo+transform), geometría degenerada, objeto al que le faltan
  claves user_text que otros de su grupo sí tienen. **Reportar la rareza, jamás
  calificarla como "error".**

### ❌ Recetas de cliente (razonamiento de dominio — NUNCA tools)

Todo esto se queda como conocimiento de la sesión/prompt, no como código del MCP:

- **Nesting / plan de corte óptimo** — optimización con criterio de dominio (minimizar
  desperdicio de *tablero*). El MCP da posiciones y booleanas; el cliente nestea.
- **Detección de elementos compuestos** (empalme de cordones) — el MCP entrega el
  contacto tope-con-tope; que sea "un cordón empalmado" lo concluye el cliente.
- **Mapeo modelo↔documentación / QA de producción** — "panel con vanos", "documentación
  pendiente" es dominio. El MCP da `instance_count` y conteos; el cliente interpreta.
- **Clasificación de roles estructurales** (cordón/montante/diagonal, muro/cubierta) —
  emerge del grado de conexión + dimensiones, en el cliente.
- Cualquier `detect_*`, `analyze_*`, `audit_*` cuyo nombre describa un **uso** y no una
  **operación geométrica** (ver heurística del nombre en `agnostic_principle.md`).

### Brechas del plan v2 (Tier 3)

- **Fase 4** — `assert_change` por valores, diff por bloques (la parte de detección de
  anomalías observacionales ya está acotada arriba como agnóstica).
- **Fase 5** — visibilidad (`IsHidden`), color, display mode.

---

**En una frase**: el sistema pasó de "razonar sobre una cercha" a **reconstruir un
edificio completo y auditar su cadena de producción**, manteniéndose estrictamente
agnóstico; y las mejoras restantes son **solo más primitivos de medición + higiene de
transporte** — todo análisis de dominio se queda, por diseño, en el cliente.

---

## Estado actual del sistema (checklist)

> **El principio agnóstico aplica también a este checklist, no solo a las tools.** Una
> frase descriptiva puede "colar" lenguaje de dominio sin que ningún test la atrape:
> el set es canónicamente completo para **razonamiento geométrico**; que el cliente lo
> aplique a un dominio estructural, mecánico, médico o geológico es decisión suya. Si
> un item nombra un uso ("nesting", "aprovechamiento") en vez de la operación, está mal
> redactado. Para "qué cambió y cuándo", ver [`CHANGELOG.md`](CHANGELOG.md).

### ✅ Incorporado y validado en vivo

| Categoría | Tool / capacidad | Estado |
|---|---|---|
| Medición | `obb_dimensions` / `obb_longest/mid/shortest`, `longest_edge` | ✅ validado |
| Medición | `get_vertices`, `get_edges`, `get_faces` (con topología `edge_indices`) | ✅ validado |
| Relación espacial | `compute_contacts` (point/curve/surface + ubicación) | ✅ validado |
| Relación espacial | `compute_distance` (mín. superficie-superficie + bbox_gap) | ✅ validado |
| Relación espacial | `find_nearby` (objetos dentro de radio, ordenados) | ✅ validado |
| Proyección | `project_to_plane` (3D→2D, polígonos UV) | ✅ validado |
| Descubrimiento | `describe_model`, `inspect_object` | ✅ |
| Consulta | `query_objects` (filtros AND, live/snapshot, paginación) | ✅ validado |
| Cómputo | `aggregate` (group-by + count/sum/avg/min/max) | ✅ |
| Bloques | `list_block_definitions`, `expand_block`, `bill_of_materials` (con summary) | ✅ validado |
| Snapshots | `take_snapshot`/`list`/`delete`/`prune_snapshots` | ✅ |
| Cambios | `diff_snapshots`, `diff_object`, `assert_change` | ✅ |
| Transporte | paginación (`offset`/`next_offset`) + `summary` en tools pesadas | ✅ validado |
| Docs | `agnostic_principle.md`, `system_capabilities.md` | ✅ |
| Repo | GitHub `JNavarro-Craft/geometry_cognition`, sincronizado | ✅ |

### ❌ Falta por abordar (todo agnóstico o de cliente, nada bloqueante)

| Categoría | Item | Tipo |
|---|---|---|
| Primitivo | `compute_2d_boolean` — unión/intersección/diferencia de polígonos | agnóstico |
| Primitivo | Posiciones 2D de objetos en una disposición existente (derivable de `inspect_object` + `project_to_plane`) | agnóstico |
| Primitivo | `compute_contacts` / `compute_distance` entre dos conjuntos (A×B) | agnóstico |
| Primitivo | `sample_curve` — muestreo de curvas | agnóstico (Tier 2) |
| Plan v2 — Fase 4 | `assert_change` por valores; diff por bloques; anomalías observacionales | agnóstico |
| Plan v2 — Fase 5 | visibilidad (`IsHidden`), color, display mode | agnóstico |
| Menor | `bbox_center`/geometría null en ruta de `fields` | técnico |
| Menor | distinguir `filter_unknown_key` de `filter_valid_empty` en el MCP | técnico |
| Mantenimiento | sin suite automatizada para tools nuevas (validación manual en vivo) | proceso |
| Mantenimiento | poda de snapshots viejos acumulados | proceso |

### 🚫 Fuera por diseño (leaks — nunca tools)

Nesting / plan de corte óptimo · detección de empalmes · QA modelo↔documentación ·
clasificación de roles · cualquier `detect_*`/`analyze_*`/`audit_*`. Son razonamiento
de cliente sobre los primitivos, no infraestructura.
