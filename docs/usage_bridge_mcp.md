# Cómo usar bien el bridge y el MCP `developer-server`

Guía para cualquier sesión (humana o Claude) que vaya a leer/analizar un modelo Rhino a
través de `developer-server`. Léela antes de filtrar. Está escrita a partir de un error
real de una sesión previa (ver "Post-mortem" al final) que se podía haber evitado.

## Regla de oro: DESCUBRIR antes de FILTRAR

No adivines nombres de capas, tipos ni claves de user_text. Llama primero a
`describe_model()` y usa los valores reales que devuelve.

```
describe_model()        # ¿qué layers, types, user_text keys, bloques hay AQUÍ?
   ↓ (usar valores reales del catálogo)
query_objects(filters)  # consulta filtrada honesta
```

`describe_model()` devuelve, del modelo activo:
- `layers`: nombres reales (full-path, `Parent::Child`) con conteo.
- `types`: tipos Rhino presentes (`Brep`, `Mesh`, `Annotation`, ...) con conteo.
- `groups`, `block_definitions` (con nº de instancias).
- `user_text_keys`: cada clave con `occurrence_count`, `distinct_values_count`,
  `example_value`. **Esta es la fuente de verdad de qué claves existen y cómo se
  escriben** (incluye typos reales del modelo, que el bridge no corrige).

## Contrato de filtros (nombres EXACTOS)

Tanto `query_objects(filters=...)` como `take_snapshot(...)` terminan en el mismo
contrato de filtros del bridge. Las claves válidas son **exactamente** estas:

| clave | tipo | significado |
|---|---|---|
| `layers` | `list[str]` | nombres de capa exactos (full-path) |
| `types` | `list[str]` | tipos Rhino exactos |
| `name_contains` | `str` | substring del nombre, case-insensitive |
| `has_user_text` | `bool` | el objeto tiene (o no) algún user_text |
| `user_text_key` | `str` | el objeto tiene esta clave de user_text |
| `user_text_value` | `str` | el objeto tiene este valor en algún user_text |
| `bbox_intersects` | `{min:[x,y,z], max:[x,y,z]}` | el bbox intersecta esta caja |

Los filtros son **AND-combinados** y **case-sensitive** en valores. Las capas son
**full-path** con `::`.

En `query_objects` además existe `user_text: {clave: valor}` (pares exactos) e
`is_block_instance: bool`, que el MCP resuelve del lado Python.

### Claves que parecen válidas pero NO lo son

Estas se **ignoran en silencio** y hacen que el filtro coincida con TODO:

- `layer` / `type` (singular) → son `layers` / `types`.
- `where`, `filter`, `query` como envoltorio → no existe; los filtros van directo.
- `name` → es `name_contains`.
- `bbox` → es `bbox_intersects`.

Si una clave de filtro no se reconoce, el bridge ahora devuelve
`filter_warnings.unknown_filter_keys` en la respuesta de la query cruda. Si la ves, tu
filtro no se aplicó.

## Cómo saber si tu filtro realmente se aplicó

1. **`matched_count`**: si pediste una capa pequeña y `matched_count` es el total de la
   escena, tu filtro no se aplicó (clave mal escrita). Compara contra el conteo de esa
   capa en `describe_model()`.
2. **`take_snapshot` → `filter_report.status`**:
   - `ok`: sin filtro, o filtro aplicado.
   - `filter_valid_empty`: filtro aplicado, 0 coincidencias (resultado confiable).
   - `filter_not_applied`: la estrategia live falló y el fallback devolvió el modelo
     COMPLETO sin filtrar. **No** trates `matched_count` como filtrado.
3. **Bridge crudo**: `filter_warnings.unknown_filter_keys` lista claves no reconocidas.

## Modelos grandes (decenas de miles de objetos)

- Filtra server-side con las claves correctas: el bridge solo devuelve lo que coincide
  (no bajes la escena entera para filtrar en cliente).
- Usa `limit` y, en la query cruda, la paginación por `cursor`/`next_cursor`.
- Consulta un estado pasado con `query_objects(source="<label_de_snapshot>")` en vez de
  re-extraer el modelo vivo.

## Qué puede y qué NO puede hoy

**Puede (lectura):** contar/inventariar por capa/tipo/grupo, leer user_text por objeto,
catálogo de claves (`describe_model`), bbox + face/edge count + volume/area, diff entre
snapshots, detectar bloques (nombre + nº de instancias), **leer el texto de anotaciones**
(`inspect_object` → `annotation_text`, y se proyecta al snapshot), **entrar a la
definición de un bloque** (`list_block_definitions` + `expand_block` → geometría, user_text,
materiales y texto internos, sin transform).

**No puede todavía (carencias reales del sistema, no errores de uso):**
- Geometría real (vértices/curvas/contorno) — solo bbox.
- Expandir instancias con su transform aplicado en espacio modelo (1.3b) — `expand_block`
  da el contenido crudo de la definición, sin posicionar cada instancia.
- Agregación server-side (sumas/group-by en una llamada) — hoy se agrega en cliente.
- **Escribir/editar** el modelo — el bridge es read-only.

(Estas carencias están en el plan: `docs/plan_bridge_developer_v2.md`.)

## El bridge/MCP es agnóstico al dominio

No codifica ningún sistema constructivo, material, formato de OT ni vocabulario de
oficina. Capas, claves de user_text y nombres de bloque son **datos opacos** que pasan
por el bridge. La semántica de negocio (qué significa una clave, qué es un error de
modelado, cómo se cotiza) la pone la sesión de Claude, no el MCP.

---

## Post-mortem: el error de la sesión previa (para no repetirlo)

Una sesión concluyó que **"el bridge no filtra server-side"** y lo marcó como brecha
bloqueante #1. Era **incorrecto**. Qué pasó realmente:

- La sesión envió el filtro como `{"where": {"layer": {"eq": "..."}}}` y como `layer`/
  `type` planos. **Ninguna de esas claves existe** en el contrato (`layers`, `types`,
  `name_contains`, ...).
- El deserializador del bridge (.NET `DataContractJsonSerializer`) **descarta claves
  desconocidas sin error**. Filtro desconocido → filtro nulo → un filtro nulo deja pasar
  TODO → `matched_count` = total de la escena, con `200 OK`.
- La sesión observó el síntoma correcto (`matched_count` = total) pero infirió la causa
  equivocada ("no filtra") en vez de la real ("usé el nombre de filtro equivocado").
- Consecuencia: para mirar ~46 objetos de una capa, paginó ~62.000 objetos de toda la
  escena, lo que además disparó timeouts que se atribuyeron a la misma falsa causa.

**La lección, en una frase:** lo único que se observó fue *"matched_count dio el total"*;
*"no filtra server-side"* fue una **conclusión**, no una observación. El bridge sí filtra,
con otro nombre.

**Qué cambió para que no vuelva a pasar:**
- El bridge ahora devuelve `filter_warnings.unknown_filter_keys` ante claves no
  reconocidas (deja de ser silencioso).
- Se corrigió un bug equivalente dentro del propio MCP: `take_snapshot(name=...)` y
  `bbox=...` emitían `name`/`bbox` en vez de `name_contains`/`bbox_intersects`, así que
  esos filtros se ignoraban — el mismo error, pero en nuestro código.
- `describe_model()` y los docstrings de las tools ahora documentan el contrato exacto
  y empujan la regla "descubrir antes de filtrar".
