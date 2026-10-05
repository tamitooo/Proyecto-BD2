# Revisión a fondo de la Parte 1 y preparación de la Parte 2

> **Fecha de la revisión:** posterior a la presentación del Avance 1.
> **Alcance:** Parte 1 completa (2.1.1 a 2.1.6) más el material de clase de las
> semanas 1 a 7 (`C:\Users\illes\Documents\BD2`).
> **Objetivo:** que la Parte 1 quede a nivel "excelente" y sirva de base firme
> para la Parte 2.
>
> **Informes de detalle que acompañan a este documento** (en `docs/revision/`):
> [`indices.md`](revision/indices.md) (corrección de las estructuras de indexación,
> uso de índices en el planner y metodología de los experimentos),
> [`sql_dinamico.md`](revision/sql_dinamico.md) (superficie SQL, carga de CSV,
> transacciones y arquitectura de los dos ejecutores),
> [`frontend.md`](revision/frontend.md) (tema, paneles, flujos de CSV y DDL) y
> [`alineacion_clase.md`](revision/alineacion_clase.md) (comparación con la clase,
> semana por semana, con el plan de repaso para la defensa).

---

## 1. Resumen ejecutivo

La Parte 1 **funcionaba en su núcleo** (estructuras, algoritmos, benchmarks), pero
tenía exactamente los tres huecos que el profesor señaló en la demo, más varios
defectos que se habrían visto en la entrega. Todo lo crítico queda resuelto y
verificado en este documento.

### Lo que el profesor observó, y su estado

| Observación | Estado | Evidencia |
|---|---|---|
| "Que pueda recibir CSV" | ✅ **Ya funciona** (estaba resuelto antes de esta revisión) | 12/12 filas del CSV de prueba, incluida `"Pérez, Juan"` (coma dentro de comillas) y tildes. Ver §3 |
| "Que se pueda crear tablas, eliminar, etc." | ✅ **Funciona**, y se hizo más dinámico | `CREATE/DROP TABLE` ya existían; ahora también `CREATE/DROP INDEX` y `BEGIN/END TRANSACTION` desde SQL. Ver §4 |
| "Nos falta mejorar índices" | ✅ **Resuelto y ahora demostrable** | `CREATE INDEX` no existía: los índices estaban *hardcodeados* en el backend. Ahora el usuario crea el índice desde la GUI y **el plan cambia en vivo**, que es justo lo que permite mostrar la mejora |
| "El fondo debe ser blanco" | ✅ **Aplicado** | El CSS era un tema oscuro completo (`--bg: #0f172a`). Ahora `--bg`/`--surface: #ffffff` con `color-scheme: light` y contraste AA verificado |
| "Código que no podíamos explicar" | ✅ **Documentado** | Cada componente está contrastado con la clase (§6), con la frase de defensa de una línea. Sólo un tema queda genuinamente fuera: recuperación ante fallos |

### Números de la corrección

| Métrica | Antes | Después |
|---|---|---|
| Pruebas de la suite que fallan | **6** (3 por la métrica "fair" sin actualizar el test, 3 desactualizadas por el `UPDATE` nuevo) | **0** |
| Pruebas en la suite | 298 | **326** |
| `CREATE INDEX` / `DROP INDEX` | no existían | parser → catálogo → ejecutor → API → GUI |
| Transacciones en el motor | `BEGIN` devolvía *Unsupported SQL command* | `BEGIN`/`END`/`COMMIT`/`ROLLBACK` reales, con ROLLBACK de datos y de DDL |
| Consultas del script del profesor pegadas tal cual | fallaban (`Unsupported SQL command: --`) | funcionan las 6, con comentarios y `;` |
| Benchmarks: línea base sin índice | no existía (el enunciado la exige) | `linear_scan` medida; a 50 000 claves el hash es **17 208×** más rápido |

---

## 2. Cómo se verificó (no es análisis estático)

Todo lo que se afirma aquí se ejecutó sobre el motor real, en un directorio de datos
temporal para no tocar la demo del equipo:

1. **El script del profesor, literal**: se leyó `queries-proy (1).sql` desde el
   archivo adjunto y se ejecutaron sus 6 sentencias **incluyendo sus comentarios
   `--`**, sobre el CSV real de 12 filas.
2. **Reproducción del flujo completo**: `CREATE TABLE` → carga del CSV → las 5
   consultas → `EXPLAIN` → `EXPLAIN ANALYZE`, con la salida real transcrita en §3.
3. **Suite completa**: 326 pruebas, 0 fallos.
4. **Benchmark regenerado**: `python -m benchmarks.benchmark_indexes --sizes 1000
   10000 50000`, con las gráficas y las tablas de `docs/` regeneradas desde el JSON.
5. **API por HTTP**: `GET /api/health`, `/api/tables`, `/api/query` (con `BEGIN` y
   `ROLLBACK`) probados con `TestClient`.
6. **Revisión cruzada del código** contra las fuentes de clase extraídas en
   `C:\Users\illes\Documents\BD2\01_fuentes_limpias` y `_extract\pdf`.

> **Nota sobre el entorno:** en esta máquina el sandbox niega escribir dentro de
> directorios creados por `tempfile.mkdtemp()` (permisos 0o700). Eso hace que ~18
> pruebas que usan `tmp_path` de pytest fallen con `WinError 5`, y **no es un
> defecto del proyecto**: con un parche temporal de `tempfile` la suite pasa
> completa. Si en sus máquinas ven ese error, es lo mismo: ejecuten con
> `$env:TEMP` apuntando a una carpeta normal con permisos de escritura.

---

## 3. El flujo del profesor, verificado

```
PASO 1 · el script del profesor tal cual, incluidos sus comentarios
  1. CREATE TABLE ok=True
  2. SELECT     ok=True   filas=1
  3. SELECT     ok=True   filas=6
  4. SELECT     ok=True   filas=0
  5. EXPLAIN    ok=True   filas=1
  6. EXPLAIN    ok=True   filas=1

PASO 2 · cargar el CSV del profesor
  filas leídas=12 insertadas=12 rechazadas=0
  'Pérez, Juan' -> [{'id': 3, 'nombre': 'Pérez, Juan', 'carrera_id': 1, 'nota': 14}]

PASO 3 · las 5 consultas, con su plan y su traza real
  WHERE nombre = 'Pérez, Juan'          filas=1  ruta=HEAP_SCAN
      traza: HEAP_SCAN(12) → FILTER(12->1)
  WHERE nota >= 14 ORDER BY id          filas=6  ruta=HEAP_SCAN
      traza: HEAP_SCAN(12) → FILTER(12->6) → EXTERNAL_SORT(6->6)
  WHERE id = 999                        filas=0  ruta=HASH_INDEX_LOOKUP (idx_alumnos_id_hash)
  EXPLAIN ...                           filas=1
  EXPLAIN ANALYZE ...                   filas=1
      traza: HEAP_SCAN(12) → FILTER(12->6) → EXTERNAL_SORT(6->6)
```

Puntos importantes que conviene decir en voz alta durante la demo:

- **El plan es honesto.** En la consulta por `nota` no existe índice sobre `nota`, así
  que el plan dice `HEAP_SCAN` + `EXTERNAL_SORT` y `used_indexes: []`. No hay ningún
  caso en el que el plan *afirme* usar un índice y por dentro haga un escaneo (eso
  sería lo peor que podría encontrar el profesor).
- **La consulta `id = 999` sí usa el índice** (`HASH_INDEX_LOOKUP` sobre
  `idx_alumnos_id_hash`): es la mejor respuesta a "¿y los índices?" antes de crear
  uno nuevo.
- **La consulta 3 devuelve 0 filas y eso es correcto**; ahora el panel de resultados
  dice "La consulta no devolvió registros" en lugar de "La mutación se aplicó
  correctamente" (que era un defecto real: se decidía por `columns.length > 0`, y una
  lectura sin filas no devuelve columnas).

---

## 4. Lo que se implementó en esta revisión

### 4.1 `CREATE INDEX` / `DROP INDEX` (el punto "mejorar índices")

No existían en ninguna parte del repositorio. Los índices se registraban a mano en
`backend/engine.py`, así que **era imposible demostrar la mejora de un índice en
vivo**: ante `WHERE nota >= 14` el plan siempre era `HEAP_SCAN`.

Ahora:

```sql
CREATE [UNIQUE] INDEX [nombre] ON tabla (columna)
    [USING HASH | BPLUS_CLUSTERED | BPLUS_UNCLUSTERED]
DROP INDEX [IF EXISTS] nombre [ON tabla]
```

- El índice se **construye y se puebla recorriendo la tabla**, así que funciona sobre
  datos ya cargados (el caso de la demo: cargar el CSV y después indexar).
- **Sobrevive al reinicio**: queda en el manifiesto del catálogo y se reconstruye al
  abrirlo.
- `USING` permite elegir la técnica, y `UNIQUE` sólo se admite con Hash (es el único
  que lo implementa en el motor), con un error claro si no.
- **El índice de la `PRIMARY KEY` no se puede eliminar**: es lo que hace cumplir la
  unicidad. Antes se podía borrar y quedaban claves primarias duplicadas.
- La GUI tiene un formulario (columna + técnica + único) y un botón de eliminar por
  índice, con el resultado o el error visible.

**El guion de demo que esto habilita** (30 segundos, y es la respuesta directa a la
observación del profesor):

```
EXPLAIN SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id;
   → HEAP_SCAN   (no hay índice sobre nota)

CREATE INDEX idx_alumnos_nota ON alumnos (nota);

EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id;
   → BPLUS_UNCLUSTERED_RANGE_SCAN usando idx_alumnos_nota
   → traza real: BPLUS_UNCLUSTERED_RANGE_SCAN(6) → FILTER(6) → EXTERNAL_SORT(6)

DROP INDEX idx_alumnos_nota;
EXPLAIN SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id;
   → HEAP_SCAN   (vuelve atrás)
```

### 4.2 Transacciones dentro del motor

`BEGIN TRANSACTION`, `END TRANSACTION`, `COMMIT` y `ROLLBACK` existían **sólo** en
`transactions/transaction_manager.py`, que opera sobre un `dict` en memoria y no pasa
por el motor. En el panel de consultas (y en el API) `BEGIN` devolvía
`Unsupported SQL command: BEGIN`.

Ahora los ejecuta el **mismo `QueryExecutor`** que atiende la GUI y el API:

- En la primera escritura sobre una tabla se guarda su estado previo y se toma el
  **bloqueo exclusivo** de esa tabla (2PL estricto: se libera en COMMIT/ROLLBACK).
- `ROLLBACK` restaura los registros, **reconstruye los índices** y además deshace el
  DDL de la transacción (`CREATE TABLE`, `CREATE INDEX` y hasta un `DROP TABLE`, que
  se restaura con sus filas).
- `END TRANSACTION` = `COMMIT`: confirma y libera.
- `GET /api/health` informa si hay una transacción abierta, con su id, sentencias y
  tablas bloqueadas.
- Sigue existiendo **una sola transacción activa por proceso** (un segundo `BEGIN`
  da un error claro). Para la **demo obligatoria de concurrencia con hilos** se
  mantiene `transactions/demo_concurrencia.py`, que es la que muestra la *race
  condition* y cómo el LockManager la resuelve. **Digan esto explícitamente**: son
  dos cosas distintas y el enunciado 2.1.4 pide ambas (transacciones + simulación con
  hilos).

### 4.3 Mejoras del planner (los "índices" que faltaban usar)

Tres casos donde existía un índice pero el planner no lo aprovechaba:

| Consulta | Antes | Ahora |
|---|---|---|
| `WHERE nota >= 14 AND nota <= 19` (con B+ sobre `nota`) | indexaba un extremo y filtraba el resto (`RANGE_SCAN` + `FILTER`) | usa **los dos extremos en un solo `range_search`** |
| `WHERE id = 1 OR id = 5` | escaneo completo (cualquier `OR` desactivaba los índices) | **`HASH_INDEX_UNION`**: una búsqueda por índice por cada grupo |
| `WHERE nota = 14 OR nota = 20` | escaneo completo | **`BPLUS_INDEX_UNION`** |

El caso del `OR` merece un comentario: **no se puede** usar un solo predicado como
camino de acceso cuando hay un `OR` (se perderían filas que cumplen el otro grupo),
así que la unión se aplica sólo cuando **todos** los grupos son de igualdad sobre la
**misma** columna indexada; si no, cae a escaneo y filtro. Esto se verificó con
`WHERE id = 1 OR nota = 20`, que devuelve correctamente las dos filas.

### 4.4 Otras correcciones
| Defecto | Consecuencia | Corrección |
|---|---|---|
| No se podía pegar el script del profesor | `Unsupported SQL command: --` por los comentarios; un BOM daba `Unsupported SQL command: SELECT` | se quitaron comentarios `--` y `/* */` (respetando literales), BOM y se toma la primera sentencia de un script con `;` |
| Columnas sensibles a mayúsculas | `SELECT ID FROM ALUMNOS` fallaba aunque `FROM ALUMNOS` funcionaba | resolución de columnas insensible a mayúsculas en SELECT/WHERE/ORDER BY/GROUP BY/UPDATE/DELETE, manteniendo el nombre real del esquema |
| `COUNT(*)` sin `GROUP BY` | error "requiere GROUP BY", aunque el ejecutor viejo sí lo hacía | `SELECT COUNT(*)/SUM/AVG/MIN/MAX FROM t` funciona (un solo grupo) |
| El API no arrancaba tras `DROP TABLE users` | `RuntimeError: seed falló … Clave primaria duplicada: 10`; uvicorn moría | el *seed* revisa **tabla por tabla** y siembra sólo las vacías |
| Importar CSV reportaba éxito sin importar nada | una ruta inexistente daba `rows_read: 0` y `success: true` | error explícito (`CsvImportError`), también para un CSV sin filas |
| Encabezado de CSV distinto = corrupción silenciosa | con `NOTA,NOMBRE,ID,CARRERA` mapeaba por posición y guardaba `id=15, nota=2` | si el encabezado no cubre las columnas de la tabla, **falla** con el listado de columnas esperadas (se puede forzar por posición con `has_header=False`) |
| El plan decía "escaneo secuencial" en un `INSERT`/DDL | `steps: []` y el panel afirmaba algo falso | el panel distingue "sin pasos" y el mensaje es correcto |
| Tras `CREATE TABLE` no se seleccionaba la tabla nueva | el siguiente CSV podía irse a `users` | `App.tsx` recarga y selecciona la tabla creada |
| `_num_paginas()` con división entera | una página parcial quedaba **invisible** al escaneo (bug latente de `HeapFile`) | redondeo hacia arriba + `replace_all` rellena la última página |
| Reconstruir todos los índices en cada `INSERT` secuencial | O(n²) al cargar un CSV | sólo se reconstruyen si hubo reorganización |
| El README afirmaba "detección de conflictos" | el LockManager no tiene grafo de espera, sólo *timeout* de 2 s | README corregido |
| Dos ejecutores con semántica distinta | el viejo ignora `LIMIT`, devuelve 0 filas con `OR`, lanza `TypeError` con DDL | aviso de **LEGADO** bien visible en `query/executor.py` con la lista de diferencias |

### 4.5 El flujo dinámico completo, verificado con datos inventados

La pregunta que importa es: *"¿y si el profesor me da otro CSV, o quiere una tabla que
se llame `animales`?"*. Se probó **con una tabla y un CSV inventados**, por HTTP (el mismo
camino que usa el navegador), y esto es lo que pasó:

```sql
-- 1. El usuario crea la tabla que quiera, con las columnas que quiera
CREATE TABLE animales (
    id INT PRIMARY KEY, nombre VARCHAR(40), especie VARCHAR(30),
    edad INT, peso FLOAT
);

-- 2. Carga su propio CSV (admite comillas, comas dentro del campo y tildes)
--    id,nombre,especie,edad,peso
--    1,Firulais,Perro,5,12.5
--    2,"Michi, el gato",Gato,3,4.2
--    3,Nemo,Pez,1,0.3
--    → insertadas=3 rechazadas=0

SELECT * FROM animales WHERE peso >= 4 ORDER BY peso;   -- funciona
CREATE INDEX idx_animales_peso ON animales (peso);      -- HEAP_SCAN → BPLUS_CLUSTERED_RANGE_SCAN
```

Y el resto de combinaciones que se verificaron:

| Caso | Resultado |
|---|---|
| Tabla con **columnas inventadas** y tipos a elección | ✅ |
| CSV **con las columnas en otro orden** | ✅ mapea **por nombre de encabezado** |
| CSV con **`;`** (Excel en español) | ✅ desde la GUI ahora se elige el separador |
| CSV **sin cabecera** | ✅ con la casilla "la primera fila es el encabezado" desmarcada (importa por posición) |
| Cabecera que **no coincide** con la tabla | ✅ **falla con mensaje claro** (antes corrompía en silencio) |
| CSV con **ruta inexistente** o **vacío** | ✅ **error explícito** (antes decía "éxito, 0 filas") |
| `CREATE INDEX` sobre la tabla nueva | ✅ y el plan cambia |
| Tablas e índices tras **reiniciar** el API | ✅ persisten (se reconstruyen desde el catálogo) |
| `SELECT COUNT(*)`, `WHERE ... OR ...`, mayúsculas en columnas | ✅ |

**Único paso manual del flujo:** la tabla se declara **antes** con `CREATE TABLE` (nombre,
columnas y tipos). El motor **no infiere el esquema** desde el CSV. Es una decisión de
alcance coherente con el enunciado (que pide un parser SQL con `CREATE TABLE`), y es la
razón de que exista la validación de encabezado: avisa en vez de adivinar.

---

## 5. Hallazgos que quedan abiertos (y cómo responderlos)

Estos **no** se tocaron porque son decisiones de alcance, no defectos. Conviene
tenerlos presentes para la defensa y para planificar la Parte 2.

### 5.1 Recuperación ante fallos: el tema de la semana 5 no está implementado

No hay WAL, ni `log_manager.py`, ni checkpoints: `commit()` no fuerza nada a disco.
**La Parte 1 no lo exige** (2.1.4 sólo pide `BEGIN/END TRANSACTION`, un mecanismo de
bloqueo y la simulación con hilos, y las tres cosas están), pero **sí es contenido de
clase** (segunda mitad de la semana 5 y el laboratorio 05).

**Frase de defensa:** *"El enunciado de la Parte 1 pide transacciones y control de
concurrencia, y eso está implementado y demostrado con hilos. La recuperación (WAL,
UNDO/REDO, checkpoints) es el tema de la semana 5; lo tenemos identificado como
extensión: implicaría escribir un log antes de cada modificación y reproducirlo al
arrancar, sobre el mismo `LOCK` conocido."*

Si quieren cerrarlo, el añadido mínimo defendible es un WAL de ~120 líneas
(`log_manager.py` con `append(record)` + `fsync`, y reproducción al abrir).

### 5.2 Los índices son 100 % en memoria

Los tres índices viven en memoria; el catálogo persiste **metadatos** y los
**reconstruye** al abrir. El laboratorio 03 pide buckets paginados en disco.
**Frase de defensa:** *"La estructura y los algoritmos son los de clase; la
persistencia se resolvió reconstruyendo desde el almacenamiento, que es una decisión
explícita y documentada, no un olvido. Paginar los buckets es el siguiente paso
natural."*

### 5.3 Otros (menores)

| Tema | Detalle | Prioridad |
|---|---|---|
| Bitmap Index Scan | no existe, y el planner **rechaza** el tipo "bitmap" a propósito (`IndexMetadata` valida los tres tipos soportados). Es el laboratorio 04 | Media si preguntan por ese lab |
| `HeapFile` sin `FILE_HEADER`/`PAGE_HEADER` | la lista de páginas libres vive en un archivo `.free` aparte. **Se puede defender**: es el mismo patrón del código de clase `Variable1.py` (archivo de índice aparte con posiciones) | Baja |
| `_try_merge` del hash extendible | fusiona buckets al borrar; el hashing extendible de libro no lo hace. Es una mejora, no un error, pero **es la línea que un profesor podría pedir explicar** | Baja (saber justificarla) |
| Sin subida *multipart* de CSV | la GUI lee el archivo en el navegador y manda el texto; funciona, pero no hay endpoint de subida real | Baja |
| `delimiter` fijo en `,` en la GUI | un CSV de Excel en español (`;`) daría 0 filas rechazadas con error visible | Baja |
| `ORDER BY ... DESC` no usa el índice | el B+ sólo expone recorrido ascendente, así que va a External Sort. **Se puede defender**: es correcto, sólo no está optimizado | Baja |
| `LIMIT` no se empuja al índice | se aplica después del sort | Baja |
| `DELETE`/`UPDATE` no usan índice | siempre escanean; correcto pero mejorable | Baja |

---

## 6. Alineación con la clase (semanas 1 a 7)

La comparación completa, componente por componente con citas de las fuentes de clase,
está en [`docs/revision/alineacion_clase.md`](revision/alineacion_clase.md) (1 026
líneas, con la tabla de 47 componentes y un plan de repaso con 20 preguntas). Resumen:

| Semana / tema | Veredicto | Lo que hay que poder decir |
|---|---|---|
| 1 · Arquitectura de SGBD | Alineado | Capas separadas (parser → planner → ejecutor → storage), como el modelo de arquitectura visto en clase |
| 2 · Registros y paginación | Alineado con matices | `record.py` usa el patrón literal del ejemplo de clase (`struct` + `RECORD_SIZE` + `seek(pos × tamaño)`). El `.free` es el patrón de `Variable1.py` |
| 2 · Heap File | Alineado | RID = (página, slot), reutilización de espacio libre por lista de páginas |
| 2 · Archivo Secuencial | Alineado | Estrategia de *overflow file* (`.main` + `.aux`), búsqueda binaria, umbral de reorganización al 30 % (el del enunciado) |
| 3 · B+ Tree | **Muy alineado** | Mínimo ⌈FB/2⌉, split en cascada, **fusión y redistribución con hermano**, hojas enlazadas y búsqueda por rango sin descender; el agrupado guarda el registro completo (como InnoDB) y el no agrupado (clave, RID) |
| 3 · Hash Extendible | **Alineado bit a bit** | Usa los **D bits bajos** (`hash & ((1<<D)-1)`), que es `Bin(Key % 2^D)` del laboratorio; D=1 y 2 buckets iniciales iguales |
| 4 · External Sort | Alineado | Two-Phase Multiway Merge Sort con min-heap y `fan_in = B-1` buffers |
| 4 · External Hashing | Alineado | Grace Hashing en dos fases para `GROUP BY`, `JOIN` y `DISTINCT` |
| 4 · Bitmap Index Scan | **Falta** | No implementado; ver §5.3 |
| 5 · Concurrencia | Alineado | Locks PS/PX con los nombres de clase, liberación sólo en COMMIT/ROLLBACK (2PL estricto) y la demo de actualización perdida (X = 100, −10, +100) |
| 5 · Recuperación | **Falta** | No es requisito de la Parte 1; ver §5.1 con la frase de defensa |
| 6 y 7 · Espacial y textual | Fuera de alcance | Son las Partes 2 y 3 (semanas 8 y 12) |

**Conclusión de la alineación:** de 47 componentes revisados, la gran mayoría está
alineada o alineada con simplificaciones defendibles. Lo único que un profesor puede
señalar como "no me lo enseñé así" son: la falta de **recuperación** (§5.1), la falta
de **bitmap index scan** (§5.3), la persistencia de índices en memoria (§5.2) y el
`_try_merge` del hash. Las cuatro tienen respuesta preparada arriba.

---

## 7. Estado de la suite y de los experimentos

### Suite

**326 pruebas, 0 fallos.** Las 6 que fallaban eran tests desactualizados, no defectos
del motor:
- 3 de `tests/test_benchmark_indexes.py`: exigían 8 métricas por índice cuando el
  benchmark pasó a medir 10 (se añadieron la versión "justa" del rango y el índice
  aislado). Se actualizaron las expectativas y se añadió una prueba que **exige** la
  nueva línea base.
- 2 de `tests/test_end_to_end.py` y 1 de `tests/test_sql_parser.py`: daban por hecho
  que `UPDATE` era sintaxis inválida. Se cambiaron por sentencias realmente fuera del
  subconjunto (`TRUNCATE TABLE`, `SELECT * FROM`).

Se añadió `tests/test_dinamica_parte1.py` (**27 pruebas**) que cubren precisamente lo
nuevo y lo que el profesor pidió: que `CREATE INDEX` **cambie el plan**, que la
igualdad y el rango sigan correctos después de indexar, los errores previsibles del
DDL de índices, el ROLLBACK de INSERT/UPDATE/DELETE/DDL, la coherencia de los índices
tras un rollback, el rango con dos extremos, la unión de índices en `OR` y la línea
base del benchmark.

### Experimentos

Se regeneró el benchmark de índices con la **línea base sin índice** que exige el
enunciado, y se regeneraron las gráficas y las tablas de
[`docs/conclusiones_experimentales.md`](conclusiones_experimentales.md) **desde el
JSON**, así que ya no hay números que no cuadren.

Resultado destacado (N = 50 000, igualdad exacta):

| Estructura | Tiempo | Mejora frente a la búsqueda lineal |
|---|---|---|
| Búsqueda lineal (sin índice) | 24 698.64 µs | 1× |
| B+ agrupado | 9.14 µs | 2 703× |
| B+ no agrupado | 3.48 µs | 7 100× |
| Hash extendible | **1.44 µs** | **17 208×** |

Y una corrección metodológica importante: el espacio del B+ agrupado se reportaba con
*pickle*, que lo inflaba ~3.5×. Ahora se declara que **85 % de sus bytes son los
registros completos** que guarda en las hojas (`payload_bytes`), que es el costo real
del *index clustering* y la contrapartida de no tener que ir al Heap File.

---

## 8. ¿Está la Parte 1 lista para empezar la Parte 2?

**Sí, con tres condiciones.**

**Lo que ya está firme:**
- Los tres bloques que el profesor observó están resueltos y **demostrables en vivo**.
- 326 pruebas en verde, incluida la reproducción del script de la cátedra.
- El contrato de respuesta del API (`QueryResult`) es estable y el frontend no conoce
  RIDs ni páginas: **es la base correcta para añadir tipos espaciales y textuales**.
- El parser es extensible por despacho de primera palabra (`if first_word == ...`),
  así que `SELECT ... WHERE distancia(...)` o `MATCH(...)` se añaden sin reescribirlo.
- El planner es basado en reglas con `reason`/`details` por paso: añadir un R-Tree o un
  índice invertido es registrar un `IndexMetadata` nuevo y un camino de acceso.
**Las tres condiciones antes de la Parte 2:**

1. **Entregable pendiente: el informe incremental.** El enunciado lo pide
   explícitamente (sección 3: "Informe incremental: diseño arquitectónico, dominio de
   datos, explicación de algoritmos") y **`docs/informe_incremental.md` está vacío
   (0 bytes)**. Es, hoy, el único entregable de la Parte 1 que falta por completo. El
   material para escribirlo ya existe: `docs/revision/alineacion_clase.md` tiene el
   diseño y la explicación de algoritmos componente por componente con citas de clase,
   `docs/revision_parte1.md` tiene la verificación y los hallazgos, y
   `docs/conclusiones_experimentales.md` cubre la parte experimental. Es cuestión de
   ensamblarlo, no de investigar de nuevo.
2. **Migrar el material viejo al ejecutor vigente.** `examples/demo_parte1.py`,
   `tests/test_end_to_end.py` y `tests/test_storage_integration.py` usan
   `query/executor.py` (el legado). Ya tiene aviso, pero **mientras existan dos
   ejecutores, cualquier extensión hay que hacerla dos veces** y la Parte 2 va a
   añadir tipos de índice nuevos. Consolidar en `query/query_executor.py` es la
   primera tarea de la Parte 2.
3. **Decidir la persistencia de índices.** El R-Tree y el índice invertido de las
   Partes 2 y 3 van a crecer bastante; hoy los índices se reconstruyen al abrir. Si no
   se pagina, conviene al menos escribirlo como decisión en el README (hoy está
   explicado en §5.2 pero no en el README).

Además, el `Catalog.create_index` y el despacho por `operator` del ejecutor ya son los
puntos de extensión: un `kind="rtree"` y un camino de acceso `RTREE_RANGE_SCAN`
encajan sin tocar el ejecutor.

---

## 9. Guion de demo de 5 minutos (Parte 1)

| Min | Qué hacer | Qué debe verse en pantalla |
|---|---|---|
| 0:00 | Arrancar backend (`python -m uvicorn backend.api:app --port 8000`) y frontend (`npm run dev`), abrir `http://localhost:5173` | Tema **blanco**, 4 paneles, panel de archivos con `users`, `employees`, `departments` y sus índices |
| 0:30 | Pegar el **script del profesor completo** (con sus comentarios) y ejecutarlo sentencia por sentencia | `CREATE TABLE` y las consultas responden; en `id = 999` el panel dice "no devolvió registros" |
| 1:30 | Panel de archivos → seleccionar `alumnos` → **Cargar CSV** → elegir `alumnos_prueba_bd2.csv` | "12 filas insertadas en alumnos, 0 rechazadas" |
| 2:00 | `SELECT * FROM alumnos WHERE nombre = 'Pérez, Juan'` | La fila con la coma; el panel de plan muestra `HEAP_SCAN` + `FILTER` |
| 2:30 | `EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id` | Plan lógico + **traza real con tiempos** (`HEAP_SCAN 12 → FILTER 12→6 → EXTERNAL_SORT 6→6`) |
| 3:00 | Panel de archivos → **Crear índice** sobre `nota` (B+ no agrupado) | Aparece `idx_alumnos_nota` en la lista de índices |
| 3:30 | Repetir el `EXPLAIN ANALYZE` | **El plan cambió**: `BPLUS_UNCLUSTERED_RANGE_SCAN` usando `idx_alumnos_nota`. *Este es el momento que responde a "mejorar índices"* |
| 4:00 | `SELECT * FROM alumnos WHERE nota = 14 OR nota = 20` | `BPLUS_INDEX_UNION`: dos búsquedas unidas por índice |
| 4:20 | `BEGIN TRANSACTION` → `DELETE FROM alumnos WHERE nota < 14` → `SELECT` (se ven menos filas) → `ROLLBACK` → `SELECT` | Las filas vuelven; el panel de plan muestra `ROLLBACK` con las tablas restauradas |
| 4:45 | `python -m transactions.demo_concurrencia` (o el archivo) | Varias transacciones con hilos, la *race condition* y cómo los locks la evitan |
| 5:00 | Cerrar con la gráfica `benchmark_results/plots/index_dashboard.png` | Hash 17 208× más rápido que la búsqueda lineal a 50 000 claves |

---

## 10. Archivos tocados en esta revisión

**Motor y SQL**
- `query/sql_parser.py` — `CREATE/DROP INDEX`, `BEGIN/END/COMMIT/ROLLBACK`, limpieza de comentarios y BOM, división de scripts por `;`
- `query/catalog.py` — `create_index`/`drop_index`, nombre automático por técnica, protección del índice de la PK
- `query/query_executor.py` — ejecución de índices y transacciones, unión de índices, agregados sin `GROUP BY`, columnas insensibles a mayúsculas, reconstrucción de índices sólo si hubo reorganización
- `query/query_planner.py` — rango con los dos extremos, unión de índices para `OR`, corrección del candidato por `ORDER BY`
- `query/csv_loader.py` — errores explícitos, validación de encabezado
- `query/executor.py` — aviso de legado con las diferencias de comportamiento
- `storage/heap_file.py` — `page_bytes`, `_num_paginas` con redondeo, `replace_all` con relleno
- `storage/sequential_file.py` — `replace_all` para el rollback
- `backend/engine.py` — *seed* por tabla, `transaction_state()`
- `backend/api.py` — documentación de sentencias, `transaction` en `/api/health`
- `tools/import_csv.py` — `allow_path=True`

**Experimentos**
- `benchmarks/benchmark_indexes.py` — línea base `linear_scan`, `payload_bytes`, resumen con el desglose
- `benchmark_results/` — JSON, CSV y las 13 gráficas regeneradas
- `docs/conclusiones_experimentales.md` — tablas y conclusiones alineadas con el JSON

**Interfaz**
- `frontend/src/styles.css`, `index.html` — tema claro con `color-scheme: light`
- `frontend/src/panels/FilesPanel.tsx` — formulario de creación de índice y borrado
- `frontend/src/panels/QueryPanel.tsx` — ejemplos de índices y transacciones
- `frontend/src/panels/ResultsPanel.tsx` — mensaje correcto para lecturas sin filas
- `frontend/src/panels/PlanPanel.tsx` — sin afirmaciones falsas cuando no hay pasos
- `frontend/src/App.tsx` — selección automática de la tabla creada

**Pruebas y documentación**
- `tests/test_dinamica_parte1.py` — **nuevo**, 27 pruebas
- `tests/test_benchmark_indexes.py`, `tests/test_sql_parser.py`, `tests/test_end_to_end.py` — expectativas actualizadas
- `README.md` — subconjunto SQL, transacciones, paneles, números de los experimentos, recuento de la suite
- `docs/revision_parte1.md` — **nuevo**, este documento
- `docs/revision/indices.md`, `frontend.md`, `sql_dinamico.md`, `alineacion_clase.md` — **nuevos**, los cuatro informes de detalle
- `.gitignore` — añadidas las carpetas temporales de pytest

---

## 11. Qué hacer a continuación, en orden

1. **Escribir el informe incremental** (§8, condición 1). Es el único entregable de la
   Parte 1 que falta y hay bastante material ya redactado en `docs/revision/`.
2. **Revisar y hacer commit.** Hay 33 archivos modificados y 2 nuevos sin confirmar.
   Sugerencia de commits atómicos, que además se ven bien en la historia del repo:
   - `feat(query): CREATE/DROP INDEX y planificador con unión de índices`
   - `feat(transactions): BEGIN/END/COMMIT/ROLLBACK en el motor SQL`
   - `fix(storage): página parcial invisible en HeapFile`
   - `fix(csv): errores explícitos y validación de encabezado`
   - `feat(ui): tema claro y gestión de índices`
   - `fix(benchmark): línea base sin índice y espacio declarado`
   - `test: cobertura de la dinámica de la Parte 1 y expectativas actualizadas`
   - `docs: revisión de la Parte 1 y guion de demo`
3. **Probar la demo completa una vez** siguiendo el guion de §9, en las máquinas del
   equipo, y **grabar el video demo** (5–10 min, que también es entregable).
4. **Decidir y documentar la persistencia de índices** (§8, condición 3) y **migrar el
   material legado** (§8, condición 2) al arrancar la Parte 2.
