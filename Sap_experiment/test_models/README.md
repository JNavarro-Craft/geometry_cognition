# test_models

Modelos SAP2000 para validación manual. **No se versionan** (regla preexistente del
`.gitignore` raíz, línea `test_models/`): los `.sdb` viven solo en tu disco.

La validación de esta sesión usó `TEST_01.sdb` (no incluido): un modelo de cercha/marco
real con 112 joints, 180 frames y 6 secciones `MGP10_*` Rectangular. Cualquier modelo
con joints + frames + secciones asignadas sirve para reproducir; abrir en SAP2000 y
seguir [`../tests/README.md`](../tests/README.md).
