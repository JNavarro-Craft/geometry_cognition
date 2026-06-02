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

## 🔶 Hallazgos OAPI Fase 1d — análisis (run + status) (resueltos)

### 13. `RunAnalysis()` NO toma cases; el modelo es flag-then-run
`cAnalyze.RunAnalysis()` **no tiene argumentos** — no existe overload "corre estos cases".
El prompt asumía `RunAnalysis(cases_to_run)`; la realidad es un modelo de **dos pasos**:
`SetRunCaseFlag(Name, Run, All)` marca qué cases correr, luego `RunAnalysis()` corre todo
lo marcado. Para `cases_to_run` el bridge: lee los flags actuales, marca solo el subset,
corre, y **restaura los flags originales** (sin efecto colateral en qué está marcado).

### 14. `GetCaseStatus`/`GetRunCaseFlag` son globales (arrays paralelos), status = int
- `GetCaseStatus(ref NumberItems, ref CaseName[], ref Status[])` **no toma nombre** — da
  TODOS los cases con su Status. `GetRunCaseFlag(ref NumberItems, ref CaseName[],
  ref Run[])` igual: **4 valores** `(ret, n, names, flags)`.
- `Status` es **int crudo** (no enum): 1=Not Run, 2=Could Not Start, 3=Not Finished,
  4=Finished. El bridge mapea a nombre + `has_run`=(code==4). Un case que no convergió
  (2 ó 3) se reporta como hecho — el bridge nunca dice "tu modelo está mal".
- `GetModelIsLocked()`→bool; tras un run exitoso pasa a **true** (resultados vigentes).

### 🐛 Bug cazado en validación (no silencioso): unpack de GetRunCaseFlag
La primera versión desempaquetó `GetRunCaseFlag` como 3 valores; devuelve **4**
(`ret, n, names, flags`) → `ValueError: too many values to unpack` → HTTP 500. Se cazó
**en la validación del camino de error** (run con case inexistente), no en producción
silenciosa. Corregido a 4-tuple. Lección: la "falla ruidosa" funcionó — un 500 visible en
vez de un dato plausible-pero-falso.

### Decisión arquitectónica: POST muta, GET lee
Primera operación **mutante** del bridge: `POST /v1/analysis/run` (cambia estado de
cómputo, puede lockear) vs `GET /v1/analysis/status` (read-safe). El método HTTP señala
intent al consumidor. NO confirm (no destructivo, re-correr es idempotente — SAP saltea
cases con resultados vigentes: 2º run = 0.0s). El confirm explícito se exigirá en Fase 1g
(modificar el modelo). Errores de análisis (singular matrix, etc.): si `RunAnalysis` da
ret≠0 → `oapi_call_failed` con el código; el cliente lo interpreta, el bridge no.

---

## 🔶 Hallazgos OAPI Fase 1e — resultados de análisis (resueltos)

### 15. `cAnalysisResults` shapes: 13 elementos (joints), 15 (frames), componentes en 7..12
- `JointDispl`/`JointReact(Name, eItemTypeElm, ref NumberResults, ref Obj[], ref Elm[],
  ref LoadCase[], ref StepType[], ref StepNum[], ref C1[]..C6[])` → tupla de **13**
  elementos: `ret(0), n(1), Obj(2), Elm(3), LoadCase(4), StepType(5), StepNum(6),
  C1..C6(7..12)`. **Los componentes están en 7..12, NO 8..13** — cazado en pre-vuelo
  (un IndexError al asumir 8..14, la misma clase del 4-tuple de Fase 1d §14). Displ:
  U1/U2/U3/R1/R2/R3. React: F1/F2/F3/M1/M2/M3.
- `FrameForce(...)` → **15** elementos: `ret, n, Obj, ObjSta(3), Elm, ElmSta, LoadCase,
  StepType, StepNum, P(9), V2, V3, T, M2, M3(14)`. `ObjSta` = distancia absoluta desde
  el i-end; la relativa se deriva como `ObjSta / longitud` (longitud de FrameObj.GetPoints
  + coords). Múltiples stations por frame (4133 → 2).

### 16. Resultados exigen selección de output + el guard de case
- **Hay que seleccionar el case para output ANTES de leer**:
  `Setup.DeselectAllCasesAndCombosForOutput()` + `SetCaseSelectedForOutput(name, True)`.
  Sin selección, la llamada devuelve `ret=1, NumberResults=0` — silencio confuso. Por eso
  el bridge **no** se fía de ese silencio: usa `Analyze.GetCaseStatus` (status==4 Finished)
  para detectar un case no corrido y devolver `case_not_run` estructurado (409, client-
  fixable). Un case no-LinearStatic → `unsupported_case_type` (no se intenta leer).
- `StepType` viene `None` y `StepNum=0.0` para LinearStatic — manejado.
- **Equilibrio global verificado** (criterio de validación): suma de reacciones de los 30
  nudos restringidos para MUERTA = F3 1290.86 kgf (vertical), F1/F2 ≈ 0 — equilibra el
  peso de las 78 cargas MUERTA (verticales/Gravity). El bridge NO computa esto; es una
  composición del cliente sobre los hechos.
- Dos códigos de error nuevos: `CASE_NOT_RUN` (409, precondición), `UNSUPPORTED_CASE_TYPE`
  (502). Anti-patrón #4: un displacement grande es un número, no "falla".

---

## 🔶 Hallazgos OAPI Fase 1e.5 — model settings (resueltos)

### 17. `GetActiveDOF`, units: las variantes `_2` no existen en SAP26
- `cAnalyze.GetActiveDOF(ref Boolean[] DOF)` → `(ret, dof[6])` en orden
  **[U1, U2, U3, R1, R2, R3]** — misma convención de índices que joint restraints/
  reactions/displacements (consistencia transversal). TEST_01: `[T,F,T,F,T,F]` (U1/U3/R2
  activos) — el patrón Plane Frame XZ, **reportado como hecho, no nombrado** (el cliente lo
  reconoce; "Plane Frame" no es vocabulario del bridge).
- **Las variantes `_2` de units NO existen en este assembly**: solo `GetPresentUnits()` y
  `GetDatabaseUnits()`, cada una devuelve el `eUnits` completo (que **ya incluye la
  temperatura** — `kgf_m_C` lleva la C de Celsius), así que no hace falta una lectura de
  temperatura aparte. El prompt asumía usar `_2`; el plano basta. TEST_01: present ==
  database == `kgf_m_C` (en este modelo coinciden; el contrato expone ambos por si difieren).
- `GetModelIsLocked()` callable en cualquier estado. El helper de units se refactorizó a
  `_units_response(enum)` reutilizable por present y database (sin duplicar code→nombre).

> Nota de shape: `present_units`/`database_units` reutilizan el modelo `UnitsResponse`
> existente, cuyo campo interno se llama `present_units` — de ahí el anidado
> `present_units: {present_units: "kgf_m_C", ...}`. Se prefirió reutilizar el contrato a
> introducir un shape nuevo de units.

---

## 🔶 Hallazgos OAPI Fase 1g.1 — savepoints (write-side, resueltos)

### 18. `cFile.Save_2` NO existe en SAP26 — solo `Save`; y `Save` actúa como "Save As"
- El design doc nombró `cFile.Save_2`; **no existe en este assembly**. La firma real es
  `cFile.Save(String FileName)` → 0 OK. `cFile.OpenFile(String FileName)` → 0 OK. (Anti-
  patrón #5 cazó esto: probar la firma antes de asumir la convención.)
- ⚠️ **`Save` reapunta el modelo en memoria al nuevo path** (como "Save As"): tras
  `Save(sp_path)`, `GetModelFilename` devuelve `sp_path`, no el original. Por eso
  `create_savepoint` hace **Save al savepoint y LUEGO OpenFile del original**, dejando la
  sesión sobre el modelo del usuario — si no, el usuario quedaría trabajando en silencio
  dentro del savepoint.
- **El cSapModel sobrevive a OpenFile** (mismo proceso SAP, modelo nuevo): `GetModelIsLocked`
  /`GetModelFilename` responden sin error tras OpenFile, sin re-attach. `restore_savepoint`
  se apoya en esto; validado en vivo (get_joints=112 y get_model_settings OK tras restore).
- `GetModelFilename(IncludePath: bool)` → str absoluto con True.

### 19. 🔶 restore deja la sesión en el ARCHIVO del savepoint (no en el original)
Por diseño, `restore_savepoint` hace `OpenFile(sp_path)` → la sesión queda cargada en el
`.sdb` del savepoint, no en el modelo original. Consecuencia observable: tras un restore,
`list_savepoints` busca savepoints de `<model>__sp_<name>` (el nuevo nombre cargado) y da
vacío; para volver al flujo de TEST_01 el cliente debe reabrir TEST_01. Es coherente con
"restore reemplaza el modelo cargado", pero es un filo que el cliente debe conocer (queda
documentado, no parcheado).

### 20. ◾ SAP crea archivos auxiliares junto al `.sdb`
Al guardar, SAP genera `.$2k`, `.ico`, `.sbk` (y tras análisis `.OUT`, `.LOG`) junto al
`.sdb`. Un `delete_savepoint` futuro (Fase 1g posterior) deberá limpiar también esos
auxiliares, no solo el `.sdb`. Esta fase no implementa delete, así que solo se anota.

### Validación end-to-end del ciclo de undo (criterio 5 + cruzado)
Ciclo completo verificado vía MCP: baseline `active_dof=[T,F,T,F,T,F]` → create_savepoint
→ cambio real (SetActiveDOF activando R1 → `[T,F,T,T,T,F]`, guardado) → restore_savepoint
(confirm=true) → `active_dof` **volvió a `[T,F,T,F,T,F]`**. El restore revierte un cambio
real. confirm_required sin confirm; savepoint_not_found; savepoint_already_exists (rechazo,
no sobrescritura); dry_run en create y restore (sin escribir/reemplazar) — todos validados.

---

## 🔶 Hallazgos OAPI Fase 1g.2 — set_active_dof + audit log (resueltos)

### 21. `cAnalyze.SetActiveDOF`: input Boolean[], rechaza si locked, NO valida degenerados
- Firma `SetActiveDOF(Boolean[] DOF)` → toma un `System.Array[Boolean]` de 6 (pythonnet no
  acepta una lista Python directa) y devuelve `(ret, dof)` vía tupla; el primer elemento es
  el status.
- **Sobre modelo LOCKED**: retorna **ret=1 y NO aplica** el cambio, y **NO auto-deslockea**.
  El bridge relaya eso como `oapi_call_failed` — política explícita: el bridge **no** hace
  unlock proactivo (el cliente decide). Validado en pre-vuelo.
- **SAP NO valida casos degenerados**: `SetActiveDOF([F,F,F,F,F,F])` se aplicó con ret=0.
  El bridge tampoco juzga (anti-patrón #4) — solo valida **shape** (exactamente 6 booleans).
  Si el patrón es estructuralmente absurdo, es decisión del cliente, no del bridge.
- Cambiar active_dof en un modelo unlocked no toca por sí mismo el lock state.

### Audit log (write_side_design.md §logging)
- Módulo compartido `sap_bridge/audit_log.py`: una línea JSONL por operación write a
  `logs/writes_<YYYY-MM-DD>.jsonl` (timestamp ISO-8601, operation, parameters, result,
  result_details, elapsed_ms). Context manager `audited()` que **también audita los
  errores** (`error_<code>`) re-lanzándolos. Escritura plana `open(..,"a")` + json.dumps,
  sin deps; un fallo de logging **nunca rompe** la operación (se traga y warnea).
- **Decisión: `list_savepoints` NO se loguea** — es read-only (filesystem scan, no muta);
  el audit trail responde "qué cambió y cuándo". Sí se loguean create/restore_savepoint
  (retrofit) y set_active_dof. Validado: 7 entradas tras el ciclo, incl. errores.

### ◾ Filo menor: dos códigos para input mal formado
La validación de shape de `active_dof` da **422** (pydantic, tipo no-lista, rechazado en el
contrato) o **502 `oapi_unexpected_shape`** (longitud ≠ 6, en el primitive). Ambos son
rechazos claros sin crash, pero `oapi_unexpected_shape` es impreciso para "input del
cliente mal formado" (no falló la OAPI). Posible mejora futura: un código `invalid_input`
dedicado. Anotado, no parcheado (no bloquea).

---

## 🔶 Hallazgos OAPI Fase 1g.3 — set_present_units (resueltos)

### 22. `SetPresentUnits(eUnits)` toma el MIEMBRO del enum, no un int; códigos ≠ asumidos
- `cSapModel.SetPresentUnits(eUnits Units)` → exige el **miembro del enum** (un int crudo
  lanza `TypeError`), retorna 0 OK. Por eso la primitiva resuelve name→miembro con
  `getattr(oapi.eUnits, name)` (en `units.resolve_unit_system`), no a un int.
- ⚠️ **Los códigos del enum NO son los que asumía el prompt**: `N_m_C` es **10**, no 7
  (7 es `kgf_mm_C`). Resolver por NOMBRE contra el enum vivo evita toda esa clase de error
  (anti-patrón #5). El conjunto soportado (16 sistemas) sale del propio enum, así que
  **coincide exactamente con lo que el read-side expone** — sin tabla duplicada que derive.
- Cambiar present_units **NO** cambia `model_is_locked` (es display preference). Idempotente
  (setear el valor actual → ret 0, `change_summary: 'X → X'`).
- Código de error nuevo: `UNKNOWN_UNIT_SYSTEM` (409, lista los nombres soportados) — más
  claro que reusar `oapi_unexpected_shape` para input del cliente (empieza a resolver el
  filo anotado en §21).

### ✅ TEST KEY — propagación de units a TODO el read-side (validado positivo)
Cambiar present_units a N_m_C y re-leer el read-side:
- **Distancias se mantienen**: joint 9 x = -13.7687 en kgf_m_C y en N_m_C (metros es metros).
- **Fuerzas re-escalan**: frame 4133 distributed load 19.4 → 190.249, **factor 9.80665
  exacto** (1 kgf = 9.80665 N). El campo `units` de cada respuesta cambió a N_m_C.
- Tras restore, todo volvió a kgf_m_C / 19.4. **El bridge respeta present_units de forma
  consistente en todo el read-side** — y NO convierte nada él mismo: SAP reformatea según
  el sistema y el bridge relaya (la decisión agnóstica de raíz, sin el leak de unidades del
  C# heredado). No es un bug — es el comportamiento correcto.

### Generalización de la plantilla write
set_present_units siguió la plantilla de set_active_dof (validar → dry_run → confirm →
aplicar → audit) **sin fricción**. Confirma la plantilla como reusable para todo write de
setting global. El shape `UnitsChange` reutiliza `UnitsResponse` (campo interno
`present_units`) en vez de un `{name,code}` nuevo — consistencia del contrato sobre la
sugerencia del prompt.

---

## 🔶 Hallazgos OAPI Fase 1g.4 — create_material + isotropic + namespace (resueltos)

### 23. `SetMaterial` SOBRESCRIBE silencioso; NO hay 'Wood'; `SetMPIsotropic` deriva G
- `cPropMaterial.SetMaterial(Name, eMatType, Color, Notes, GUID)` → toma el **miembro**
  eMatType (resuelto por nombre, no int), retorna 0. ⚠️ **Con un nombre EXISTENTE
  sobrescribe en silencio** (ret=0, sin error, sin duplicado). Por eso el guard
  `name_already_exists` (consultar get_materials antes) es esencial — sin él un create
  clobberaría un material del usuario. Justifica la decisión #1 del design doc en la práctica.
- **eMatType tiene 8 miembros**: Steel, Concrete, NoDesign, Aluminum, ColdFormed, Rebar,
  Tendon, Masonry. **NO existe 'Wood'** (el prompt lo usaba) — la madera se modela como
  `NoDesign` (lo que usa MGP10). Resolver name→miembro por reflexión cazó esto y devuelve
  `unknown_material_type` con la lista real (anti-patrón #5).
- `cPropMaterial.SetMPIsotropic(Name, E, U, A, Temp)` → 4 inputs (NO toma G; SAP **deriva**
  G = E/(2(1+U)), verificado), Temp input (0.0), retorna 0. Material inexistente → ret=1.
  Valores en **present units**; el bridge NO convierte (responsabilidad del cliente).
- Un material recién creado por SetMaterial **trae propiedades default** de SAP (no null:
  E≈2.53e9, nu=0.2), no vacías — por eso create + set_properties son atómicas separadas.

### Namespace en código (write_side_design.md §1, primera vez operativo)
`namespace.py`: `get_bridge_prefix` (env `BRIDGE_NAMESPACE_PREFIX`, default `AI_`, leído una
vez), `has_bridge_prefix` (startswith), `assert_prefix_required` (PREFIX_REQUIRED),
`assert_no_conflict` (NAME_ALREADY_EXISTS). Enforcement UNIVERSAL: todo create lo usa. El
prefijo es del SISTEMA, no se hardcodea fuera de aquí. Validado: create sin prefijo →
rechazo; **distinción de ownership confirmada** — set_properties sobre material `AI_` aplica
sin confirm, sobre `MGP10` (preexistente) exige confirm (regla §5.1). El savepoint revierte
en bloque tanto el material AI_ nuevo como la modificación al MGP10 preexistente.

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
- ✅ **Fase 1d** — `run_analysis`, `get_analysis_status` (PRIMER cruce mutante).
  **Hecha** (sesión 5); validada en vivo (run 7 cases en 5.8s → todos Finished, modelo
  locked; subset con restauración de flags; idempotencia 0.0s; error path estructurado;
  integridad referencial OK). POST muta / GET lee. Falta cancel (OAPI no lo expone fiable).
- ✅ **Fase 1e** — `get_joint_displacements`, `get_joint_reactions`, `get_frame_forces`
  (resultados post-análisis; cierra el ciclo input→análisis→output). **Hecha** (sesión 6);
  validada en vivo (joint 9 restringido: reacción F1/F3, displ solo r2; frame 4133: 2
  stations con M3≠0; equilibrio global F3=1290.86 kgf; case_not_run + unsupported_case_type
  + case inexistente). Falta `get_frame_stresses` (1e.2) y resultados de envelope (1e.3).
- ◾ **Fase 1f** — `get_modal_results`, `get_response_spectrum`.
- 🟡 **Fase 1g** — escritura, gobernada por [`write_side_design.md`](write_side_design.md)
  (namespace por prefijo, dry-run, savepoints, stop-on-first-failure, confirm).
  - ✅ **1g.1** — savepoints (`create_savepoint`, `restore_savepoint`, `list_savepoints`):
    infraestructura de undo. **Hecha** (sesión 8); ciclo de undo validado en vivo. Las
    primitivas escriben el filesystem, no el modelo en memoria.
  - ✅ **1g.2** — `set_active_dof` (primer write que MUTA el modelo en memoria; setting
    global → confirm obligatorio) + **audit logging** compartido (retrofit a savepoints).
    **Hecha** (sesión 9); ciclo del patrón cliente validado end-to-end (savepoint → preview
    → rechazo-sin-confirm → aplicar → restore). 21 primitivas.
  - ✅ **1g.3** — `set_present_units` (segundo setting global; valida que la plantilla
    generaliza). **Hecha** (sesión 10); ciclo del patrón cliente + TEST KEY de propagación
    de units validados. 22 primitivas.
  - ✅ **1g.4** — SALTO CUALITATIVO: `namespace.py` (prefijo en código) + `create_material`
    + `set_material_properties_isotropic`. Primer write sobre objetos. **Hecha** (sesión 11);
    ciclo de 13 pasos validado (prefijo, tipo, duplicado, ownership confirm). 24 primitivas.
  - ◾ **1g.5+** — `create_section` (solo Rectangular probablemente), luego assign (batches +
    stop-on-first-failure), modify, delete. Evitar el delete-all-then-recreate peligroso de
    `RhinoSAP/SapFrameSynchronizer`.
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
