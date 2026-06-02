# Brechas y hallazgos — sesión Objetivo 1 (3 primitivas read-only)

Lo que se descubrió construyendo el bridge SAP + MCP. Marcador 🔶 = hallazgo a recordar.
No es una lista de bugs sin resolver: los técnicos se corrigieron en la sesión; los de
alcance están fuera por diseño (ver `../SAP_AI.md`).

---

## 🔶 Hallazgos técnicos de la OAPI vía pythonnet (resueltos)

### 1. `Helper` no expone `GetObject` — hay que castear a la interfaz `cHelper`
La clase concreta `SAP2000v1.Helper` implementa `GetObject`/`CreateObject`
**explícitamente** desde la interfaz `cHelper`. En pythonnet eso significa que
`Helper().GetObject(...)` lanza `AttributeError`. Solución: `cHelper(Helper())`.
> Se cazó porque el primer `/v1/units` devolvió `AttributeError` en vez del esperado
> `sap_not_running`. La regla "falla ruidosa" lo hizo visible de inmediato.

### 2. Los `ref`/`out` de la OAPI vuelven como tupla
pythonnet no usa parámetros por referencia: el valor de retorno y los `out`/`ref` se
devuelven juntos en una tupla. P. ej. `PointObj.GetCoordCartesian(name, 0,0,0,"Global")`
→ `(ret, x, y, z)`; `GetNameList(0, None)` → `(ret, number, names)`. Los placeholders
de entrada (`0.0`, `None`, `""`) son irrelevantes pero deben ir.

### 3. `cPropFrame.GetNameList` FILTRA por `eFramePropType` — no hay "todos los tipos"
Verificado en vivo: pasar `Rectangular` devolvió las 6 secciones; `I` y `Box`
devolvieron 0. No existe overload sin filtro. Para enumerar el catálogo completo se
**itera sobre los 47 valores del enum** y se unionan los nombres; el tipo de cada
sección sale del bucket que la devolvió (no hace falta `GetTypeOAPI` por sección).
Se **cruza el total contra `PropFrame.Count()`** y se lanza `OAPI_UNEXPECTED_SHAPE` si
no coinciden, para no devolver un catálogo parcial en silencio.

### 4. 🔶 Coordenadas con muchos decimales en unidades `kgf_m_C`
Los joints volvieron con coords como `-10.70648404...` m. Es consistente con un modelo
construido en otras unidades o empujado desde Rhino. **Decisión:** el bridge **expone**
las unidades activas (`/v1/units`) y las coords **tal cual**; no convierte. La conversión
es del cliente, que sabe qué tiene en cada lado (lección destilada de
`RhinoSAP/Utils/UnitConversion.cs`). Validado con el usuario contra la UI: las coords
en metros eran correctas para el modelo.

---

## ◾ Brechas de alcance (fuera por diseño esta fase, orden tentativo siguiente)

Del PROMPT MAESTRO, "PRÓXIMOS PASOS". No bloqueantes; cada una es su propia fase.

- ◾ **Fase 1b** — `get_materials`, `get_section_properties` (dimensiones reales de la
  sección: alto/ancho/área. Hoy `get_sections` da solo nombre + tipo).
- ◾ **Fase 1c** — `get_load_cases`, `get_loads`, `get_combinations`.
- ◾ **Fase 1d** — `run_analysis`, `get_analysis_status`.
- ◾ **Fase 1e** — `get_displacements`, `get_reactions`, `get_forces`, `get_stresses`.
- ◾ **Fase 1f** — `get_modal_results`, `get_response_spectrum`.
- ◾ **Fase 1g** — escritura (`create_joint/frame`, `set_section`…) con dry-run + undo,
  y **namespace/registry** para tocar solo lo propio (evitar el delete-all-then-recreate
  peligroso de `RhinoSAP/SapFrameSynchronizer`).
- ◾ **Fase 1h** — snapshots + diff.
- ◾ **Fase 1i** — poblar `docs/domains/structural/` (códigos, materiales, factores,
  recetas, casos) — conocimiento del cliente, no tools.

---

## 🔶 Cuestiones de contrato a revisar cuando lleguen más consumidores

El bridge será consumido por plugins Rhino y scripts (Objetivo 2). Antes de eso:

- 🔶 **Paginación**: hoy `/v1/joints` y `/v1/frames` devuelven todo en un payload (112 y
  180 filas, sin problema). Con modelos grandes habrá que paginar por cursor, como hace
  el Rhino bridge de geometry_cognition (`next_cursor`). Decidir el shape ANTES de que
  haya clientes que dependan del actual.
- 🔶 **Filtros**: no hay forma de pedir "solo joints con restraint" o "frames de tal
  sección". Cuando se añadan, deben ser filtros agnósticos (por hecho), no por dominio.
- 🔶 **`coord_system`**: hoy fijo en `"Global"`. Si se exponen otros sistemas, el campo
  ya está en el contrato para no romperlo.
- 🔶 **Sesión attach-only**: robustecer a "start new instance" (seam ya previsto en
  `sap_session.py` con el comentario de `mode`). Aditivo, no rompe el contrato.

---

## Nota de método

Sin tests sintéticos: la validación fue **contra el modelo SAP real** del usuario,
cruzando cada primitiva contra la UI. Es el test que importa (igual que en
geometry_cognition). Los hallazgos 1–4 se cazaron porque el código **falla ruidosamente**
en vez de devolver datos plausibles pero falsos.
