# Reasoning Framework

Este documento define una capa de disciplina para el razonamiento del sistema, sin cambiar la arquitectura ni la logica de los MCPs existentes.

## 1) Niveles de razonamiento

### Observation
- Describe lo observado directamente en datos de entrada o salidas geometricas.
- No interpreta funcion ni dominio.
- Debe usar lenguaje de deteccion directa.

### Evidence
- Formaliza soporte trazable usando `evidence_items`, `relations`, `metadata` y referencias observacionales.
- Debe indicar de donde proviene el soporte.
- Mantiene caracter observacional y limitaciones.

### Inference
- Propone interpretaciones tentativas derivadas de evidencia.
- Debe explicitar incertidumbre.
- Nunca equivale a verdad confirmada.

### Conclusion
- Afirmacion cerrada permitida solo con confirmacion geometrica.
- Requiere `assertion_level = confirmed` y estado de verificacion acorde.
- Debe citar metodo de confirmacion.

## 2) Reglas de uso

1. Toda afirmacion debe indicar explicitamente su nivel: `Observation`, `Evidence`, `Inference` o `Conclusion`.
2. Toda `Inference` debe:
   - referenciar evidencia concreta (por ejemplo `ev-rel-*`, `ev-geom-*`, `ev-ent-*`);
   - incluir incertidumbre explicita (por ejemplo "podria", "consistente con").
3. `Conclusion` solo se permite cuando:
   - la relacion o interaccion usada como base tiene `assertion_level = confirmed`;
   - existe verificacion explicita (por ejemplo `verification_status = verified` o equivalente confirmado por metodo).
4. Si la evidencia es candidata o parcialmente verificada, la salida debe permanecer en `Inference`, no escalar a `Conclusion`.
5. Toda afirmacion debe preservar trazabilidad y limitaciones observacionales.

## 3) Prohibiciones

Sin evidencia confirmada, no afirmar en forma concluyente:
- "es un frame"
- "es estructural"
- "es un stud"
- "es un track"

Estas afirmaciones solo podrian aparecer como `Conclusion` si hay soporte confirmado y verificable.

## 4) Lenguaje permitido por nivel

### Observation
- "se observa"
- "se detecta"

### Evidence
- "basado en"
- "segun metadata"

### Inference
- "consistente con"
- "podria indicar"

### Conclusion
- "confirmado mediante"

## 5) Ejemplos correctos vs incorrectos

### Observation (3)
- Correcto: "Observation: se observa una relacion `intersects` candidata entre `obj-a` y `obj-b`."
- Incorrecto: "Observation: los objetos estan confirmadamente conectados."

- Correcto: "Observation: se detecta `bbox_overlap` en la relacion `rel-001`."
- Incorrecto: "Observation: esto demuestra una union real."

- Correcto: "Observation: se observa metadata compartida entre dos objetos."
- Incorrecto: "Observation: pertenecen a un mismo sistema funcional."

### Evidence (3)
- Correcto: "Evidence: basado en `ev-rel-rel-001`, la interaccion esta marcada como `candidate`."
- Incorrecto: "Evidence: esta claro que hay contacto real."

- Correcto: "Evidence: segun metadata (`ev-rel-rel-010`), existe una relacion declarativa observacional."
- Incorrecto: "Evidence: la metadata confirma funcion geometrica."

- Correcto: "Evidence: basado en `ev-geom-obj-1` y `ev-rel-rel-022`, hay soporte para proximidad."
- Incorrecto: "Evidence: por lo tanto ya esta verificado."

### Inference (3)
- Correcto: "Inference: consistente con `ev-rel-rel-022`, podria indicar interaccion espacial pendiente de verificacion."
- Incorrecto: "Inference: definitivamente hay contacto real."

- Correcto: "Inference: basado en `ev-rel-rel-030` (candidate), podria indicar cercania con incertidumbre."
- Incorrecto: "Inference: es estructural."

- Correcto: "Inference: consistente con evidencia relacional candidata y limitaciones bbox-based."
- Incorrecto: "Inference: queda confirmado el comportamiento."

### Conclusion (3)
- Correcto: "Conclusion: confirmado mediante verificacion geometrica (`assertion_level=confirmed`) para `rel-101`."
- Incorrecto: "Conclusion: confirmado con base en bbox overlap candidato."

- Correcto: "Conclusion: confirmado mediante chequeo de interseccion verificado."
- Incorrecto: "Conclusion: confirmado porque la metadata coincide."

- Correcto: "Conclusion: confirmado mediante evidencia con estado `verified` y trazabilidad completa."
- Incorrecto: "Conclusion: confirmado sin evidencia referenciada."

## 6) Tests conceptuales

- Inference sin evidencia -> invalida.
- Conclusion sin `assertion_level = confirmed` -> invalida.
- Inference con evidencia trazable y lenguaje de incertidumbre -> valida.

