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

---

## 🔶 Hallazgos OAPI Fase 1b — materiales + dimensiones de sección (resueltos)

### 5. Los parámetros `out` de tipo **enum** exigen un miembro del enum como placeholder
Para los `Double&`/`String&` out basta pasar `0.0`/`""` (como en la sesión 1). Pero un
parámetro `out` de tipo enum (`eMatType`, `eFramePropType`) **rechaza `0`** —pythonnet
lanza `TypeError: No method matches given arguments`—. Hay que pasar **un miembro real
del enum** (cualquiera; se sobrescribe en el retorno): `prop.GetTypeOAPI(name,
oapi.eFramePropType.Rectangular)`. Por eso los primitives reciben `oapi_namespace`.

### 6. El tipo de material sale de `GetMaterial`, no de `GetTypeOAPI`
`cPropMaterial.GetTypeOAPI(name, ref eMatType, ref SymType)` tiene **dos** out-params;
incluso con el placeholder enum correcto su segunda salida complica la llamada. En
cambio `GetMaterial(name, ref eMatType, ref Color, ref Notes, ref GUID)` devuelve el
`eMatType` como primer out y es la vía limpia. Verificado: MGP10 → `eMatType.NoDesign`
(SAP **no** lo clasifica como madera; el nombre 'MGP10' es etiqueta del usuario).

### 7. `GetMPIsotropic`/`GetWeightAndMass` llevan un `Temp` de **entrada** al final
Firmas reales: `GetMPIsotropic(name, ref E, ref U, ref A, ref G, Temp)` y
`GetWeightAndMass(name, ref W, ref M, Temp)`. El último `Temp` (Double) es **input**
(0.0), no out — va después de los `ref`. `GetMPIsotropic` **solo aplica a materiales
isotrópicos**: para Rebar/Tendon devuelve no-cero o lanza → el bridge reporta los
campos mecánicos como `null`, nunca un default fabricado (validado en vivo: A615Gr60 y
A416Gr270 vuelven con E/nu/A/G nulos pero weight/mass presentes).

### 8. 🔶 `cPropFrame.GetSectProps` devuelve 12 propiedades universales (cualquier forma)
`GetSectProps(name, ref Area, As2, As3, Torsion, I22, I33, S22, S33, Z22, Z33, R22,
R33)` → 12 floats tras `ret`. Disponible para toda sección, independiente de la forma.
Las **dimensiones** sí dependen de la forma (`GetRectangle` → T3=depth, T2=width;
`GetCircle`, `GetISection`… cada una con su firma): el bridge despacha por tipo y
devuelve un dict con las claves nativas de SAP, sin normalizar entre formas (eso sería
interpretación). Tipos no implementados esta fase → `OAPI_UNEXPECTED_SHAPE` con el tipo
recibido, nunca una respuesta parcial. Verificado MGP10_33x73: Area=0.002409 =
0.073×0.033 (cuadra contra cálculo manual).

---

## 🔶 Hallazgos OAPI Fase 1c — definiciones de carga (resueltos)

### 9. Tres colecciones, tres patrones de firma distintos
- `cLoadPatterns.GetLoadType(name, ref eLoadPatternType)` + `GetSelfWTMultiplier(name,
  ref Double)` (ojo: **WT** mayúscula). El enum out exige placeholder de miembro (§5).
- `cLoadCases.GetNameList` **filtra por `eLoadCaseType`** (como `cPropFrame` en §3) pero
  **tiene overload de 2 args sin filtro** que devuelve TODO. Verificado: filtrando a
  `LinearStatic` → 6 casos; sin filtro → 7 (el extra es `MODAL`). El bridge usa el de 2
  args para el catálogo completo. `GetTypeOAPI(name, ref eLoadCaseType, ref Int32
  SubType)` → 2 out-params; se expone el tipo, el SubType no esta fase.

### 10. 🔶 Combinaciones: interfaz `cCombo`, ComboType es **int** crudo, arrays paralelos
- La interfaz es **`cCombo`** (no `cRespCombo`), vía `model.RespCombo`.
- `GetTypeOAPI(name, ref Int32 ComboType)` devuelve un **entero**, no un enum — este
  assembly **no expone `eComboType`**. Mapeo OAPI documentado: 0=Linear Additive,
  1=Envelope, 2=Absolute Add, 3=SRSS, 4=Range Add. El bridge expone **ambos**:
  `combo_type_code` (el int, hecho puro) y `combo_type` (nombre mapeado; 'Unknown' si el
  código cae fuera del set conocido, reportado nunca adivinado). Verificado ENVOLVENTE→1.
- `GetCaseList(name, ref NumberItems, ref eCNameType[] CNameType, ref String[] CName,
  ref Double[] SF)` → 3 **arrays paralelos** tras el count. A diferencia de los enum
  escalares, el array enum out **acepta `None`** como placeholder. El bridge consolida en
  `items=[{case_name, case_type, scale_factor}]` para que el cliente no recomponga
  índices, y **valida que las longitudes coincidan** (mismatch → `oapi_unexpected_shape`,
  nunca zip a la más corta). `eCNameType` ∈ {`LoadCase`, `LoadCombo`}: el combo-of-combo
  es real (p.ej. `D+L` referencia el combo `D`).

### ◾ Observación del modelo (no bug del bridge)
El modelo TEST_01 tiene **tres** patterns tipo Dead: `DEAD` y `PESO PROPIO` con
self-weight=1.0, y `MUERTA` con 0.0. Dos patterns con SW=1.0 contarían el peso propio dos
veces si ambos entraran al mismo combo; el combo `D` usa `PESO PROPIO`+`MUERTA`, así que no
ocurre. Es característica del modelo del usuario — el bridge lo **expone como hecho**, no lo
interpreta ni lo corrige. Integridad referencial de combos verificada: cero referencias
colgantes (todo `LoadCase`→caso existente, todo `LoadCombo`→combo existente).

---

## 🔶 Hallazgos OAPI Fase 1c.2 — cargas aplicadas + composición de case (resueltos)

### 11. `GetLoadDistributed`/`GetLoadForce`: arrays paralelos + `eItemType.Objects`
- `cFrameObj.GetLoadDistributed(Name, ref NumberItems, ref FrameName[], ref LoadPat[],
  ref MyType[], ref CSys[], ref Dir[], ref RD1[], ref RD2[], ref Dist1[], ref Dist2[],
  ref Val1[], ref Val2[], eItemType)` → 11 arrays paralelos tras el count. `eItemType`
  ∈ {Objects=0, Group, SelectedObjects}; se pasa **Objects** para acotar a UN frame.
- **`Dir` es un int crudo** (no hay enum de dirección en el assembly, igual que combo_type
  §10). Mapeo OAPI documentado: 1-3=Local 1/2/3, 4-6=Global X/Y/Z, 7-9=Projected,
  10=Gravity, 11=Projected Gravity. El bridge expone `direction_code` (int) +
  `direction` (nombre; 'Unknown' fuera de rango). `MyType`: 1=Force, 2=Displacement.
  Verificado en TEST_01: códigos presentes 10 (Gravity, 116×) y 2 (Local 2, 38×).
- `cPointObj.GetLoadForce(Name, ref NumberItems, ref PointName[], ref LoadPat[],
  ref LcStep[], ref CSys[], ref F1[], ref F2[], ref F3[], ref M1[], ref M2[], ref M3[],
  eItemType)` → las 6 componentes son **6 arrays planos separados** (F1..M3), NO un array
  2D. Cuidado con la aridad: 12 args (un placeholder None por cada array).

### 12. Composición de case: `cLoadCases.StaticLinear.GetLoads`, guard por tipo
`StaticLinear.GetLoads(Name, ref NumberLoads, ref LoadType[], ref LoadName[], ref SF[])`
da la composición de un caso LinearStatic (3 arrays paralelos). Para otros tipos
(Modal, etc.) la llamada falla (ret≠0), así que el **gate es el tipo** (`GetTypeOAPI`),
no el código de retorno: si no es LinearStatic, el bridge devuelve `case_type` correcto +
`unsupported_case_type=true` + `loads=[]` (información, no error). Verificado: los 6 cases
LinearStatic de TEST_01 aplican 1 pattern del mismo nombre, SF=1.0, LoadType='Load';
MODAL → unsupported.

### ◾ Observación del modelo (no bug; anti-patrón #4)
TEST_01: **78/180 frames** con distributed loads (154 cargas), patterns referenciados
`MUERTA`/`VIENTO`/`VIVA` — todos existentes (cero refs colgantes). **El nombre del pattern
no implica su función**: `VIENTO` tiene cargas con dirección **Gravity**, no de viento
horizontal — el bridge reporta el hecho del OAPI, no interpreta. **0/112 joints** con point
loads: la primitiva `get_point_loads_on_joint` se validó en el **camino vacío** (retorna
`[]` correctamente); la cobertura del camino no-vacío queda pendiente de un modelo con
cargas puntuales en nudos.

---

## ◾ Brechas de alcance (fuera por diseño esta fase, orden tentativo siguiente)

Del PROMPT MAESTRO, "PRÓXIMOS PASOS". No bloqueantes; cada una es su propia fase.

- ✅ **Fase 1b** — `get_materials`, `get_section_properties` (dimensiones reales:
  depth/width + propiedades universales área/inercias). **Hecha** (sesión 2); validada
  en vivo. Sección no-rectangular sigue pendiente (dispatch aditivo, ver hallazgo 8).
- ✅ **Fase 1c** — `get_load_patterns`, `get_load_cases`, `get_combinations`
  (DEFINICIONES de carga). **Hecha** (sesión 3); validada en vivo (6 patterns, 7 cases,
  8 combos; integridad referencial OK).
- ✅ **Fase 1c.2** — `get_distributed_loads_on_frame`, `get_point_loads_on_joint`,
  `get_load_case_details` (cargas APLICADAS + composición de case). **Hecha** (sesión 4);
  validada en vivo (78/180 frames con distributed; point loads camino vacío; MODAL
  unsupported; integridad referencial OK). Falta: point loads en frames, temperature/
  displacement loads (1c.3, aditivos); detalles de cases no-LinearStatic.
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
