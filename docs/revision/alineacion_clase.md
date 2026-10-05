# Alineación Clase ↔ Proyecto — Informe de defensa oral (Parte 1)

**Proyecto:** `C:\Users\illes\Documents\Proyecto-BD2` — *Minigestor de Base de Datos Multimodal*
**Material de clase:** `C:\Users\illes\Documents\BD2` (PDFs semanas 01–07 + código de ejemplo semana 02)
**Objetivo:** que el equipo pueda (a) confirmar lo que **sí** está alineado, (b) corregir o justificar lo que **no**, y (c) explicar cada línea en la defensa oral.

---

## 0. Método, fuentes y limitaciones (leer antes de usar este informe)

**Cómo se obtuvo la evidencia de clase.** No fue necesario extraer PDFs: el repositorio de materiales ya contenía texto pre-extraído en `C:\Users\illes\Documents\BD2\01_fuentes_limpias\*.txt` (y una copia en `02_conocimiento\`, `04_conocimiento_optimo\` y `_extract\pdf\`). **Todas las citas de clase de este informe provienen de esos `.txt`**, que son el texto extraído de los PDFs indicados. Cada cita va como `archivo:línea` del `.txt` correspondiente y se nombra el PDF de origen.

| Semana | PDF de origen | Texto pre-extraído citado |
|---|---|---|
| 01 | `week_01\01 Arquitectura de SGDB (1).pdf` | `01_fuentes_limpias\semana01_teoria_arquitectura_SGBD.txt` |
| 01 | `week_01\Laboratorio 01 - Repaso PostgreSQL (1).pdf` | `01_fuentes_limpias\semana01_lab_postgresql.txt` |
| 02 | `week_02\02 Registros, Paginación y Organización de Archivos.pdf` | `01_fuentes_limpias\semana02_teoria_registros_paginacion_archivos.txt` |
| 02 | `week_02\Laboratorio 02 - HeapFiles (2).pdf` | `01_fuentes_limpias\semana02_lab_heapfiles.txt` |
| 02 | `week_02\Fijo1.py/.cpp`, `Fijo2.py/.cpp`, `Variable1.py/.cpp` | leídos íntegramente (código de ejemplo) |
| 03 | `week_03\03 Indexación Hash y Árboles B+ (1).pdf` | `01_fuentes_limpias\semana03_teoria_hash_btree.txt` |
| 03 | `week_03\Laboratorio 03 - HashFile y BTree (2).pdf` | `01_fuentes_limpias\semana03_lab_hashfile_btree.txt` |
| 04 | `week_04\04 Bitmap Index Scan - External Algorithm.pdf` | `01_fuentes_limpias\semana04_teoria_bitmap_external.txt` |
| 04 | `week_04\laboratorio 05 - External Algorithm - Bitmap (1).pdf` | **NO EXTRAÍBLE** (ver aviso) |
| 05 | `week_05\05 Recuperación ante Fallos.pdf` | `01_fuentes_limpias\semana05_teoria_recuperacion_fallos.txt` |
| 05 | `week_05\Laboratorio 05 - Concurrencia.pdf` | `01_fuentes_limpias\semana05_lab_concurrencia.txt` |
| 06 | `week_06\07 BD Espaciales - GiST - Rtree.pdf` | `01_fuentes_limpias\semana06_teoria_espacial_gist_rtree.txt` |
| 06 | `week_06\Laboratorio 06 - PostGIS.pdf` | `01_fuentes_limpias\semana06_lab_postgis.txt` |
| 07 | `week_07\07 BD Vectorial - Recuperación de Información Textual 1.pdf` | `01_fuentes_limpias\semana07_teoria_vectorial_ir.txt` |

> ⚠️ **Aviso honesto sobre dos fuentes:**
> 1. **`week_04\laboratorio 05 - External Algorithm - Bitmap (1).pdf` NO se pudo extraer.** En el material pre-extraído figura con **0 bytes** (`01_fuentes_limpias\semana04_lab_external_bitmap.txt` y `_extract\pdf\week_04__laboratorio 05...txt`). Se intentó recuperarlo con un extractor alternativo (script de apoyo en `.review_tmp\extract_w04lab.py`): el PDF tiene 1 076 175 bytes, **0 objetos `/Font`**, 2 `/Image`, 15 operadores `BT` y **ningún content stream de texto decodificable** → es un PDF basado en imágenes (escaneado/exportado como imagen). **No hay `pypdf`, `pdfminer`, `pymupdf`, `PyPDF2` ni el binario `pdftotext` instalados** en este equipo, y no se instaló nada por red. Por lo tanto, **la comparación de la semana 04 se apoya en el PDF de teoría (`04 Bitmap Index Scan - External Algorithm.pdf`) y en el título del laboratorio**, no en su enunciado detallado. Si el profesor evalúa ese laboratorio, el equipo debe abrir el PDF original.
> 2. Los `.txt` de los laboratorios de la semana 02 y 03 provienen de PDFs con codificación `Type1/CFF` mal mapeada: el texto sale en mayúsculas ("3ROFESOR +EIDER 6ANCHEZ") y algunas palabras están corruptas (`PfGINA` = "página", `FB` = "factor de bloque"). Las citas se transcriben tal cual aparecen, aclarando la lectura.

**Reglas respetadas:** no se modificó **ningún** archivo bajo `C:\Users\illes\Documents\BD2` ni ningún archivo fuente del proyecto (verificado: los tamaños y fechas de modificación de `BD2\_extract\pdf\*` siguen idénticos a la inspección inicial). El único destino de escritura es este informe (`Proyecto-BD2\.review\alineacion_clase.md`) y los archivos temporales en `Proyecto-BD2\.review_tmp\`.

---

## 1. Resumen ejecutivo

### 1.1 Lo que se puede defender TAL CUAL (alineación fuerte, con cita)

| # | Módulo del proyecto | Por qué está alineado |
|---|---|---|
| 1 | **Registros de longitud fija empaquetados con `struct`** (`storage\record.py`) | Es *literalmente* el patrón de `week_02\Fijo2.py:12-13` (`FORMAT = '12s12si'`, `RECORD_SIZE = struct.calcsize(FORMAT)`) y `Fijo2.py:22` (`file.seek(pos * RECORD_SIZE)`). El proyecto hace `struct.pack`/`unpack` con formato calculado y `seek(offset)` directo. |
| 2 | **RID = (page_id, slot_id)** (`storage\heap_file.py:7-24`) | La clase lo define explícitamente: *"RID = (page_id, slot_number). Identificador físico único de cada tupla"* (`semana01_teoria_arquitectura_SGBD.txt:505-506`), y el Lab 02 pide *"CADA REGISTRO DEBERÁ IDENTIFICARSE MEDIANTE RID (PAGE_ID, SLOT_ID)"* (`semana02_lab_heapfiles.txt:42-44`). |
| 3 | **Lectura directa O(1) por RID, sin recorrer el archivo** (`heap_file.py:59-61,67-72`) | El Lab 02 lo exige: *"OBTIENE EL REGISTRO UTILIZANDO (PAGE_ID, SLOT_ID) SIN RECORRER SECUENCIALMENTE TODO EL ARCHIVO CON O(1)"* (`semana02_lab_heapfiles.txt:149-157`). |
| 4 | **Borrado lógico con tombstone** (`record.py:31-33`; `heap_file.py:142-151`) | La clase enseña eliminación lógica: *"Delete: Remueve registros mediante eliminación lógica (marcado como inactivo) o física"* (`semana02_teoria_...txt:159-169`) y el Lab 02 pide *"VERIFICAR QUE read() NO RETORNE REGISTROS ELIMINADOS"* (`semana02_lab_heapfiles.txt:304-307`). `heap_file.read()` devuelve `None` si el flag no es `USED` (`heap_file.py:138-140`). |
| 5 | **Archivo Secuencial con zona de overflow (`.main` + `.aux`)** (`storage\sequential_file.py:21-36`) | Es la *"Estrategia del Overflow File (1)"* de la clase: *"Las inserciones más recientes se guardan en un espacio extra... La búsqueda debe realizarse en ambos espacios. De forma periódica, el archivo de datos debe ser reconstruido utilizando los registros del espacio extra"* (`semana02_teoria_...txt:2562-2576`). El proyecto busca en `.main` y luego en `.aux` (`sequential_file.py:113-129`) y reconstruye (`:212-229`). |
| 6 | **Umbral de reorganización = 30 %** (`sequential_file.py:3-4,199-210`) | El enunciado lo exige ("cuando haya más del 30 % de espacio desperdiciado", `.enunciado.txt:20`) y la clase justifica la reorganización periódica (`semana02_teoria_...txt:2854-2863`). `REORG_AUX_RATIO = REORG_WASTE_RATIO = 0.3`. |
| 7 | **B+ Tree: hojas enlazadas + rango sin volver a bajar** (`indexes\bplus_tree.py:93-97,275-306`) | Propiedad de clase: *"Todos los nodos hoja están conectados de manera similar a una lista enlazada"* (`semana03_teoria_hash_btree.txt:499-500`) y el Lab 03 lo pide: *"APROVECHE EL ENLAZADO ENTRE HOJAS PARA RECORRER EFICIENTEMENTE EL INTERVALO SOLICITADO SIN VOLVER A DESCENDER POR EL ÁRBOL"* (`semana03_lab_hashfile_btree.txt:694-696`). |
| 8 | **B+ Tree: split de hojas "copia hacia arriba" + merge/redistribución con hermano** (`bplus_tree.py:84-117,183-218`) | La clase define exactamente esa política de eliminación: *"Si las entradas en el nodo y un hermano encajan en un solo nodo, fusione los hermanos. Si no encajan, redistribuir los registros entre el nodo y un hermano de manera que ambos tengan más del número mínimo de entradas"* (`semana03_teoria_hash_btree.txt:739-749`). |
| 9 | **B+ Tree: nodos al menos a la mitad** (`bplus_tree.py:24-34`) | *"Los nodos deben estar siempre llenos al menos en su mitad"* (`semana03_teoria_hash_btree.txt:506-507`) y Lab 03: *"LOS NODOS DEBEN TENER AL MENOS ⌈FB/2⌉ ENTRADAS PARA MANTENER EL BALANCEO"* (`semana03_lab_hashfile_btree.txt:454`). |
| 10 | **Hash Extendible usa los D bits MENOS significativos** (`indexes\extendible_hash.py:51-53`) | La función del laboratorio es `pos_bucket = binary_hash(key) % 2^D` y el ejemplo de la clase calcula explícitamente `Bin(Key % 2^D)` (`semana03_teoria_hash_btree.txt:1339,1358,1379`). El proyecto hace `self._hash(key) & ((1 << self.global_depth) - 1)` = los `D` bits bajos. **Coincide bit a bit con la clase.** |
| 11 | **Hash Extendible: duplicación de directorio + split con `local_depth`, fusión de "buddy" y reducción del directorio** (`extendible_hash.py:116-161,198-268`) | Clase: *"Crece duplicando directorio solo cuando es necesario"*, *"Si el bucket esta lleno, dividir el bucket y reinsertar todos los registros... Se crean nuevos buckets con una nueva profundidad local (d = d + 1). El directorio es modificado... entonces aumentar la profundidad global (D = D + 1)"* y *"Si dos buckets tienen poco elementos y tienen el mismo prefijo en la profundidad local anterior (d-1), proceder a mezclar"* (`semana03_teoria_hash_btree.txt:1301,1556-1587`). El Lab 03 pide justamente *"¿CÓMO GESTIONARÁ LOS BUCKETS QUE QUEDAN LIBRES? FUSIÓN DE BUCKETS, REDUCCIÓN DEL DIRECTORIO, REUTILIZACIÓN"* (`semana03_lab_hashfile_btree.txt:205-207`). |
| 12 | **External Sort = Two-Phase Multiway Merge Sort con k-way merge y min-heap** (`operators\external_sort.py:139-199,251-298`) | Clase: *"Fase 1: Run Generation... Fase 2: Multiway Merging"*, *"h = B-1 buffers de entrada + 1 salida"*, y *"En cada iteración, seleccione el ID del término más bajo que no se haya procesado utilizando un min-heap"* (`semana04_teoria_bitmap_external.txt:171-190,271-279`). El proyecto: runs ordenados en RAM → archivos temporales → `heapq` k-way merge con `fan_in` runs simultáneos → pasadas adicionales si sobran runs (`external_sort.py:168-190`), que es lo que el slide dibuja como *"¿Y si hay mas datos? Merge Pass 1, Merge Pass 2"* (`semana04_teoria_...txt:196-212`). |
| 13 | **External Hashing = Grace Hashing en dos fases (particionar / construir en RAM)** (`operators\external_hashing.py:28-62,557-584`) | Clase: *"Fase 1: Particionamiento: Aplicar función hash h_p a la llave de cada tupla. Distribuir tuplas en B-1 particiones en disco... Fase 2: Construcción: Leer cada partición (una a la vez) en memoria. Construir tabla hash en RAM usando una segunda función hash diferente h_r"* (`semana04_teoria_...txt:342-377`). El proyecto particiona con `hash((depth, key)) % partition_count` (`external_hashing.py:582-584`) y vuelve a particionar si una partición no cabe (`repartition_passes`), que es la extensión recursiva correcta. |
| 14 | **External Hashing para GROUP BY, JOIN y DISTINCT** (`external_hashing.py:68,251`, `query\executor.py:369-376`) | Clase: *"¿Como extender External Hashing para join y distinct? SELECT * FROM R, S WHERE R.a=S.a"* (`semana04_teoria_...txt:451-515`). |
| 15 | **LockManager con protocolos PS (compartido) y PX (exclusivo) y liberación solo al final** (`transactions\lock_manager.py:17,32-47,49-68,74-86`) | Los nombres y la semántica son los de clase: *"Bloqueo Exclusivo (Protocolo PX)"* (`semana05_teoria_recuperacion_fallos.txt:791`), *"Bloqueo Compartido (Protocolo PS)"* (`:832`). `release_all` documenta *"Protocolo Strict 2PL"* y libera **todos** los locks en `commit`/`rollback`, lo que es exactamente el **2PL estricto/riguroso** del material complementario (`04_conocimiento_optimo\03_semana05_optimo.md:235-249`). |
| 16 | **Demostración de concurrencia con hilos, race condition y su resolución** (`transactions\demo_concurrencia.py`) | El enunciado lo exige (`.enunciado.txt:39-42`) y el problema demostrado es exactamente *"Actualización perdida"* de la clase (`semana05_teoria_...txt:194-330`). El `demo_concurrencia.py:48-62` corre el mismo escenario 3 veces sin locks (resultado variable) y 3 veces con PX (X = 190 estable). |
| 17 | **Recorrido de 2PL por grano fino (registro/clave)** | Clase: la granularidad *"pueden aplicarse a diferentes unidades de dato: Base de datos, Tabla, Registro, Campo"* con el trade-off *"Grano más fino → Mayor concurrencia → Mayores posibilidades de interbloqueo"* (`semana05_teoria_...txt:775-784`). El proyecto bloquea por **clave** (`lock_manager.py:26-30`: `_recursos[recurso_id]`), es decir grano registro. |

### 1.2 Lo que hay que poder JUSTIFICAR (desviación defendible en una frase)

Cada punto trae la frase lista para memorizar. Etiqueta **(a)** = elección legítima y explicable; **(b)** = riesgo real, el profesor puede decir "eso no es como lo enseñé".

1. **(a) La página no tiene header; el control de espacio libre vive en un archivo aparte `.free` (pickle).**
   *Frase:* «Usamos el patrón de `Variable1.py/.cpp` de la semana 02 —un archivo de índice auxiliar con las posiciones— aplicado a los slots libres, en vez del puntero *first-deleted* dentro del header, porque nuestro esquema es de longitud fija y así el layout de la página queda idéntico al de `Fijo2.py`: `PAGE_SIZE // record_size` slots contiguos y acceso directo por `page*page_bytes + slot*record_size`.»
   Refuerzo: `Variable1.py:11-17` escribe la posición en un `indexfile` con `struct.pack("Q", pos)`; el proyecto hace `pickle.dump(self.free_pages, f)` en `path + ".free"` (`heap_file.py:43,63-65`). **Mismo patrón de la clase.**

2. **(a) El Archivo Secuencial no está paginado: `.main`/`.aux` son arrays planos de registros con `seek`.**
   *Frase:* «Es la organización *Sorted/Sequential File* de Elmasri Cap. 13/17 que vimos en clase —inserción ordenada, eliminación lazy y reconstrucción periódica del *overflow*— implementada sobre el archivo binario de longitud fija de `Fijo2.py`; la paginación del heap no la replicamos porque el propio slide dice que *en la práctica el espacio auxiliar se maneja en el mismo archivo de datos* y el costo real se mide en el número de `log2(b)` accesos de la búsqueda binaria.»
   Refuerzo: slide *"Búsqueda Binaria: El Costo Real... accesos con búsqueda binaria (⌈log2 b⌉)"* (`semana02_teoria_...txt:2480-2513`) y *"En la práctica, el espacio auxiliar se maneja en el mismo archivo de datos"* (`:2976-2977`). El proyecto implementa la búsqueda binaria exacta (`sequential_file.py:90-111`).

3. **(a) El B+ Tree y el Hash Extendible son estructuras en memoria (objetos Python / `dict`), no páginas en disco.**
   *Frase:* «El laboratorio de la semana 03 nos pedía **diseñar** las estructuras de nodo y el pseudocódigo de los algoritmos con el análisis de accesos a disco; nosotros implementamos y verificamos la *lógica* del índice —separadores, split en cascada, merge, profundidades local/global, reducción del directorio— sobre objetos, y el costo de E/S lo medimos con el número de nodos visitados. La persistencia paginada del índice es el siguiente paso.»
   **⚠️ Matiz:** esto es (a) *solo si* el equipo puede mostrar el análisis de accesos; si el profesor pregunta "¿cuántos accesos a disco hace tu búsqueda?" y la respuesta es "ninguno, todo está en RAM", el punto se vuelve **(b)**. Ver §4.4.

4. **(a) El bucket del Hash Extendible se llena por *claves distintas*, no por *registros*.**
   *Frase:* «`bucket_capacity` cuenta entradas de índice (claves distintas) y los RIDs duplicados cuelgan en una lista de la clave, así que el *factor de bloque* del laboratorio se respeta contando entradas de índice; si el bucket está lleno hacemos split y rehash, que es el algoritmo de Fagin que vimos.»
   Evidencia: `extendible_hash.py:102` (`bucket.distinct_keys() < self.bucket_capacity`), `stats()` expone `load_factor = distinct_keys / (buckets * capacity)` (`:313-317`).
   **⚠️ Riesgo:** el Lab 03 dice *"FACTOR DE BLOQUE FB = 3"* sobre **registros** (`semana03_lab_hashfile_btree.txt:184-190`). Si el profesor introduce 4 claves iguales con `bucket_capacity = 3`, el bucket tendrá 4 entradas. Aclararlo proactivamente.

5. **(a) El Hash Extendible no usa buckets de overflow encadenados.**
   *Frase:* «Implementamos el hashing extendible *puro* de Fagin que está en la diapositiva —siempre divide y rehashea—; los buckets de desbordamiento encadenados son una variante que el laboratorio pide como caso borde (`encadenamiento máximo de N=1 y si se supera, rehashing`), y en nuestra implementación el rehashing recursivo hace que esa rama nunca se alcance.»
   Evidencia: `semana03_teoria_hash_btree.txt:1565-1569` (*"Si ya no se puede incrementar la profundidad, se produce desbordamiento de buckets... entonces aumentar la profundidad global"*) vs. `semana03_lab_hashfile_btree.txt:194-196`.

6. **(a) `PAGE_SIZE = 4096` pero la página efectiva es `slots_per_page * record_size`.**
   *Frase:* «Declaramos `PAGE_SIZE = 4096` como tamaño de bloque objetivo y la página efectiva es `(4096 // record_size) * record_size` —4047 B para `users`, 4087 B para `departments`— porque no partimos registros entre páginas; es el mismo criterio de la diapositiva de longitud fija: *"la modificación no permite que los registros crucen el límite del bloque"*.»
   Evidencia: `heap_file.py:4,42,56,60`; slide `semana02_teoria_...txt:1594-1601`. **Verificado numéricamente:** `users` → `record_size = 1+4+32+4+16 = 57`, `4096//57 = 71`, `71*57 = 4047` = tamaño exacto de `backend\data\users.dat`. `departments` → `record_size = 61`, `4096//61 = 67`, `67*61 = 4087` = tamaño exacto de `departments.dat`.

7. **(a) Solo hay registros de longitud fija; `TEXT` se normaliza a `VARCHAR(255)`; no hay Slotted Page.**
   *Frase:* «El subconjunto de tipos del motor es `INT`/`FLOAT`/`VARCHAR(n)` y lo implementamos con el archivo binario de longitud fija (`Fijo2`); el Slotted Page con *slot directory* de (offset, length) de la Parte 2 del Lab 02 y del PDF de la semana 02 no lo necesitamos porque no hay campos de tamaño variable, y queda declarado como extensión futura.»
   Evidencia: `sql_parser.py:595-596` (`TEXT/STRING/CLOB/VARCHAR` → `VARCHAR(255)`); slide del Slotted Page (`semana02_teoria_...txt:2019-2104`) y Lab 02 Parte 2 (`semana02_lab_heapfiles.txt:216-243`). **Riesgo moderado (b):** la Parte 2 del Lab 02 sí pide Slotted Page y el PDF de la semana 02 lo presenta como la técnica n.º 3 para longitud variable. Ver §3.3.

8. **(a) El LockManager resuelve conflictos por *timeout* (2 s) y lanza `RecursoBloqueado`, no por *wait-for graph*.**
   *Frase:* «Prevenimos el interbloqueo con un tiempo de espera máximo en lugar de detectarlo con un *wait-for graph*: si la transacción no consigue el lock en 2 segundos, se aborta y se hace `ROLLBACK`, lo que rompe el ciclo de espera. Es una política de *timeout* estándar y la diferencia es que nosotros prevenimos en vez de detectar.»
   Evidencia: `lock_manager.py:19,41-45,61-65`. Clase: *"Detecta deadlocks mediante un wait-for graph"* (`semana01_teoria_arquitectura_SGBD.txt:551-553`) y *"El problema de las técnicas de bloqueo es que puede producirse un interbloqueo"* (`semana05_teoria_...txt:999-1003`). **Riesgo moderado (b):** ver §6.4 — el material insiste en el wait-for graph.

9. **(a) El motor REST serializa las peticiones con un `threading.Lock` global.**
   *Frase:* «El motor de la Parte 1 no es *thread-safe* a nivel de storage porque cada operación abre y cierra el archivo; para que la web no corrompa archivos desde dos peticiones simultáneas, `DemoEngine.run()` toma un mutex global, y la concurrencia real con PS/PX se demuestra en `transactions/demo_concurrencia.py` con hilos.»
   Evidencia: `backend\engine.py:69` (`self._lock = threading.Lock()  # el motor no es thread-safe: serializamos`) y `:110-112`. **Riesgo (b):** el profesor puede decir "tu control de concurrencia no está integrado en el motor". Ver §6.5.

10. **(a) Después de reorganizar el Archivo Secuencial se reconstruyen **todos** los índices, en cada `INSERT` a una tabla secuencial.**
    *Frase:* «`reorganizar()` reescribe `.main` completo, así que todos los RID cambian y los índices quedan colgando; por eso `Catalog.rebuild_indexes()` los reconstruye. Es correcto pero costoso y está documentado como limitación.»
    Evidencia: `query\query_executor.py:264-273`, `query\catalog.py:385-428`, `docs\guia_issues_y_entregables.md:153-163`. **Riesgo (b) de rendimiento:** es O(n) por insert. Ver §3.5.

### 1.3 Lo que hay que CAMBIAR (riesgo real: "eso no es como lo enseñé")

| Prioridad | Qué | Evidencia | Acción concreta |
|---|---|---|---|
| **P0** | **No existe absolutamente nada de recuperación / logging (WAL).** | `grep` sobre todo el proyecto de `WAL|write_ahead|log_file|recovery|checkpoint|undo_log` → **0 coincidencias** en `.py` y `.md`. | Ver §9. No hace falta implementar ARIES para la Parte 1 (el enunciado solo pide BEGIN/END + locks), pero **sí hay que decirlo en voz alta** en la defensa con la frase preparada, y añadir 3 líneas al README/informe. |
| **P0** | **`README.md:198` y `:311-312` afirman cosas que el código no hace.** Dice *"locks compartidos/exclusivos, **crecimiento** y **detección de conflictos**"*. | `lock_manager.py` no tiene fase de crecimiento declarada ni detección de deadlock (solo timeout). | Corregir el README a: *"locks PS/PX por clave, protocolo 2PL estricto (todos los locks se liberan en COMMIT/ROLLBACK) y resolución de interbloqueos por timeout"*. Riesgo alto porque el profesor lee el README. |
| **P1** | **`IndexMetadata` rechaza explícitamente `"bitmap"`**: no hay Bitmap Index Scan. | `query\query_planner.py:59-62` (`allowed = {"hash", "bplus_clustered", "bplus_unclustered"}`) y `tests\test_query_planner.py:636-643` (`test_invalid_index_kind` espera `ValueError` con `"bitmap"`). | No es requisito del enunciado (2.1.2 pide B+ agrupado, B+ no agrupado y Hash Extendible), pero la clase lo enseñó. Frase: *"el enunciado no pide bitmap; nuestro B+ no agrupado ya agrupa los RIDs en las hojas y el planner evita el *heap fetch* desordenado al devolver los RIDs ordenados, que es el problema que el bitmap resuelve."* Y añadirlo al roadmap. |
| **P1** | **El Heap no tiene `FILE_HEADER` (page_size, num_pages) ni `PAGE_HEADER` (n registros, n activos, primer espacio libre), y no implementa `MOVE THE LAST`.** | `grep` de `header|num_records|num_pages|PAGE_HEADER|FILE_HEADER|page_size|nslots|slot_dir|ItemId` sobre `storage\*.py` → **0 coincidencias**. Lab 02 lo exige en `semana02_lab_heapfiles.txt:39-44,95-113`. | **Cambio pequeño y de alto valor:** añadir al `.dat` un `FILE_HEADER` de 16 B (`page_size`, `num_pages`) y a cada página un `PAGE_HEADER` de 12 B (`num_slots`, `num_active`, `first_free_slot`), dejando `.free` como caché. Alternativa mínima: documentar la desviación y la frase de §1.2.1. |
| **P1** | **La reorganización del secuencial puede ser O(n) por insert** y además `insert` devuelve un RID que puede quedar inválido. | `query\query_executor.py:266-273` llama `rebuild_indexes` en **cada** insert secuencial; `sequential_file.py:131-145` devuelve `RID("aux", pos)` calculado antes de la posible reorganización. | Mitigar: solo reconstruir si `n_reorganizaciones` cambió (comparar el contador antes/después). Es un cambio de 3 líneas y elimina el riesgo de rendimiento. |
| **P2** | **`_guardar_free_list()` reescribe el pickle completo del set de páginas en cada insert/delete.** | `heap_file.py:121,131,150` → `pickle.dump(self.free_pages, f)` con todo el set. | Aceptable para la demo; mencionarlo como limitación conocida (*"el `.free` se reescribe entero; en producción sería un append-only o un bitmap de páginas"*). |
| **P2** | **No hay cola de espera (FIFO) por recurso → posible inanición.** | `lock_manager.py:36-46,53-65` usa `Condition.wait()` sin orden de llegada. Clase: *"Cola de espera"* / *"Cola de espera de bloqueo exclusivo"* (`semana05_teoria_...txt:803-804,844`). | Documentar: *"el `threading.Condition` despierta a todos (`notify_all`) y el scheduler decide; no garantizamos FIFO, lo declaramos como limitación."* |

### 1.4 NO CUBIERTO (fuera del alcance de la Parte 1 / aún no implementado)

| Tema | Estado en el proyecto | Veredicto |
|---|---|---|
| **Semana 05: Recuperación ante fallos (WAL, UNDO/REDO, checkpoints, ARIES)** | **Ausente por completo** | **NOT COVERED IN THE PROJECT.** Ver §9. |
| **Semana 06: R-Tree, GiST, PostGIS, Haversine, k-NN** | Ausente (solo planificado) | **NOT COVERED YET** — es la Parte 2 del enunciado (entrega semana 8), planificado en `README.md:665` (`indexes/rtree.py`). |
| **Semana 07: índice invertido, TF-IDF + coseno, BM25, SPIMI** | Ausente (solo planificado) | **NOT COVERED YET** — es la Parte 3 (semana 12), planificado en `README.md:666` (`text/spimi.py`, `text/ranking.py`). |
| **Semana 04: Bitmap Index Scan** | Ausente y **rechazado explícitamente** por el planner | **NOT COVERED** — ver §5.3. |
| **Semana 02: Slotted Page (registros de longitud variable)** | Ausente (todo es longitud fija) | **ALIGNED BUT SIMPLIFIED** — el tipo de dato del proyecto lo permite; ver §3.3. |

---

## 2. Semana 01 — Arquitectura de un SGBD

### 2.1 Qué enseña la clase

Fuente: `week_01\01 Arquitectura de SGDB (1).pdf` → `semana01_teoria_arquitectura_SGBD.txt`.

**(a) Estructura física de una página y del Heap File** (`:490-506`):

> "Estructura de una Página — **Header (24 bytes)** / **ItemId Array** / Tupla 1 / Tupla 2 / Espacio Libre / Tupla N"
> "**Heap File y RID** … **RID = (page_id, slot_number)** — Identificador físico único de cada tupla."

Es decir: la clase exige **header de página (24 B) + arreglo de ItemIds + heap de tuplas**, y RID lógico = (page_id, slot_id).

**(b) Componentes del gestor** (`:510-576`) — el slide titulado *"TRANSACTION MANAGER - Garantizando ACID"* enumera los subcomponentes:

> "**Lock Manager** — Controla el acceso concurrente con locks compartidos (S) y exclusivos (X). **Detecta deadlocks mediante un wait-for graph.** Protocolo **2PL** (Two-Phase Locking): **fase de crecimiento** / fase de decrecimiento."
> "**Log Manager (WAL)** — Write-Ahead Log: cada cambio se escribe en el log ANTES de ir a disco. Garantiza Durability y permite Recovery. **Force-the-Log rule**: el log se sincroniza (fsync) en cada COMMIT."
> "**Recovery Manager** — Tras un crash, usa el WAL para: **REDO** (aplica transacciones confirmadas) / **UNDO** (deshace transacciones incompletas). **Checkpoints** limitan cuánto log hay que releer."

Y el slide de WAL (`:579-604`):

> "**PRINCIPIO WAL**: Todo cambio debe ser registrado en el log ANTES de que la página modificada se escriba en disco. 1. BEGIN Transaction → 2. Modificar página en RAM → 3. Escribir WAL record → 4. COMMIT (fsync WAL) → 5. bgwriter flushea a disco (async)"

**(c) Laboratorio 01 — Repaso PostgreSQL** (`week_01\Laboratorio 01 - Repaso PostgreSQL (1).pdf` → `semana01_lab_postgresql.txt`): restauración del dump `employees`/`departments`, **exploración del catálogo del sistema** (`pg_class.reltuples`, `relpages`, `pg_total_relation_size`, `pg_attribute` para "columnas y tipos de dato de cada tabla" — `:31-55`), es decir tamaño/estructura física de tablas antes de optimizar consultas.

### 2.2 Qué implementa el proyecto

- **RID = (page, slot): ALINEADO.** `storage\heap_file.py:7-24`:
  ```python
  class RID:
      """Record ID: identifica un registro por (num_pagina, num_slot)"""
      def __init__(self, page, slot):
          self.page = page
          self.slot = slot
  ```
- **Header de página de 24 B + ItemId Array: NO EXISTE.** `grep -E "header|num_records|num_pages|PAGE_HEADER|FILE_HEADER|page_size|nslots|slot_dir|ItemId"` sobre `storage\*.py` devuelve **cero coincidencias**. El layout real es (`heap_file.py:28-37`):
  ```
  [Pagina 0][Pagina 1][Pagina 2]...
  cada Pagina tiene un tamano fijo (PAGE_SIZE bytes) y contiene
  N = PAGE_SIZE // record_size slots para registros.
  ```
  El control de espacio libre está en un archivo auxiliar (`heap_file.py:43`: `self.free_path = path + ".free"`, `:48-52`: `pickle.load` de un `set` de páginas con huecos).
- **Lock Manager: PARCIAL.** `transactions\lock_manager.py:17-30` implementa PS/PX por recurso. **No hay `wait-for graph`** (no existe la palabra `wait_for` ni `deadlock` en el proyecto — verificado por `grep`). La resolución de conflictos es por timeout: `:19` `TIMEOUT_SEGUNDOS = 2.0`, `:41-45` y `:61-65` lanzan `RecursoBloqueado`.
- **Log Manager (WAL) / Recovery Manager: AUSENTES.** `grep` de `WAL|write_ahead|log_file|recovery|checkpoint|undo_log` sobre todo el proyecto → **0 coincidencias** en `.py` y `.md`.

### 2.3 Veredicto

| Elemento | Veredicto | Tipo |
|---|---|---|
| RID = (page_id, slot_id) | **ALIGNED** | — |
| Accesso directo por RID O(1) | **ALIGNED** | — |
| Header de página (24 B) + ItemId Array | **DEVIATES** | (a) justificable con la frase de §1.2.1 + **cambio recomendado P1** (§1.3) |
| Lock Manager S/X | **ALIGNED** | — |
| Wait-for graph para deadlock | **DEVIATES** | (a)/(b) mixto → ver §6.4; frase obligatoria en §1.2.8 |
| Protocolo 2PL (crecimiento/decrecimiento) | **ALIGNED** (2PL estricto por comportamiento) | ver §6.3 |
| Log Manager (WAL) + force-the-log | **NOT COVERED** | **P0** — §9 |
| Recovery Manager (UNDO/REDO/checkpoints) | **NOT COVERED** | **P0** — §9 |
| Catálogo del sistema con tamaño/páginas (Lab 01) | **ALINEADO CONCEPTUALMENTE**: el proyecto expone `_table_info` con `size_bytes` de cada archivo, `record_size` y `row_count` | — |
| **Acción:** (1) escribir en el README/informe que WAL y Recovery Manager están **fuera del alcance de la Parte 1** por el propio enunciado; (2) corregir el README de `transactions/`; (3) opcional (alto valor/coste bajo): añadir `FILE_HEADER`/`PAGE_HEADER`. |

---

## 3. Semana 02 — Registros, Paginación y Organización de Archivos

### 3.1 Qué enseña la clase

Fuentes: `week_02\02 Registros, Paginación y Organización de Archivos.pdf` → `semana02_teoria_registros_paginacion_archivos.txt`; `week_02\Laboratorio 02 - HeapFiles (2).pdf` → `semana02_lab_heapfiles.txt`; y el código de ejemplo `week_02\Fijo1.{py,cpp}`, `Fijo2.{py,cpp}`, `Variable1.{py,cpp}` (leídos íntegramente).

**(a) Conceptos de paginación** (`semana02_teoria_...txt:99-123`):

> "**Page**: Cuando un archivo es demasiado grande, se divide en **páginas (bloques de igual tamaño)**… Estas páginas son la **unidad de intercambio entre el disco y la memoria principal**."
> "**Key**… **Index**: Es un puntero a un registro en un archivo."

**(b) Operaciones y eliminación** (`:141-169`):

> "**Read**: … secuencial o **directa (usando un índice o clave)**."
> "**Delete**: Remueve registros mediante **eliminación lógica (marcado como inactivo)** o **física**. Puede requerir reorganización o reutilización del espacio."

**(c) Registros de longitud fija — tres alternativas de eliminación** (`:1627-1893`):
- Alternativa 1: *"Mover los registros i+1, …, n hacia i, …, n-1"* → **O(n)**.
- Alternativa 2: *"Mover el registro n hacia i"* → **O(1)**.
- Alternativa 3: **Free List**: *"No mover registros, pero enlazar todos los registros liberados en una lista (Free List)"*. Y su descripción operativa (`:1801-1841`):
  > "**Free List**: Gestiona espacios de registros eliminados para su reutilización. **Cómo funciona**: 1. El **header** almacena la dirección del primer registro eliminado. 2. Cada registro eliminado guarda la dirección del siguiente. 3. Se forma una **lista enlazada** de espacios reutilizables. **Optimización**: Usar los mismos registros eliminados para almacenar punteros."
  > "Eliminar los registros 3, 5, 1 y 7 → 7->1->5->3-> **O(1)**. Insertar dos nuevos registros → **O(1)**."

**(d) Registros de longitud variable — tres técnicas** (`:1896-2104`):
1. **Archivos de texto** con delimitadores: *"Problemas: El delimitador es parte del contenido. Acceso directo a un registro. Eliminar un registro. O(n) O(n)"*.
2. **Archivos binarios** con **indicadores de longitud al inicio** de cada campo/registro (`:1969-2005`).
3. **Slotted Page** (`:2019-2104`):
   > "Slotted Page: cabecera que indica el inicio de cada registro. Contiene: Localización y tamaño de cada registro. El número de registros de entrada. El final del espacio libre separado para este encabezado."
   > "**Está organizada mediante un Page Header, un ItemId Array (Slot Directory) y el área de datos.** El **ItemId Array** contiene una entrada por registro, típicamente con **(offset, length)** … **Los registros se almacenan desde el final de la página hacia el inicio, mientras que el ItemId Array crece desde el inicio hacia el final.** Esta organización permite mover físicamente los registros durante la compactación **sin cambiar el RID lógico**, siempre que el RID haga referencia al slot y no directamente al offset físico."
   > "**RID = (page_id, slot_id)**"
   > Y el slide de comparación (`:2203-2207`): *"PostgreSQL usa un HÍBRIDO: campos fijos al inicio del tuple (alineados, acceso O(1)) y campos variables al final referenciados por tabla de atributos"*.

**(e) Laboratorio 02, Parte 1 — Heap File con registros de longitud fija** (`semana02_lab_heapfiles.txt:26-181`). Los requisitos textuales:

> "TODAS LAS PÁGINAS DEBERÁN TENER UN TAMAÑO FIJO DE …" (`:26`)
> "EL ARCHIVO DEBERÁ TENER LA SIGUIENTE ESTRUCTURA: … **FILE HEADER** DEBERÁ CONTENER COMO MÍNIMO **page_size** Y **num_pages**. OPCIONALMENTE, EL ESTUDIANTE PODRÁ AGREGAR INFORMACIÓN QUE FACILITE LA LOCALIZACIÓN DE PÁGINAS CON ESPACIO DISPONIBLE" (`:29-41`)
> "CADA REGISTRO DEBERÁ IDENTIFICARSE MEDIANTE **RID (PAGE_ID, SLOT_ID)**" (`:42-44`)
> "**HEADER DE PÁGINA**: PARA REGISTROS DE LONGITUD FIJA, EL HEADER DE CADA PÁGINA DEBE CONTENER: **NÚMERO TOTAL DE REGISTROS EN LA PÁGINA / NÚMERO DE REGISTROS ACTIVOS (NO ELIMINADOS) / PUNTERO AL PRIMER ESPACIO ELIMINADO (PARA FREE LIST STRATEGY)**" (`:95-113`)
> "SE LE PIDE IMPLEMENTAR UNA CLASE LLAMADA … CON **DOS ESTRATEGIAS DE ELIMINACIÓN**: **MOVE THE LAST** (MUEVE EL ÚLTIMO REGISTRO A LA POSICIÓN DEL REGISTRO ELIMINADO) y **FREE LIST** (MANTIENE UNA LISTA DE ESPACIOS LIBRES PARA SER USADOS EN NUEVAS INSERCIONES). ACTUALIZAR LOS METADATOS DE LA PÁGINA" (`:115-131`)
> "INSERT — AGREGA UN NUEVO REGISTRO UTILIZANDO **LA ESTRATEGIA DE LOCALIZACIÓN DE PÁGINAS PROPUESTA**" (`:141-143`)
> "READ — OBTIENE EL REGISTRO UTILIZANDO **(PAGE_ID, SLOT_ID) SIN RECORRER SECUENCIALMENTE TODO EL ARCHIVO CON O(1)**" (`:147-157`)

**(f) Laboratorio 02, Parte 2 — Slotted Page** (`semana02_lab_heapfiles.txt:216-287`):

> "PARA REGISTROS DE LONGITUD VARIABLE CON **SLOTTED PAGE**, EL HEADER DE CADA PÁGINA DEBE CONTENER: **NÚMERO DE SLOTS UTILIZADOS / PUNTERO AL ESPACIO LIBRE (FREE SPACE POINTER) / DIRECTORY DE SLOTS — array de pares (offset, length) para cada registro**"
> "LOS REGISTROS DEBERÁN ALMACENARSE **DESDE EL FINAL DE LA PÁGINA HACIA EL INICIO**, MIENTRAS QUE EL SLOT DIRECTORY CRECERÁ DESDE EL INICIO HACIA EL FINAL"
> "EL ESTUDIANTE DEBERÁ IDENTIFICAR EL PROBLEMA DE **FRAGMENTACIÓN DEL ESPACIO LIBRE**… COMO EXTENSIÓN OPCIONAL SE PODRÁ IMPLEMENTAR `compact()` PARA REORGANIZAR LOS REGISTROS ACTIVOS Y CONSOLIDAR EL ESPACIO LIBRE"

**(g) Archivo Secuencial (Sorted/Ordered File)** (`semana02_teoria_...txt:2450-3052`):

> "Un archivo **ordenado** que mantiene sus registros físicamente ordenados según el valor de un campo de búsqueda." (**Sequential File** = Silberschatz, **Sorted File** = Ramakrishnan, **Ordered File** = Elmasri: *"Son el mismo concepto con tres nombres distintos"*)
> "**Búsqueda Binaria: El Costo Real** — El costo NO se mide en registros comparados, sino en **accesos a bloque/página**: accesos a bloque = ⌈log2 b⌉ … Ejemplo numérico (Elmasri): 30 000 registros, bloque 1024 B, registro 100 B → bfr=10, b=3000 bloques, **12 accesos**. Comparar contra Heap: hasta 3 000 accesos."
> "**Estrategia del Overflow File (1)**: Las inserciones más recientes se guardan en un espacio extra. Debe haber un límite máximo de K registros en ese espacio adicional. **La búsqueda debe realizarse en ambos espacios. De forma periódica, el archivo de datos debe ser reconstruido utilizando los registros del espacio extra.**"
> "(2) *"En el overflow file, también es posible mantener los registros ordenados"*. (3) *"Overflow con registros enlazados… Si no [hay espacio], guardar el registro en el espacio auxiliar… será necesario actualizar los punteros… es fundamental reorganizar el archivo de datos de forma regular"*.
> "**Eliminación de un registro**: Se emplean los **punteros para omitir** los registros que han sido eliminados. Durante la **reconstrucción** del archivo, estos serán eliminados por completo."
> "**Reorganización**: Cuando el overflow crece demasiado se reconstruye el archivo… **En la práctica, el espacio auxiliar se maneja en el mismo archivo de datos**"
> Tabla comparativa final (`:3019-3047`): Heap File vs Sequential File por Scan / Igualdad / Rango / Insertar (`O(1)` vs `O(N)` desplazamiento u overflow) / Eliminar / Mantenimiento (`Ninguno` vs `Reconstrucción periódica (merge overflow)`).

**(h) Código de ejemplo de la semana 02** (referencia directa para la defensa):

| Archivo | Técnica | Patrón clave |
|---|---|---|
| `Fijo1.py:10-24` | Texto, longitud fija 27 caracteres | `file.seek(pos * 27)`, `file.read(27)`, `line[:12]`, `line[12:24]`, `line[24:27]` |
| `Fijo2.py:12-27` | **Binario, longitud fija 28 B** | `FORMAT = '12s12si'`; `RECORD_SIZE = struct.calcsize(FORMAT)`; `struct.pack(FORMAT, ...)`; `file.seek(pos * RECORD_SIZE)`; `struct.unpack(FORMAT, data)` |
| `Fijo1.cpp:32-54` / `Fijo2.cpp:31-46` | Idem en C++ | `setw(12)`; `file.seekg(pos * (12+12+4+1))`; `sizeof(Alumno)` |
| `Variable1.py:11-43` | **Longitud variable = pickle + ARCHIVO DE ÍNDICE aparte con posiciones** | `pos = file.tell()`; `pickle.dump(alumno, file)`; `index.write(struct.pack("Q", pos))`; lectura: `index.seek(pos * calcsize("Q"))` → `file.seek(record_pos)` → `pickle.load(file)` |
| `Variable1.cpp:25-75` | Idem en C++ | `streampos pos = dataFile.tellp()`; `indexFile.write(...&pos, sizeof(streampos))`; `indexFile.seekg(pos * sizeof(streampos))` |

### 3.2 Qué implementa el proyecto

**(a) Registros de longitud fija con `struct`** — `storage\record.py:41-42,53-76`:
```python
self.record_size = 1 + sum(f.size for f in self.fields)          # :41
self._fmt = "<B" + "".join(f.fmt for f in self.fields)           # :42
...
s = str(v).encode("utf-8")[: f.size]
s = s.ljust(f.size, b"\x00")                                     # :62-63
return struct.pack(self._fmt, flag, *packed_vals)                # :65
```
→ Es **exactamente** el patrón de `Fijo2.py:12-13` (formato + tamaño calculado + padding), con un **flag de 1 byte por registro** (`FLAG_EMPTY=0`, `FLAG_USED=1`, `FLAG_DELETED=2`, `record.py:31-33`).

**(b) Heap File paginado** — `storage\heap_file.py`:
```python
PAGE_SIZE = 4096  #bytes por pagina                                   # :4
self.slots_per_page = max(1, PAGE_SIZE // schema.record_size)        # :42
self.free_path = path + ".free"                                      # :43
def _num_paginas(self):
    page_bytes = self.slots_per_page * self.schema.record_size       # :56
def _offset(self, page, slot):
    page_bytes = self.slots_per_page * self.schema.record_size
    return page * page_bytes + slot * self.schema.record_size        # :60-61
```
- **Layout:** `N = PAGE_SIZE // record_size` slots **contiguos**, sin header, sin ItemId Array.
- **Página efectiva ≠ 4096.** Verificado contra los archivos reales:
  | Tabla | `record_size` | `slots_per_page` | página efectiva | tamaño del `.dat` |
  |---|---|---|---|---|
  | `users` | `1+4+32+4+16 = 57` | `4096//57 = 71` | `71*57 = 4047 B` | `4047 B` ✔ |
  | `departments` | `1+4+32+24 = 61` | `4096//61 = 67` | `67*61 = 4087 B` | `4087 B` ✔ |

**(c) Reutilización de espacio libre del Heap** — `heap_file.py:107-132` (insert) y `:142-151` (delete):
```python
for page in list(self.free_pages):                     # :111
    for slot in range(self.slots_per_page):            # :112
        flag, _ = self._leer_slot(f, page, slot)
        if flag != self.schema.FLAG_USED:              # :116
            self._escribir_slot(f, page, slot, values, self.schema.FLAG_USED)
            if not self._pagina_tiene_libres(f, page, excepto=slot):
                self.free_pages.discard(page)          # :120
            self._guardar_free_list()                  # :121
            return RID(page, slot)
```
```python
def delete(self, rid):
    """Marca el slot como tombstone (eliminacion logica) y lo libera para reuso."""  # :143
    self._escribir_slot(f, rid.page, rid.slot, values, self.schema.FLAG_DELETED)      # :148
    self.free_pages.add(rid.page)                                                     # :149
```
→ **Estrategia: tombstone + free list de PÁGINAS en un archivo auxiliar `.free` (pickle)**, no free list enlazada dentro del header de página.

**Verificación de los requisitos del Lab 02 contra el proyecto:**

| Requisito del Lab 02 | Proyecto | Evidencia |
|---|---|---|
| Páginas de tamaño fijo | ✔ (pero página efectiva < `PAGE_SIZE`) | `heap_file.py:4,42,56` |
| **FILE HEADER con `page_size` y `num_pages`** | ✘ **no existe** | grep sin coincidencias en `storage\` |
| RID = (page_id, slot_id) | ✔ | `heap_file.py:7-24` |
| **PAGE HEADER: n total, n activos, puntero al 1.er espacio eliminado** | ✘ **no existe** | idem |
| Estrategia **FREE LIST** | △ implementada como **set de páginas** en `.free`, no como lista enlazada con punteros | `heap_file.py:43,48-52,63-65` |
| Estrategia **MOVE THE LAST** | ✘ **no implementada** | `grep MOVE_THE_LAST\|move_last\|mover_ultimo` → 0 |
| `read(page_id, slot_id)` en O(1) sin scan | ✔ | `heap_file.py:59-61,67-72,134-140` |
| `read()` no devuelve eliminados | ✔ | `heap_file.py:138-140` |
| Crear página nueva si no hay espacio | ✔ | `heap_file.py:78-89,126-132` |
| Mostrar estado de los headers antes/después | ✘ (no hay headers que mostrar) | — |
| **Parte 2: Slotted Page** (n slots, free space pointer, slot directory (offset,length), registros desde el final) | ✘ **no implementado**; todo es longitud fija | `record.py:41`, `sql_parser.py:595-596` |

**(d) Archivo Secuencial Paginado** — `storage\sequential_file.py`:
```python
REORG_AUX_RATIO = 0.3        # :3
REORG_WASTE_RATIO = 0.3      # :4
...
  - Archivo PRINCIPAL (.main): registros almacenados en disco ordenados por clave primaria.
  - Archivo AUXILIAR (.aux): zona de overflow donde se insertan los nuevos registros en orden de llegada.   # :24-25
```
- **Búsqueda binaria en `.main`** (`:90-111`): `mid = (low+high)//2; f.seek(mid*rsize); pk = self._clave(values)` → **implementa literalmente el `⌈log2 b⌉` de la clase**.
- **Búsqueda = main (binaria) + aux (lineal)** (`:113-129`) → slide *"La búsqueda debe realizarse en ambos espacios"*.
- **Eliminación lazy (tombstones)** (`:167-197`): `f.write(self.schema.pack(values, flag=self.schema.FLAG_DELETED))`.
- **Reorganización al 30 %** (`:199-210`):
  ```python
  def _necesita_reorganizar(self):
      """Determina si la cantidad de registros en .aux o los tombstones superan el 30%."""
      n_main = self._num_registros(self.main_path)
      n_aux  = self._num_registros(self.aux_path)
      if n_main == 0:
          return n_aux > 10
      ratio_aux        = n_aux / float(n_main)
      ratio_tombstones = self._tombstones_main / float(n_main)
      return ratio_aux >= REORG_AUX_RATIO or ratio_tombstones >= REORG_WASTE_RATIO
  ```
- **Reorganización = merge de main + aux, ordenar y reescribir** (`:212-229`) → slide *"reconstruido utilizando los registros del espacio extra"*.
- **Rango** (`:147-164`): recorre **todo** `.main` y `.aux`, filtra y hace `sort` en memoria → desaprovecha el orden físico (la clase enfatiza *"Range queries eficientes: BETWEEN, >, < recorren solo el rango físico contiguo de páginas necesario"*, `semana02_teoria_...txt:2523-2524`).

**Nota sobre el patrón "archivo auxiliar de posiciones" (defensa clave):** el `.free` del heap (`heap_file.py:43,63-65`, `pickle.dump(self.free_pages, f)`) es **el mismo patrón** de `Variable1.py:11-17` / `Variable1.cpp:25-41` (archivo de índice aparte que guarda posiciones y se lee con `seek(pos * tamaño)`). Esto convierte la desviación "free-list fuera del header" en **una técnica que la clase enseñó explícitamente**.

### 3.3 Veredicto

| Elemento | Veredicto | Justificación / acción |
|---|---|---|
| Registros de longitud fija con `struct` + padding | **ALIGNED** | idéntico a `Fijo2.py`; frase lista en §1.2.7 |
| `VARCHAR(n)` acotado en vez de longitud variable | **ALIGNED BUT SIMPLIFIED** | (a) *"Implementamos longitud fija (`Fijo2`) porque el esquema usa INT/FLOAT/VARCHAR(n); el Slotted Page de la Parte 2 del Lab 02 queda como extensión."* |
| **Slotted Page / slot directory** | **NOT COVERED** | (b) **riesgo moderado**: el Lab 02 Parte 2 y el PDF de la semana 02 lo piden. Acción mínima: escribir en el informe *"no aplica a la Parte 1 por el subconjunto de tipos"* y enlazar a la diapositiva del híbrido de PostgreSQL. |
| Página de tamaño fijo (`PAGE_SIZE=4096`) pero página efectiva = múltiplo de `record_size` | **DEVIATES** (defendible) | (a) frase en §1.2.6; los números son verificables contra los `.dat` reales. |
| Free list de espacio libre (reutilización) | **ALIGNED BUT SIMPLIFIED** | (a) *"El free list vive en un archivo auxiliar `.free` (patrón `Variable1.py`), no en el `page_header`, y no es una lista enlazada sino un set de páginas."* |
| `MOVE THE LAST` como segunda estrategia de borrado | **NOT COVERED** | (a) *"El enunciado pide 'una estrategia de reutilización de espacios libres'; el laboratorio pedía dos, nosotros implementamos la de free list y descartamos `MOVE THE LAST` porque nuestras páginas no se fragmentan por compactación."* **⚠️ (b) si el profesor evalúa el Lab 02 tal cual.** |
| Eliminación lógica (lazy) en el secuencial | **ALIGNED** | slide *"Se emplean los punteros para omitir los registros que han sido eliminados"* `:2730-2735` |
| `FILE_HEADER` (page_size, num_pages) y `PAGE_HEADER` | **NOT COVERED** | **P1** — cambio pequeño y de alto valor; ver §1.3 |
| Inserción ordenada en el secuencial | **ALIGNED BUT SIMPLIFIED** | El proyecto inserta **siempre en `.aux`** y no "en el lugar ordenado" del `.main`; es la variante (1) del overflow, no la (3) con punteros enlazados. Frase: *"Usamos el overflow file no ordenado (variante 1) porque es la que la propia diapositiva marca como la práctica, y la búsqueda cubre ambos espacios."* |
| Umbral de reorganización 30 % | **ALIGNED** | `sequential_file.py:3-4` + `.enunciado.txt:20` |
| Búsqueda binaria medida en accesos a bloque | **ALIGNED** | `sequential_file.py:90-111` vs `semana02_teoria_...txt:2480-2513` |
| `range_search` recorre todo en vez de recorrer el rango físico contiguo | **DEVIATES** (menor) | (b) menor: la clase insiste en la ventaja de rango del archivo ordenado. **Acción barata:** en `range_search`, usar `_busqueda_binaria_main(low_key)` para hallar el inicio y leer secuencialmente desde ahí. |
| Reorganización reescribe `.main` y **todos los RID cambian** → reconstruir índices | **DEVIATES de diseño** (riesgo de rendimiento) | (b) `query\query_executor.py:266-273`. **Acción P1:** reconstruir sólo si `n_reorganizaciones` cambió. |

---

## 4. Semana 03 — Indexación Hash y Árboles B+

### 4.1 Qué enseña la clase

Fuentes: `week_03\03 Indexación Hash y Árboles B+ (1).pdf` → `semana03_teoria_hash_btree.txt`; `week_03\Laboratorio 03 - HashFile y BTree (2).pdf` → `semana03_lab_hashfile_btree.txt`.

**(a) Dense vs Sparse Index** (`:39-136`): *"**Dense Index-file**: Contiene una entrada para cada registro… **Sparse Index-file**: Contiene entradas solo para algunos registros… generalmente el primer registro en cada página de datos… Sólo posible si datos están ordenados."*

**(b) Propiedades del B+ Tree** (`:491-512`):

> "**Propiedades del B+ Tree**: Todos los nodos hoja deben estar al mismo nivel de altura. Los nodos hoja apuntan a los registros reales en el archivo de datos. **Todos los nodos hoja están conectados de manera similar a una lista enlazada.** Los nodos internos forman el directorio del índice. Los nodos internos no contienen información del archivo de datos. **Los nodos deben estar siempre llenos al menos en su mitad.**"

**(c) Clustered vs Unclustered** (`:537-718`):

> "Para crear un **índice agrupado**, primero se debe **organizar el archivo de datos, dejando espacio extra en cada página** para futuras inserciones."
> "**Solo puede existir UN índice agrupado por tabla** (el archivo tiene un único orden físico)." / "En **InnoDB (MySQL)**: La PK es siempre el clustered index; **las hojas contienen el registro completo (índice en árbol = tabla)**." / "En **PostgreSQL**: Se ejecuta `CLUSTER table USING index`, reorganiza el data file (heap), pero **el orden no se mantiene automáticamente**."
> "Decimos que el índice está **agrupado** si está construido sobre el mismo atributo utilizado para ordenar los registros en el archivo de datos. De lo contrario, **no agrupado**."
> Costos: Clustered → *"Búsqueda puntual: O(log_R N). Rango: O(log_R N + páginas del rango). Ideal para: PK, búsquedas de rango. Inserción: puede causar page split en heap."* Unclustered → *"Búsqueda puntual: O(log_R N) + heap fetch. Rango: puede ser costoso (random I/O). Ideal para: predicados de alta selectividad. Covering index elimina heap fetch."* Y (`semana03_teoria_...txt:659-663`): *"PostgreSQL usa **bitmap index scan** para agrupar RIDs antes de leer el heap."*

**(d) Inserción / Eliminación en B+ Tree** (`:722-749`):

> "**Inserción (pasos generales)**: Se recorre el árbol desde la raíz en busca del nodo hoja… Si hay espacio en el nodo hoja, agregar el par (clave-dirección)… **En otro caso dividir el nodo y actualizamos el nodo padre (actualización en cascada).**"
> "**Eliminación (pasos generales)**: Se recorre el árbol en búsqueda del nodo hoja que contiene el registro a eliminar. Remover el par (clave-puntero) del nodo hoja. **Si el nodo se queda con pocas entradas… Si las entradas en el nodo y un hermano encajan en un solo nodo, fusione los hermanos. Si no encajan, redistribuir los registros entre el nodo y un hermano de manera que ambos tengan más del número mínimo de entradas. Actualice la clave de búsqueda correspondiente en el nodo padre.** Las eliminaciones pueden ocasionar una actualización en cascada hacia arriba hasta que se encuentre un nodo con más de la mitad de entradas."
> Complejidad (`:753-782`): *"Cada nodo interno tiene entre ⌈R/2⌉ y R entradas… Cada nodo hoja tiene entre ⌈R/2⌉ y R-1 entradas. Ya que el último espacio se reserva para el puntero al siguiente nodo."*

**(e) Hash File — Static Hashing** (`:899-1281`):

> "*index(key) = h(key) mod M*. key: clave de búsqueda. **M**: número de bloques disponibles."
> "**Bucket**: los datos son organizados en buckets. Un bucket generalmente corresponde a **una página/bloque** en donde se almacena uno o más registros."
> "**Static Hashing** — Definición: La función de hash asigna cada clave a un bucket en un **rango fijo** de direcciones. Cuando los buckets se llenan, se crean **áreas de overflow (encadenamiento)**."
> "**Manejo del overflow: desbordamiento encadenado.**" / "**Eliminación**: localizar la página del registro usando la función hash. Eliminar el registro del main bucket o del overflow. **En este último caso, traer un elemento del overflow bucket hacia el main bucket.**"
> "**Deficiencias**: … las bases de datos crecen o disminuyen con el tiempo. Posible solución: reorganización periódica… **Mejor solución: permitir la modificación del número de buckets dinámicamente.**"

**(f) Extendible Hashing** (`:1285-1603`) — **el texto central para comparar**:

> "Introducido por Ronald **Fagin et al. (1979)**… Es un tipo de hash dinámico para gestionar bases de datos que crecen y reducen su tamaño en el tiempo (transaccionales). La función hash genera una **secuencia de bits**. En cualquier momento, **solo se usa un sufijo/prefijo del binario** para indexar los registros en una **tabla de direcciones de buckets**. **Crece duplicando directorio solo cuando es necesario.**"
> Slide de ejemplo (`:1305-1328`): *"Número de bits en el sufijo común de la secuencia de bits correspondiente a los registros en el bucket"*, *"**Profundidad local** d=2 d=3 d=3 d=3 d=2"*, *"**Profundidad global D = 3**"*, *"Todos los registros que terminan en 01 / Todos los registros que terminan en 111"*.
> Slide de ejemplo con función concreta (`:1332-1340`): *"D = 2, Key = 2,3,5,7,11,17,18,19,23,28,29,31,32,36 — **Bin(Key % 2^D)** — Factor de bloque: 3"* (y las iteraciones `D = 3` en `:1394-1508`).
> "**Búsqueda**: Sea D la profundidad global del índice. Aplicar la función hash sobre la clave de búsqueda y obtener la secuencia **D-bit**. Haga coincidir la secuencia de D-bit con una entrada del directorio y dirigirse al bucket correspondiente… El índice también provee información de la **profundidad local** de los buckets."
> "**Inserción**: … Si el bucket está lleno, **dividir el bucket y reinsertar todos los registros**. Se crean nuevos buckets con una nueva profundidad local **(d = d + 1)**. **El directorio es modificado.** Si ya no se puede incrementar la profundidad, se produce **desbordamiento de buckets**. Si el desbordamiento es demasiado (parametrizar), entonces **aumentar la profundidad global (D = D + 1)**."
> "**Eliminación**: Localizar el buffer respectivo y remover el registro. **Si el bucket queda vacío, puede ser liberado** (implica actualizar el índice). **Si dos buckets tienen poco elementos y tienen el mismo prefijo en la profundidad local anterior (d-1), proceder a mezclar** (implica actualizar el índice)."
> "**Ventajas**: La eficiencia no se degrada con el crecimiento del archivo de datos. Minimiza el espacio de overflow. **Deficiencias**: El índice podría llegar a ser muy grande… Cambiar el tamaño del índice (tabla de direcciones) es una operación cara. **No soporta búsqueda por rango.**"
> Otras técnicas: *"**Trie Hashing**: Usa un Trie Digital en lugar de un directorio plano… **Linear Hashing (LH)**: Usa un split secuencial de buckets. Mantiene un nivel n y un puntero de división p."*

**(g) Laboratorio 03 — Parte I: Static Hashing PAGINADO (3 pts)** (`semana03_lab_hashfile_btree.txt:23-75`):

> "IMPLEMENTE UNA VERSIÓN BÁSICA DE **STATIC HASHING** EN LA QUE LOS BUCKETS SE ALMACENAN **PAGINADOS EN DISCO**, ES DECIR, **CADA BUCKET CORRESPONDE A UN BLOQUE DE TAMAÑO FIJO PERSISTIDO EN UN ARCHIVO BINARIO**, NO A UNA ESTRUCTURA ÚNICAMENTE EN MEMORIA, CON MANEJO DE DESBORDAMIENTO MEDIANTE ENCADENAMIENTO"
> "DISEÑO DE LA PÁGINA BUCKET: DEFINA EL FORMATO BINARIO DEL BUCKET — **CABECERA CON NÚMERO DE REGISTROS Y PUNTERO AL BUCKET DE OVERFLOW**, SEGUIDO DE UN ARREGLO DE REGISTROS DE TAMAÑO FIJO"
> "INSERCIÓN: CALCULE LA POSICIÓN DEL BUCKET CON UNA FUNCIÓN HASH SIMPLE (P. EJ. `KEY % NUM_BUCKETS`). SI EL BUCKET DESTINO ESTÁ LLENO, CREE Y ENLACE UN BUCKET DE OVERFLOW PERSISTIÉNDOLO COMO UNA NUEVA PÁGINA AL FINAL DEL ARCHIVO."
> "BÚSQUEDA: LOCALICE EL BUCKET PRINCIPAL A PARTIR DEL HASH Y RECORRA LA CADENA DE OVERFLOW…"
> "ELIMINACIÓN: ELIMINE EL REGISTRO Y COMPACTE EL BUCKET. DISCUTA Y JUSTIFIQUE… ¿SE LIBERA LA PÁGINA PARA REUTILIZARLA, SE MANTIENE RESERVADA O SE ENLAZA A UNA LISTA DE ESPACIOS LIBRES?"

**(h) Laboratorio 03 — Parte I: Extendible Hashing (ejercicio manual, 3 pts)** (`semana03_lab_hashfile_btree.txt:171-207`):

> "PARA CALCULAR LA POSICIÓN DEL BUCKET UTILICE LA FUNCIÓN: **POS_BUCKET = BINARY_HASH(KEY) % 2^D**"
> "FACTOR DE BLOQUE **FB = 3**. LA **PROFUNDIDAD GLOBAL INICIA EN D = 1** Y SE INCREMENTA CADA VEZ QUE SE REALIZA UN REHASHING (**D = D + 1**). EL ÍNDICE HASH DEBE DIRECCIONAR A LOS BUCKETS CORRESPONDIENTES EN EL ARCHIVO DE DATOS. **EL ARCHIVO INICIA CON DOS BUCKETS (0 Y 1)** Y SE INCREMENTA EL NÚMERO DE BUCKETS CUANDO OCURRE UN OVERFLOW."
> "CUANDO UN BUCKET SE DESBORDA, APLIQUE **SPLIT** Y ACTUALICE EL ÍNDICE CON LA NUEVA ENTRADA REFERENCIANDO AL BUCKET CREADO. SI YA SE ALCANZÓ LA PROFUNDIDAD GLOBAL, ENCADENE LOS BUCKETS DESBORDADOS. **MANTENGA UN ENCADENAMIENTO MÁXIMO DE N = 1** (SOLO SE PERMITE UN BUCKET ENCADENADO). SI SE SUPERA, APLIQUE REHASHING."
> "B) ALGORITMO DE BÚSQUEDA… CONSIDERANDO TODOS LOS CASOS POSIBLES: BUCKET SIN OVERFLOW, BUCKET CON OVERFLOW, CLAVE INEXISTENTE. C) ALGORITMO DE ELIMINACIÓN… **¿CÓMO GESTIONARÁ LOS BUCKETS QUE QUEDAN LIBRES? FUSIÓN DE BUCKETS, REDUCCIÓN DEL DIRECTORIO, REUTILIZACIÓN?**"

**(i) Laboratorio 03 — Parte II: B+ Tree File** (`semana03_lab_hashfile_btree.txt:336-460`):

> "CONSTRUYA ÍNDICES B+ **AGRUPADOS** Y **NO AGRUPADOS**… **USE FACTOR DE BLOQUE FB = 4** PARA PÁGINAS DE DATOS E ÍNDICE."
> "**PROPIEDADES DEL B+ TREE A RESPETAR**: LOS NODOS DEBEN TENER AL MENOS **⌈FB/2⌉ ENTRADAS** PARA MANTENER EL BALANCEO. LAS INSERCIONES QUE CAUSAN DESBORDAMIENTO APLICAN **DIVISIÓN (SPLIT)**. LOS SPLITS PUEDEN PROPAGARSE **EN CASCADA** INCREMENTANDO LA ALTURA DEL ÁRBOL. **LAS HOJAS DEBEN MANTENERSE ENLAZADAS** PARA FACILITAR BÚSQUEDAS POR RANGO Y RECORRIDOS ORDENADOS."
> "**UNCLUSTERED B+ TREE**: LAS HOJAS APUNTAN A **DIRECCIONES FÍSICAS** DE LOS REGISTROS, NO CONTIENEN LOS REGISTROS COMPLETOS."
> "**CLUSTERED B+ TREE**: [diseñe el algoritmo de búsqueda **por rango**] APROVECHE EL ENLAZADO ENTRE HOJAS PARA RECORRER EFICIENTEMENTE EL INTERVALO SOLICITADO **SIN VOLVER A DESCENDER POR EL ÁRBOL**. INCLUYA UN BREVE ANÁLISIS DE LA CANTIDAD DE ACCESOS A DISCO, DISTINGUIENDO EL COSTO DE LOCALIZAR EL EXTREMO INFERIOR DEL RANGO DEL COSTO DE RECORRER LAS HOJAS ENLAZADAS."

### 4.2 Qué implementa el proyecto

**(a) B+ Tree base** — `indexes\bplus_tree.py`:

| Aspecto | Código | Comparación con la clase |
|---|---|---|
| Orden / factor de bloque | `def __init__(self, order=4)` (`:17`) | Coincide con **FB = 4** del Lab 03. En `backend\engine.py:88,92,97` y `query\catalog.py:301-305` se instancia `order=4`. |
| Mínimo de claves en hoja | `min_leaf_keys = ceil(max_keys / 2)` con `max_keys = order - 1` (`:25-30`) | Clase: *"nodos hoja entre ⌈R/2⌉ y R-1 entradas"* (`:765-769`). ✔ |
| Mínimo de hijos internos | `min_internal_children = ceil(order / 2)` (`:32-34`) | Lab 03: *"al menos ⌈FB/2⌉ entradas"* (`:454`). ✔ |
| Búsqueda | `_find_leaf` con `bisect_right(node.keys, key)` descendiendo por separadores (`:53-64`) | Búsqueda desde la raíz hasta la hoja + búsqueda binaria en la hoja. ✔ |
| Split de hoja | `split = (len(leaf.keys)+1)//2`; la mitad superior va al nodo derecho; **la clave NO se elimina de la hoja** (queda en ambas) y el separador en el padre es la primera clave del derecho (`:84-97,44-46`) | Es un B+ Tree "copia hacia arriba". La clase dice *"dividir el nodo y actualizamos el nodo padre (actualización en cascada)"* (`:733-734`) y *"El B+Tree combina ambos mundos: nodos hoja actúan como índice denso sobre las páginas de datos"* (`:354`). ✔ |
| Split de nodo interno | `split = (len(node.children)+1)//2`; separadores recalculados como *primera clave de cada hijo* (`:119-150,44-46`) | Índice **disperso** en los internos, denso en las hojas — literal al slide `:354`. ✔ |
| Eliminación | `delete` (`:152-181`) → si `len(leaf.keys) < min_leaf_keys` → `_rebalance_leaf` (`:183-218`) | ✔ |
| Redistribución | `_rebalance_leaf:189-199`: si el hermano izquierdo tiene `> min`, **rota** una entrada desde la izquierda; si no, desde la derecha | Clase: *"Si no encajan, redistribuir los registros entre el nodo y un hermano"* (`:744-746`). ✔ |
| Fusión | `_rebalance_leaf:201-218`: fusiona con el hermano izquierdo o el derecho y actualiza el enlace `next`/`prev` | Clase: *"Si las entradas en el nodo y un hermano encajan en un solo nodo, fusione los hermanos"* (`:743-745`). ✔ |
| Cascada hacia arriba | `_after_child_removed` (`:220-232`) → `_rebalance_internal` (`:234-273`) recursivo; reducción de la raíz (`:223-227`) | Clase: *"Las eliminaciones pueden ocasionar una actualización en cascada hacia arriba"* (`:748-749`). ✔ |
| **Hojas enlazadas** | `right.next = leaf.next; leaf.next = right; right.prev = leaf` (`:93-97`) | ✔ (clase `:499-500`) |
| **Rango sin volver a bajar** | `range_search` (`:275-306`): localiza la hoja del extremo inferior y recorre `leaf.next` | ✔ (Lab 03 `:694-696`) |
| Autoverificación | `validate()` (`:308-372`) comprueba: raíz sin padre, claves ordenadas, **todas las hojas a la misma profundidad** (`:348-349`), underflow/overflow, separadores válidos, enlaces `next/prev` correctos, cadena de hojas ordenada y sin claves duplicadas como entradas separadas | Clase: *"Todos los nodos hoja deben estar al mismo nivel de altura"* (`:495`) y *"nodos al menos a la mitad"* (`:506`). **Punto fuerte de defensa: la invariante de clase está codificada en un test ejecutable.** |
| **Paginación en disco** | **NINGUNA.** Los nodos son objetos Python (`class BPlusNode` con `keys`/`children`/`values` en listas, `:5-13`); no hay `seek`, `struct`, `PAGE_SIZE` ni persistencia (`grep` de `seek|struct|open(|PAGE_SIZE|pickle|to_disk|save|persist` en `indexes\` → solo `bulk_load` y `load_factor`). | **DEVIATES.** Clase: *"Están optimizados para operaciones de E/S de disco, ya que minimizan el número de accesos al disco"* (`:410-419`) y *"el costo NO se mide en registros comparados, sino en accesos a bloque/página"*. |

**(b) B+ agrupado** — `indexes\clustered_bplus.py:34-47`:
```python
def insert(self, record):
    key = self._get_key(record)
    if self.unique and self.tree.search(key):
        raise ValueError(f"duplicate clustered key: {key}")
    self.tree.insert(key, deepcopy(record))       # :40
```
→ **Las hojas guardan el registro completo** (`deepcopy(record)`), y `search` devuelve registros completos, no RIDs (`:46-47`). Esto corresponde **exactamente** a la caracterización de la clase para InnoDB: *"las hojas contienen el registro completo (índice en árbol = tabla)"* (`semana03_teoria_hash_btree.txt:586`). Sin embargo, **no** reorganiza un archivo de datos aparte (la construcción de la clase era *"primero se debe organizar el archivo de datos, dejando espacio extra en cada página"*, `:538-540`): en el proyecto el índice **es** el almacén para los registros agrupados.
En la ejecución, el B+ agrupado se registra sobre `employees.salary` (`backend\engine.py:90-94`) y el planner lo usa para **evitar el External Sort** (`query\query_planner.py:302-310,249-267,385-415`) → coincide con la ventaja de clase *"Orden del índice = orden físico de las páginas de datos"* (`:603`).

**(c) B+ no agrupado** — `indexes\unclustered_bplus.py:32-56`:
```python
def insert(self, record, rid):
    """
    Indexa un registro existente.
    El registro NO se almacena en el indice. Solo se guarda su RID bajo
    el valor de `key_field`.                        # :33-38
    """
    self.tree.insert(key, rid)
```
→ **Hojas con (clave, RID)**, denso, apuntando al heap → coincide con *"Los nodos hojas son índices densos"* (`:633`) y *"LAS HOJAS APUNTAN A DIRECCIONES FÍSICAS DE LOS REGISTROS, NO CONTIENEN LOS REGISTROS COMPLETOS"* (Lab 03 `:666`). El ejecutor hace el *heap fetch* por RID (`query\executor.py:470-478`, `query\query_executor.py:808-819`).

**(d) Hash Extendible** — `indexes\extendible_hash.py`:

| Aspecto | Código | Comparación con la clase |
|---|---|---|
| Estado inicial | `global_depth = 1`, `directory = [_Bucket(local_depth=1), _Bucket(local_depth=1)]` (`:32-37`) | Lab 03: *"LA PROFUNDIDAD GLOBAL INICIA EN D = 1… EL ARCHIVO INICIA CON DOS BUCKETS (0 Y 1)"* (`:187-190`). **Coincidencia exacta.** |
| Capacidad de bucket | `bucket_capacity=4` por defecto (`:18`); en el catálogo y en `engine.py` se usa `bucket_capacity=4` (`catalog.py:305,410-415`; `engine.py:88`) | Lab 03 usa FB = 3; el proyecto usa 4. Es un parámetro, no una desviación conceptual. |
| **Función de posición** | `mask = (1 << self.global_depth) - 1; return self._hash(key) & mask` (`:51-53`) | **Usa los D bits MENOS significativos.** La clase calcula `Bin(Key % 2^D)` (`:1339,1358,1379`), que son los D bits bajos. **ALINEADO bit a bit** (el slide menciona "sufijo/prefijo" de forma ambigua en `:1297`, pero su ejemplo resuelto usa `Key % 2^D`). |
| Duplicar directorio | `self.directory = self.directory + self.directory[:]` (`:124`) | *"Crece duplicando directorio solo cuando es necesario."* ✔ Correcto para indexación por bits bajos. |
| Split | `if old_depth == self.global_depth: self._double_directory()`; `split_bit = 1 << old_depth`; redirige los índices con ese bit a `new_bucket`; **reinserta todas las claves** redistribuyéndolas (`:127-161`) | Clase: *"Si el bucket está lleno, dividir el bucket y reinsertar todos los registros… (d = d + 1). El directorio es modificado."* ✔ |
| Profundidad local | `bucket.local_depth = new_depth` (`:141`) y `validate()` comprueba que `local_depth ≤ global_depth` (`:336-339`) | ✔ |
| Fusión (merge) | `_try_merge` (`:198-245`): busca el *buddy* con `buddy_index = directory_index ^ (1 << (depth-1))`, exige **misma `local_depth`** y que la suma de claves distintas quepa; el superviviente baja su `local_depth` a `depth-1` | Clase: *"Si dos buckets tienen poco elementos y tienen el mismo prefijo en la profundidad local anterior (d-1), proceder a mezclar"* (`:1583-1587`). ✔ |
| Reducción del directorio | `_shrink_directory` (`:247-268`): reduce `global_depth` mientras las dos mitades del directorio sean idénticas y ningún bucket requiera la profundidad actual | Lab 03: *"¿CÓMO GESTIONARÁ… **REDUCCIÓN DEL DIRECTORIO**…?"* (`:205-207`). ✔ |
| Sin rangos | `items()`/`keys()` documentan *"No existe garantia de orden, a diferencia de un B+ Tree"* (`:270-283`) | Clase: *"No soporta búsqueda por rango"* (`:1603`). ✔ |
| **Buckets de overflow encadenados** | **NO existen.** El `insert` hace `while True: ... self._split_bucket(bucket)` (`:91-107`), es decir **split recursivo hasta que quepa**, sin cadena de overflow | Lab 03 pide *"MANTENGA UN ENCADENAMIENTO MÁXIMO DE N = 1… SI SE SUPERA, APLIQUE REHASHING"* (`:194-196`). El proyecto implementa el hashing extendible **puro** (la teoría `:1565-1569` sí menciona overflow sólo cuando no se puede incrementar la profundidad). |
| **Paginación en disco** | **NINGUNA.** `_Bucket.records` es un `dict` Python (`:4`). El Lab 03 Parte I pide explícitamente *"CADA BUCKET CORRESPONDE A UN BLOQUE DE TAMAÑO FIJO PERSISTIDO EN UN ARCHIVO BINARIO, NO A UNA ESTRUCTURA ÚNICAMENTE EN MEMORIA"* | **DEVIATES** — ver §4.3. |
| Invariantes verificables | `validate()` (`:320-392`): tamaño del directorio `= 2^D`, `local_depth` válida, capacidad, **número de referencias del directorio = `2^(D-d)`**, prefijo de bits compartido, cada clave en su bucket correcto, contador de entradas | **Punto fuerte de defensa:** las invariantes del algoritmo de Fagin quedan como código ejecutable. |

**(e) Cómo lo usa el planner** (`query\query_planner.py:133-142`):
```python
class QueryPlanner:
    """
    Reglas:
      - Igualdad: Hash > B+ clustered > B+ unclustered.
      - Rango: B+ clustered > B+ unclustered.
      - ORDER BY: B+ puede evitar External Sort.
      - GROUP BY: External Hashing.
      - Equi-JOIN: External Hash Join.
      - Sin indice util: Heap/Sequential Scan.
    """
```
→ Las reglas son **consistentes con los costos de la clase** (`semana03_teoria_hash_btree.txt:808-896`): hash O(1) para igualdad, B+ `O(log_R N)` para igualdad y rango, y *"No soporta búsqueda por rango"* para el hash (por eso el hash nunca aparece como candidato de rango: `_candidate_for_predicate:357-371`).

### 4.3 Veredicto

| Elemento | Veredicto | Justificación / acción |
|---|---|---|
| Orden/FB = 4, mínimo ⌈FB/2⌉ | **ALIGNED** | `bplus_tree.py:17,24-34` vs Lab 03 `:353-354,454` |
| Split de hoja/interno + cascada | **ALIGNED** | `bplus_tree.py:84-150` vs `semana03_teoria_...txt:722-749` |
| Fusión + redistribución con hermano | **ALIGNED** | `bplus_tree.py:183-273` vs `semana03_teoria_...txt:739-749` |
| Hojas enlazadas y rango sin descender | **ALIGNED** | `bplus_tree.py:93-97,275-306` vs Lab 03 `:694-696` |
| B+ agrupado = registros completos en la hoja | **ALIGNED** | `clustered_bplus.py:34-47` vs *"En InnoDB… las hojas contienen el registro completo"* `:586` |
| B+ no agrupado = (clave, RID) al heap | **ALIGNED** | `unclustered_bplus.py:32-47` vs Lab 03 `:666` |
| **B+ Tree en disco (páginas, accesos)** | **DEVIATES** | (b) **riesgo real** si se pregunta el número de accesos a disco. Frase: *"Diseñamos la estructura y los algoritmos como pedía el laboratorio y verificamos las invariantes (altura uniforme, mínimo ⌈FB/2⌉, enlaces) en `validate()`; el costo lo razonamos en número de nodos visitados = altura del árbol, y la persistencia paginada del índice está en el roadmap."* **Acción sugerida:** añadir en el README una línea con el costo teórico (`altura = ⌈log_⌈FB/2⌉ M⌉`, `semana03_teoria_...txt:773-780`) y medirlo con la altura real del árbol en el benchmark. |
| Hash: **D bits bajos** (`Key % 2^D`) | **ALIGNED** | `extendible_hash.py:51-53` vs `semana03_teoria_...txt:1339` |
| Hash: D=1 inicial y dos buckets | **ALIGNED** | `extendible_hash.py:32-37` vs Lab 03 `:187-190` |
| Hash: split + rehash + `d = d+1` + duplicar directorio | **ALIGNED** | `extendible_hash.py:116-161` vs `:1556-1569` |
| Hash: fusión de buckets + reducción del directorio | **ALIGNED** | `extendible_hash.py:198-268` vs `:1583-1587` y Lab 03 `:205-207` |
| Hash: sin búsqueda por rango | **ALIGNED** | `extendible_hash.py:270-275` vs `:1603` |
| Hash: capacidad por **claves distintas** y no por registros | **ALIGNED BUT SIMPLIFIED** | (a) frase en §1.2.4. ⚠️ aclarar el FB del laboratorio. |
| Hash: **sin** buckets de overflow encadenados (N=1) | **DEVIATES** (defendible) | (a) frase en §1.2.5 |
| Hash: **sin** paginación en disco (Lab 03 Parte I) | **DEVIATES** | (b) **riesgo real**: el Lab 03 Parte I pide *"NO A UNA ESTRUCTURA ÚNICAMENTE EN MEMORIA"* y *"cabecera con número de registros y puntero al bucket de overflow"*. Frase: *"Implementamos el hash **dinámico extendible** que pide el proyecto (2.1.2, 'Índice Hash Dinámico (Extendible Hashing)'); el hash **estático paginado** del Lab 03 Parte I es la técnica anterior que el propio material presenta como deficiente ('la función hash mapea a un conjunto fijo de direcciones… Mejor solución: permitir la modificación del número de buckets dinámicamente') y los buckets de overflow del laboratorio son innecesarios en nuestra variante porque siempre dividimos."* **Acción:** añadir al roadmap/README la frase y, si hay tiempo, un `.hash` paginado que reutilice el layout del Lab 03. |
| Hash: solo `Static Hashing` paginado y `Trie Hashing` del laboratorio | **NOT COVERED** | Igual que el punto anterior. `Trie Hashing` tampoco existe. |

---

## 5. Semana 04 — Bitmap Index Scan y Algoritmos Externos

### 5.1 Qué enseña la clase

Fuente: `week_04\04 Bitmap Index Scan - External Algorithm.pdf` → `semana04_teoria_bitmap_external.txt`.
(Aviso: el **laboratorio** de esta semana no se pudo extraer — ver §0.)

**(a) Bitmap Index Scan** (`:23-139`):

> "**Problema**: un índice non-clustered sobre `edad=25` … cada registro puede estar en una **página diferente del heap**."
> "**Solución PostgreSQL: construir un bitmap de páginas en memoria antes de leer el heap.**" → "B+Tree Index Scan (non-clustered, sobre edad)" → "**Bitmap en Memoria (1 bit por página del heap)**" → "**Heap Fetch (ordenado) (páginas en orden físico)**".
> "**Combinación de índices con AND / OR**: `SELECT FROM empleados WHERE edad=25 AND depto='TI';` PostgreSQL construye **un bitmap por cada índice** y luego hace **AND bit a bit** antes de acceder al heap: Bitmap A `idx_edad` **AND** Bitmap B `idx_depto` → "Intersección de páginas" → "**una pasada por el heap**".
> Beneficio explícito: eliminar *"…ng de caché en heap random-access"* (lectura: evitar la pérdida de caché por acceso aleatorio al heap).

**(b) El problema de la escala** (`:143-164`):

> "`SELECT * FROM R ORDER BY R.a`… **No hay ningún índice** en el atributo `R.a`. Tabla R es muy grande (aprox. **50 GB**). La memoria RAM asignada es muy limitada (**≤ 1 GB**)."
> "Las operaciones de BD (**order by, join, group-by, distinct**) requieren materializaciones intermedias que pueden superar ampliamente la RAM disponible." / "**Objetivo**: Minimizar el número de I/O operations (lecturas/escrituras de páginas)."

**(c) External Sorting — Two-Phase Multiway Merge Sort** (`:166-318`):

> "**Fase 1: Run Generation** — [leer B páginas en RAM,] … **⌈B/M⌉ runs iniciales** … [ordenar en memoria y escribir cada run a disco]"
> "**Fase 2: Multiway Merging** — … **B-1 buffers de entrada + 1 salida** … (k-way merge)"
> "¿Y si hay mas datos? **Merge Pass 1 / Merge Pass 2**"
> "**¿Como ordenar bloques usando solo dos buffers?** Si se considera 10 bloques de 10 registros. Se puede hacer **mezclas binarias**, con un árbol de mezcla de **log2(10) = 4 niveles**. Durante cada capa, la lectura en memoria se ejecuta en bloques… se fusiona, se escribe de nuevo."
> "**Pero es más eficiente hacer una fusión de múltiples mezclas**… Abra todos los archivos de bloque simultáneamente y mantenga **un búfer de lectura para cada uno y un búfer de escritura para el archivo de salida**. **En cada iteración, seleccione el ID del término más bajo que no se haya procesado utilizando un min-heap.**"

**(d) External Hashing** (`:324-515`):

> "`SELECT R.a, count(*) FROM R GROUP BY R.a` … **R = 50 GB**, RAM **≤ 1 GB**."
> "**Fase 1: Particionamiento** — Aplicar **función hash h_p** a la llave de cada tupla. **Distribuir tuplas en B-1 particiones en disco (usando B-1 buffers de salida + 1 de entrada)** … [garantiza que] **candidatos a misma cubeta [estén en la misma partición]**"
> "**Fase 2: Construcción** — Leer **cada partición (una a la vez) en memoria**. Construir **tabla hash en RAM usando una segunda función hash diferente h_r**. Procesar la partición … colisiones manejadas con **encadenamiento o probing**."
> "Interpretación para GROUP BY: Se crean **B-1 particiones** en disco. Se hace `partition = h_p(R.a)`… **Todas las tuplas con el mismo R.a caen en la misma partición.**"
> Ejemplo resuelto (`:427-446`): datos `(A),(B),(A),(C),(D),(A),(C),(E),(F),(A),(C),(C)` → `P0: A,A,A,A,E` / `P1: B,D` / `P2: C,C,C,C,F` → `P0` con `h_r`: **`A:4, E:1`**.
> "**¿Como extender External Hashing para join y distinct?** `SELECT * FROM R,S WHERE R.a=S.a;` — 1. **Particionamiento**: Se dividen las relaciones R y S aplicando **la misma función de hash** sobre el atributo a. De este modo, **ambas generan un universo de particiones idéntico**. 2. **Construcción y unión**: Se carga en memoria **la partición i de R** y se construye una tabla hash. Luego se recorren las tuplas de la partición i de S, verificando coincidencias."

**(e) Índices avanzados de PostgreSQL** (`:519-710`): BRIN (*"Almacena resúmenes de bloques de datos (mínimo/máximo)… Índices muy compactos"*), GiST (*"Soporta múltiples tipos de consultas: igualdad, rango, proximidad… Soporta estructuras como R-Tree y Inverted Index"*), SP-GiST (KD-Tree, trie, quadtrees) y la tabla comparativa final.

### 5.2 Qué implementa el proyecto

**(a) External Sort — ALINEADO en el algoritmo.** `operators\external_sort.py`:
```python
class ExternalSort:
    """
    `memory_limit_records` limita cuántos registros se ordenan en RAM por run.
    `fan_in` limita cuántos runs se combinan simultáneamente.       # :48-51
    """
    def __init__(self, memory_limit_records=1000, fan_in=8, temp_dir=None):   # :53-58
```
- **Fase 1 (Run Generation)** (`:135-162`): acumula `batch` hasta `memory_limit_records`, ordena en RAM (`_write_sorted_run:235-241`) y **escribe el run a un archivo temporal** (`:245-248`, `pickle.dump`). ✔ *"leer B páginas en RAM… ordenar… escribir cada run a disco"*.
- **Fase 2 (Multiway Merge)** (`:168-199` + `:251-298`): `while len(runs) > self.fan_in:` fusiona grupos de `fan_in` runs en pasadas sucesivas y luego una fusión final → corresponde a *"B-1 buffers de entrada + 1 salida"* y a *"¿Y si hay mas datos? Merge Pass 1, Merge Pass 2"*.
- **min-heap** (`:276-279,295-298`): `heapq.heappush(heap, (wrapped_key, run_index, record))` → literal a *"seleccione el ID del término más bajo… utilizando un min-heap"*.
- **Estadísticas** (`ExternalSortStats`, `:12-18,220-226`): `initial_runs` (=⌈B/M⌉ del slide), `merge_passes`, `temporary_files`. **Excelente para la defensa: el propio código expone los parámetros del modelo de la clase.**
- **`ORDER BY` multi-columna y DESC**: `_SortAtom` con `descending`/`nulls_last` (`:21-44`); `query\executor.py:518-530` aplica el orden estable de derecha a izquierda.
- **Diferencia respecto al slide:** la memoria se mide en **registros**, no en páginas/buffers (`memory_limit_records`), y los `fan_in` buffers son descriptores de archivo, no páginas. Defendible: ver §5.3.

**(b) External Hashing — ALINEADO.** `operators\external_hashing.py`:
```python
class ExternalHashing:
    """
    Esto implementa el patrón de Grace Hashing:
        input -> hash partitions -> procesamiento por partición      # :30-31
    """
    def __init__(self, memory_limit_records=1000, partition_count=8, temp_dir=None, max_depth=8):  # :41-47
```
- **Fase 1 (Particionamiento)** (`_partition_iterable:557-580`): crea `partition_count` archivos temporales, un buffer de salida por partición, y deriva cada tupla con `_partition_index` (`:582-584`: `hash((depth, key)) % self.partition_count`) → `B-1` buffers de salida + 1 de entrada. ✔
- **Reparticionado recursivo** (`repartition_passes`, `max_depth`): si una partición no cabe en memoria, **vuelve a particionar** — es la extensión correcta del algoritmo y evita el fallo por *skew*.
- **Fase 2 (Construcción)** (`_group_partition:169-180`): carga una partición en memoria y construye la tabla hash en RAM con **segunda función distinta** (la del `dict`, con `depth` distinto). ✔
- **GROUP BY** (`group_by:68-166`), **JOIN** (`hash_join:251-350`, con `SUPPORTED_JOINS = {"inner","left","right","full"}` `:39`), **DISTINCT**, agregados `count/sum/min/max/avg` (`SUPPORTED_AGGREGATES` `:38`). ✔ Coincide con *"¿Como extender External Hashing para join y distinct?"*.
- **Uso desde el plan** (`query\query_planner.py:207-247`): `EXTERNAL_HASH_JOIN` para equi-join, `NESTED_LOOP_JOIN` cuando el operador no es igualdad, `EXTERNAL_HASH_GROUP_BY` para GROUP BY. ✔ Coincide con la clase.

**(c) Bitmap Index Scan — NO EXISTE, y el planner lo rechaza explícitamente.**
`query\query_planner.py:59-62`:
```python
def __post_init__(self):
    allowed = {"hash", "bplus_clustered", "bplus_unclustered"}
    if self.kind not in allowed:
        raise ValueError(f"unsupported index kind: {self.kind}")
```
Y la propia suite de tests **verifica que "bitmap" debe fallar** (`tests\test_query_planner.py:636-643`):
```python
def test_invalid_index_kind():
    with pytest.raises(ValueError, match="unsupported index kind"):
        IndexMetadata("bad", "users", "id", "bitmap")
```
Búsqueda global de `bitmap|Bitmap|BITMAP` en todo el proyecto `.py` → **1 sola coincidencia**, y es ese test. **No hay bitmap de páginas, ni combinación AND/OR de bitmaps, ni *heap fetch* ordenado.**

### 5.3 Veredicto

| Elemento | Veredicto | Justificación / acción |
|---|---|---|
| External Sort: run generation + k-way merge + min-heap + B-1 buffers | **ALIGNED** | `external_sort.py:139-199,251-298` vs `semana04_teoria_...txt:171-190,271-279`. **Frase de defensa:** *"Es el Two-Phase Multiway Merge Sort de la clase: fase 1 genera ⌈N/M⌉ runs ordenados de `memory_limit_records` registros, fase 2 los fusiona con un min-heap y `fan_in` buffers de entrada —que es exactamente B-1 entradas más 1 de salida—; si hay más runs que buffers, hacemos pasadas adicionales de merge como muestra el slide."* |
| External Sort: memoria en **registros** y no en páginas | **ALIGNED BUT SIMPLIFIED** | (a) *"El operador trabaja sobre un iterable de tuplas Python, así que la unidad de memoria es el registro y `fan_in` es el número de buffers de entrada del merge; el modelo de páginas se conserva en la estructura del algoritmo, y `ExternalSortStats` reporta `initial_runs` y `merge_passes` para revisar el costo."* |
| External Hashing: dos fases, `h_p` en disco y `h_r` en RAM | **ALIGNED** | `external_hashing.py:557-584,169-180` vs `:342-377` |
| External Hashing para GROUP BY / JOIN / DISTINCT | **ALIGNED** | `external_hashing.py:68,251`; `query_planner.py:207-247` vs `:451-515` |
| **Bitmap Index Scan (1 bit por página + AND/OR de bitmaps + heap fetch ordenado)** | **NOT COVERED** | (b) **riesgo real si el profesor pregunta por el laboratorio de la semana 04.** El enunciado **no** lo exige (2.1.2 pide B+ agrupado/no agrupado y Hash Extendible), pero la clase lo enseñó. **Frase de defensa:** *"No implementamos bitmap; el problema que resuelve —evitar el heap random-access agrupando los RIDs por página— lo resolvemos parcialmente haciendo que el B+ no agrupado devuelva los RIDs en orden de clave y materializando por RID, y reconocería la técnica como el siguiente paso: un arreglo de bits por página del heap y la intersección AND/OR de dos bitmaps antes del fetch."* **Acción sugerida (barata y de alto impacto):** añadir en `query_planner.py` un `kind="bitmap"` que sea `bplus_unclustered + bitmap de páginas` y usarlo cuando hay **dos o más predicados sobre columnas indexadas** (el caso del slide `edad=25 AND depto='TI'`). Con 30–40 líneas se cierra el único hueco técnico de la semana 04. |

---

## 6. Semana 05 — Control de Concurrencia

### 6.1 Qué enseña la clase

Fuentes: `week_05\05 Recuperación ante Fallos.pdf` → `semana05_teoria_recuperacion_fallos.txt`; `week_05\Laboratorio 05 - Concurrencia.pdf` → `semana05_lab_concurrencia.txt`.

**(a) Transacción, ACID y estados** (`:42-95`):

> "Un conjunto de operaciones de acceso a base de datos que conforman una **unidad lógica de trabajo**… Puede iniciar con una instrucción **BEGIN TRANSACTION**… **COMMIT**: transacción exitosa, los cambios se deben hacer efectivos (persistencia). **ROLLBACK**: transacción no exitosa, los cambios se deben deshacer."
> ACID: *"Atómica — Se realizan todas las acciones o no se realiza ninguna. Consistente… Aislada — Una transacción no puede afectar otra aunque se ejecuten concurrentemente. Durable — Una vez que hace COMMIT, la base de datos debe persistir los cambios."*
> Estados: Activa → Parcialmente confirmada → Confirmada / Fallida → Terminada.

**(b) Problemas de concurrencia** (`:194-476`): Actualización perdida (`:195-330`, con el ejemplo numérico **X=100, T1: X=X-10, T2: X=X+100 → 90 / 90**), Dependencia no confirmada / lectura sucia (`:333-462`), **Suma incorrecta** (`:467-471`), **Lectura no repetible** (`:472-474`).

**(c) Serializabilidad por conflictos** (`:480-747`):

> "Una **planificación serializable** es una planificación concurrente **equivalente a una secuencial**."
> "**Serialización por Conflictos**: Para probar si un plan es serializable por conflictos se usa un **grafo de precedencia o grafo de serialización**."
> "**Pasos Generales**: 1. Crear la estructura de grafo a partir de la planificación concurrente de transacciones. 2. Algoritmo para verificar si se arma al menos un ciclo dentro del grafo. 3. Caso que no haya ciclos, algoritmo debe indicar al menos una planificación secuencial equivalente."
> Ejemplos resueltos: *"Hay un ciclo => No es serializable"* (`:650`) y *"Planificación secuencial equivalente"* (`:696`).

**(d) Técnicas de control de concurrencia** (`:749-1003`):

> "El objetivo es garantizar que la ejecución de un conjunto de transacciones sea serializable: **Bloqueos / Marcas de tiempo / Validación**. **Pesimistas**: garantizan la seriabilidad antes de la ejecución. **Optimistas**: se ejecutan y luego se verifica."
> "**Técnicas de Bloqueo** — El bloqueo regula el acceso concurrente a objetos compartidos (buffer de datos). **Granularidad**: pueden aplicarse a diferentes unidades de dato: **Base de datos / Tabla / Registro / Campo**. **Grano más fino** → Mayor concurrencia → **Mayores posibilidades de interbloqueo** → Más costos de manejo de concurrencia."
> Protocolos: **PX** (Bloqueo Exclusivo) `:789-826`, **PS** (Bloqueo Compartido) `:829-914`, **PU** (Bloqueo de Actualización) `:918-976`. Cada uno con su **colas de espera**: *"Cola de espera de bloqueo exclusivo"* `:844`, *"Cola de espera de bloqueo de actualización"* `:934`.
> "Algoritmo para bloqueo exclusivo / Algoritmo para bloqueo compartido / **Algoritmo de desbloqueo**" (`:978-995`) — con la pregunta guía *"¿Cómo modificamos este algoritmo para incluir el caso de bloqueo con protocolo PU?"*
> "El problema de las técnicas de bloqueo es que puede producirse un **interbloqueo o bloqueo mortal**. Esto es cuando dos o más transacciones están esperando cada una de ellas que la otra libere algún objeto antes de seguir." (`:999-1003`) — y el slide anterior muestra el interbloqueo (`:953`) en el protocolo PU: `T1 SREAD(R) … T2 SREAD(R) … XWRITE(R) wait … XWRITE(R) wait → Interbloqueo (deadlock)`.

**(e) 2PL — material complementario y de la semana 01.** La semana 05 no dibuja "2PL" con ese nombre, pero la **semana 01 sí** (`semana01_teoria_arquitectura_SGBD.txt:554-557`: *"Protocolo 2PL (Two-Phase Locking): fase de crecimiento / fase de decrecimiento"*), y el material de consolidación del propio curso lo desarrolla: `04_conocimiento_optimo\03_semana05_optimo.md:235-249` y `02_conocimiento\semana05_conocimiento.md:610-617`:

> "**2PL básico** — Fase de **crecimiento** (solo se piden bloqueos) y fase de **decrecimiento** (solo se liberan). Nunca se pide después de liberar. → **Serializabilidad por conflictos**. No garantiza ausencia de deadlock ni recuperabilidad."
> "**2PL estricto (strict 2PL)** — Todos los bloqueos **exclusivos (PX)** se retienen hasta el `COMMIT`/`ABORT`. → Serializabilidad **+ recuperabilidad** (evita lectura sucia y escritura sucia)."
> "**2PL riguroso (rigorous 2PL)** — **Todos** los bloqueos (PS y PX) se retienen hasta el `COMMIT`/`ABORT`."
> "**2PL conservador (conservative 2PL)** — Se piden **TODOS** los bloqueos antes de empezar. → Serializabilidad **+ AUSENCIA DE DEADLOCK**."
> ⚠️ *"2PL garantiza SERIALIZABILIDAD por conflictos, NO ausencia de deadlock. El único que evita el deadlock es el 2PL conservador."* (`02_conocimiento\semana05_conocimiento.md:1558`)

**(f) Laboratorio 05 — Concurrencia** (`semana05_lab_concurrencia.txt`). Contenido verificable del texto extraído:

> "**P1. Detección de problemas concurrentes**: Analizar los siguientes planes de transacciones y deducir qué problema de concurrencia puede ocurrir: **actualización perdida, dependencia no confirmada, lectura sucia y lectura no repetible**. Mostrar los valores del recurso compartido en cada instante de tiempo." (`:12-17`)
> "**P2**: Analice el siguiente plan… ¿Qué problema se presenta si se tiene que mantener la restricción A = B al finalizar?" (`:61-68`)
> "**P3. Grafo de Precedencia**: … indique usted si corresponde a una planificación serializable por conflictos usando el grafo de precedencia. Caso de no ser serializable, permute las instrucciones…" (`:85-103`)
> "**P4. Algoritmos**: a) Diseñe el algoritmo para verificar si una planificación es serializable por conflicto. Considere los tres pasos generales. b) **Diseñe el algoritmo de bloqueo para el protocolo de actualización.** c) **Diseñe el algoritmo de desbloqueo considerando el protocolo de actualización.**" (`:119-123`)
> "**P5–P7. DB Recovery**: checkpoints y UNDO/REDO, registro del log, estrategias de modificación **diferida e inmediata**." (`:124-173`)

> ⚠️ **Obsérvese:** el laboratorio de la semana 05 mezcla **concurrencia** (P1–P4) con **recovery** (P5–P7). Es material de clase, no del enunciado del proyecto.

### 6.2 Qué implementa el proyecto

**Archivos:** `transactions\lock_manager.py` (86 líneas), `transactions\transaction_manager.py` (48 líneas), `transactions\demo_concurrencia.py` (71 líneas), `tests\test_transactions.py` (54 líneas).

**(a) `LockManager` — PS/PX por recurso** (`lock_manager.py:10-30`):
```python
class _Recurso:
    def __init__(self):
        self.lectores = set()
        self.escritor = None
        self.cond = threading.Condition()

class LockManager:
    """Manejador de bloqueos compartidos (PS) y exclusivos (PX)."""
    TIMEOUT_SEGUNDOS = 2.0                                    # :19
    def __init__(self):
        self._recursos = {}
        self._lock_tabla = threading.Lock()
        self._locks_por_txn = {}
```
- **PS** (`:32-47`): compatible con otros lectores, incompatible con un escritor de otra transacción; reentrante para el mismo txn (`:37-39`).
- **PX** (`:49-68`): incompatible con cualquier otro lector y con otro escritor; **convierte** un PS propio en PX (`:66` `r.lectores.discard(txn_id)`).
- **Protocolo:** `release_all` (`:74-86`):
  ```python
  def release_all(self, txn_id):
      """Libera todos los bloqueos tomados por la transacción (Protocolo Strict 2PL)."""
  ```
  Se llama **solo** desde `commit`/`rollback` (`transaction_manager.py:38,47`) → **no hay fase de decrecimiento durante la transacción** → comportamiento de **2PL estricto/riguroso**.
- **Resolución de conflictos:** `while ... cond.wait(timeout=restante)` y `raise RecursoBloqueado` si vence (`:41-45,61-65`). **No hay `wait-for graph`, ni `wait-die`/`wound-wait`, ni orden de adquisición.**

**(b) `Transaction` — BEGIN/COMMIT/ROLLBACK + undo buffer** (`transaction_manager.py`):
```python
class Transaction:
    """Modela el ciclo de vida de transacciones (BEGIN / COMMIT / ROLLBACK)."""   # :8
    def __init__(self, tabla_compartida, lock_manager, usar_locks=True):
        self.id = f"T{next(_contador_txn)}"        # :10  ← BEGIN TRANSACTION (identidad)
        self._undo_buffer = {}                     # :15
    def leer(self, clave, modo="compartido"):
        if modo == "exclusivo": self.locks.acquire_exclusive(self.id, clave)
        else:                   self.locks.acquire_shared(self.id, clave)
        return self.tabla[clave]                   # :17-23
    def escribir(self, clave, nuevo_valor):
        if self.usar_locks: self.locks.acquire_exclusive(self.id, clave)
        if clave not in self._undo_buffer:
            self._undo_buffer[clave] = self.tabla[clave]   # :29-30  ← imagen ANTES
        self.tabla[clave] = nuevo_valor                     # :32
    def commit(self):
        self._undo_buffer.clear(); self.locks.release_all(self.id)   # :36-38
    def rollback(self):
        for clave, valor_anterior in self._undo_buffer.items():
            self.tabla[clave] = valor_anterior                          # :43-44
        self._undo_buffer.clear(); self.locks.release_all(self.id)      # :45-47
```
→ `_undo_buffer` guarda **imágenes "antes"** en memoria y `rollback` las restaura: es el **UNDO** de la clase (`semana05_teoria_...txt:1182-1194`: *"Deshacer transacción: Acción de colocar las imágenes antes (estado anterior) de los registros modificados por una transacción"*), **pero en RAM y sin log en disco**.

**(c) Demo con hilos** (`demo_concurrencia.py:20-40`): dos hilos T1 (`X = X - 10`) y T2 (`X = X + 100`) sobre `X = 100`; `time.sleep(0.05)` (`:11`) fuerza el cruce de hilos; `esperado = 100 - 10 + 100 = 190` (`:39`). Sin locks el resultado varía; con PX es 190. **Reproduce exactamente el ejemplo de "Actualización perdida" del slide** (`semana05_teoria_...txt:194-330`), sólo que el slide da 90/90 como resultado perdido.

**(d) Integración con el motor: NO EXISTE.** Búsqueda global de `from transactions|import transactions|transaction_manager|LockManager` → **solo** coincidencias en `transactions\*.py` y `tests\test_transactions.py`. Ni `backend\engine.py`, ni `backend\api.py`, ni `query\query_executor.py` ni `query\catalog.py` importan el módulo de transacciones. Y `backend\engine.py:69`:
```python
self._lock = threading.Lock()  # el motor no es thread-safe: serializamos
```
`DemoEngine.run()` (`:110-112`) toma ese mutex global antes de ejecutar **cualquier** sentencia.

### 6.3 Veredicto

| Elemento | Veredicto | Justificación / acción |
|---|---|---|
| PS (compartido) y PX (exclusivo) | **ALIGNED** | `lock_manager.py:32-68` vs `semana05_teoria_...txt:789-914`. Nombres idénticos a los de clase. |
| BEGIN / COMMIT / ROLLBACK con `undo_buffer` | **ALIGNED** | `transaction_manager.py:8-48` vs `.enunciado.txt:37` y `semana05_teoria_...txt:42-95` |
| Protocolo **2PL estricto** (todos los locks hasta COMMIT/ROLLBACK) | **ALIGNED** | `lock_manager.py:74-86` — declarado en el docstring y consistente con `04_conocimiento_optimo\03_semana05_optimo.md:245` |
| Granularidad de bloqueo por **registro/clave** | **ALIGNED** | `lock_manager.py:26-30` vs `semana05_teoria_...txt:775-784` |
| Demostración con hilos de *race condition* y su resolución | **ALIGNED** | `demo_concurrencia.py` vs `.enunciado.txt:39-42` y `semana05_teoria_...txt:194-330` |
| **Fase de crecimiento explícita (2PL)** | **ALIGNED DE COMPORTAMIENTO, NO EXPLÍCITA** | (a) *"No hay una bandera de fase porque solo liberamos en COMMIT/ROLLBACK, así que la fase de decrecimiento coincide con el fin de la transacción; eso es 2PL estricto."* ⚠️ Si se pide "muéstrame el crecimiento", responder con el orden de `acquire_*` antes de `release_all`. |
| **Detección de deadlock con `wait-for graph`** | **DEVIATES** | (b) **riesgo real**: la semana 01 lo pide con ese nombre (`semana01_teoria_arquitectura_SGBD.txt:551-553`). Frase: §1.2.8. **Acción P1 (barata, ~25 líneas, muy vistosa):** mantener un `dict` `espera[txn] = [txn_bloqueantes]` al bloquearse y al liberar, y exponer `detectar_ciclo()` con un DFS; usarlo en `demo_concurrencia.py` para imprimir un ciclo real. Convierte el punto más débil de la semana 05 en una demo. |
| **Protocolo PU (bloqueo de actualización)** | **NOT COVERED** | El laboratorio P4 pide *"Diseñe el algoritmo de bloqueo/desbloqueo para el protocolo de actualización"* (`semana05_lab_concurrencia.txt:119-123`) y la clase lo desarrolla (`:918-976`). Frase: *"Implementamos los protocolos PS y PX, que cubren el requisito del enunciado ('implementa algún mecanismo de bloqueo'); el PU de la diapositiva es la variante que evita el deadlock del caso SREAD→XWRITE y lo tenemos identificado como extensión."* |
| **Cola de espera FIFO por recurso** | **NOT COVERED / simplificado** | (a) `notify_all` sin orden. Frase: §1.2 lista, punto 11 de cambios. Declararlo como limitación. |
| **Grafo de precedencia / verificación de serializabilidad** | **NOT COVERED** | El laboratorio P3/P4 lo pide (`:85-123`). No hay código. Frase: *"El grafo de precedencia lo resolvimos a mano en el laboratorio; el motor no lo verifica en runtime porque implementamos bloqueo pesimista, que garantiza la serializabilidad por construcción en vez de comprobarla a posteriori."* (Esta frase es **correcta** según la clase: *"Pesimistas: Garantizan la seriabilidad antes de la ejecución"*, `:761-767`.) |
| **Transactionalidad sobre el almacenamiento real** | **DEVIATES (mayor)** | `Transaction` opera sobre un `dict` en memoria (`transaction_manager.py:23,30,32`), **no** sobre `HeapFile`/`SequentialFile`/índices. Y el motor web **serializa con un mutex global** (`engine.py:69`). Frase: *"El módulo de transacciones es la capa de control de concurrencia pedida en 2.1.4 y se demuestra con hilos sobre un recurso compartido; el API web serializa las peticiones con un mutex porque las operaciones de archivo no son atómicas a nivel de storage, y lo declaramos explícitamente en el README."* **Acción P1:** integrar `Transaction` en `Catalog`/`query_executor` para `BEGIN/END` desde SQL, o al menos documentarlo como limitación explícita (hoy el README dice "✅ Completo" sin matices: `README.md:63`). |
| **Recuperación (P5–P7 del laboratorio)** | **NOT COVERED** | Ver §9. |

---

## 7. Semana 06 — Bases de Datos Espaciales (GiST / R-Tree / PostGIS)

### 7.1 Qué enseña la clase

Fuente: `week_06\07 BD Espaciales - GiST - Rtree.pdf` → `semana06_teoria_espacial_gist_rtree.txt`; laboratorio `week_06\Laboratorio 06 - PostGIS.pdf` → `semana06_lab_postgis.txt`.

**(a) R-Tree** (`:979-1034`, `:1122-1262`):

> "**El R-Tree es un índice espacial jerárquico que organiza objetos geométricos (puntos, líneas, polígonos) mediante rectángulos mínimos (MBR) para facilitar búsquedas espaciales eficientes.** Cada rectángulo representa un nodo o entrada en el árbol. Los nodos internos agrupan elementos espacialmente cercanos para mejorar la eficiencia de búsqueda."
> "Es ampliamente utilizado en Sistemas de Información Geográfica (GIS), motores de bases de datos como **PostgreSQL (con PostGIS)**, Oracle Spatial…" — referencia: *A. Guttman. R-trees: A dynamic index structure for spatial searching. ACM SIGMOD 1984.*
> "Es un **árbol balanceado similar a un B-Tree**. Garantiza que puntos cercanos se almacenen en lo posible en la misma página de datos o subárbol. **Regiones de páginas jerárquicamente organizadas siempre deben estar contenidas completamente [unas en otras]**."
> "**MBR: Minimum Bounding Rectangle**" y la condición de poda: *"**¿MBR intersects with Query Region?**"* / *"**MINDIST(Q, MBR) <= radio**"* (`:1262-1302`).

**(b) MINDIST** (`:1499-1720`): definición y ejercicios: *"Calcule el MINDIST entre Q y el MBR formado por los puntos… MBR={(3,1), (6,7)}"*, y el tratamiento del empate *"MINDIST(Y, P1) = MINDIST(Y, P2)"*.

**(c) GiST** (`:377-406`, y teoría de la semana 04 `semana04_teoria_bitmap_external.txt:602-625`): *"GiST (Generalized Search Tree): Soporta múltiples tipos de consultas: igualdad, rango, proximidad. Índices para datos espaciales (PostGIS), texto completo, etc. Estructura de árbol balanceado como B-Tree. Flexible y extensible mediante operadores personalizados. **Soporta estructuras como R-Tree y Inverted Index.**"*

**(d) Haversine** (`:333`) y el laboratorio de **PostGIS** (`semana06_lab_postgis.txt`, 7994 bytes): consultas espaciales en PostgreSQL.

### 7.2 Qué implementa el proyecto

**NADA.** `grep -E "r_tree|rtree|RTree|haversine|Haversine|GiST"` sobre todo el proyecto → **0 coincidencias** en código. Solo hay una mención en el roadmap:
> `README.md:665`: "**2. Base de datos espacial** | Puntos 2D (latitud, longitud), consultas por rango, k-NN, intersección con polígonos, Euclidiana y Haversine, panel de mapa | `indexes/rtree.py`, extensión del parser para `distancia(...)` y `POINT(...)`"

El parser no reconoce `POINT(...)` ni `distancia(...)`: `sql_parser.py:575-600` (`_normalize_type`) sólo admite `INT/FLOAT/VARCHAR`, y `SUPPORTED_PREDICATE_OPERATORS` (`query_planner.py:5-7`) sólo tiene `= == < <= > >= between != <>`.

### 7.3 Veredicto

**NOT COVERED IN THE PROJECT — fuera del alcance de la Parte 1 (es la Parte 2 del enunciado, entrega semana 8).**

- **No es un riesgo hoy**, porque el enunciado fecha la Parte 2 en la **semana 8** (`.enunciado.txt:133-135`) y la Parte 1 se cierra en la semana 6.
- **Sí es un riesgo de comunicación:** el README declara *"2.1.x ✅ Completo"* y deja lo espacial sólo en el roadmap. Si el profesor pregunta "¿dónde está lo espacial?", la respuesta es: *"Es la Parte 2 y la planificamos para la semana 8; el índice previsto es un R-Tree con MBR y poda por MINDIST(Q, MBR) ≤ radio para rango y k-NN, más Haversine para distancia geodésica, tal como vimos en la semana 06; hoy no hay código."* Añadir esa frase al informe evita que parezca un olvido.
- **Nota útil para cuando lo implementen:** reutilizar el esqueleto de `bplus_tree.py` (nodos con `children`, split por `(len+1)//2`, `validate()` con hojas a la misma profundidad) hace que el R-Tree sea ~150 líneas y que las invariantes de Guttman queden verificables igual que las del B+.

---

## 8. Semana 07 — Bases de Datos Vectoriales / Recuperación de Información Textual

### 8.1 Qué enseña la clase

Fuente: `week_07\07 BD Vectorial - Recuperación de Información Textual 1.pdf` → `semana07_teoria_vectorial_ir.txt` (2223 líneas).

**(a) Índice invertido con postings** (`:2203-2218`) — el slide final muestra la estructura concreta:

> "**Índice Invertido con Similitud de Coseno**
> Term | Posting List
> casa | `[1: 1, 2: 1, 3: 2, 4: 1]`
> grande | `[1: 1, 3: 2]`
> gato | `[2: 1]`
> bonita | `[3: 1]`
> sol | `[1:2, 4: 2]`
> brilla | `[4: 3]`"

→ posting list = lista de `(doc_id: tf)`.

**(b) TF-IDF y similitud de coseno** (`:866`: "TF-IDF & Similitud de Coseno"; `:1248`, `:1398`, `:1488-1669`):

> "**De ángulos a cosenos**… El coseno es una función **monótonamente decreciente** para el intervalo [0°, 180°]" (`:1488-1502`)
> "**Calculo de la proximidad: Similitud de Coseno**" (`:1669`)

**(c) Recuperación booleana / operaciones sobre postings** (`:2195-2199`): ejemplo resuelto con intersección de listas → `Result: [3]`.

> ⚠️ **Observación importante:** en el texto extraído de este PDF **no aparecen** las cadenas `SPIMI` ni `BM25`. El título del PDF es *"Recuperación de Información Textual **1**"*, lo que sugiere que **SPIMI y BM25 son la segunda parte** de la clase (o están en el laboratorio). El enunciado del proyecto sí los exige: *"utilizando **SPIMI** (Single-Pass In-Memory Indexing) para el índice invertido. Implementa dos técnicas de ranking: **TF-IDF + Similitud del Coseno** y **BM25**"* (`.enunciado.txt:76`). **El equipo debe confirmar con el profesor que SPIMI/BM25 se dictaron**, porque de las 7 semanas de material entregado TF-IDF + coseno sí está y BM25 no.

### 8.2 Qué implementa el proyecto

**NADA** para texto. `grep -E "spimi|SPIMI|bm25|BM25|tf_idf|tfidf"` sobre todo el proyecto → **0 coincidencias**. Solo el roadmap:
> `README.md:666`: "**3. Búsqueda de texto** | Índice invertido con SPIMI, ranking TF-IDF + coseno y BM25, extensión `MATCH(...) USING` | `text/spimi.py`, `text/ranking.py`"

El parser no reconoce `MATCH(...)`: `_parse_select`/`_extract_select_clauses` (`sql_parser.py:158-250`) solo manejan `SELECT/FROM/WHERE/GROUP BY/ORDER BY/JOIN/LIMIT`.

### 8.3 Veredicto

**NOT COVERED IN THE PROJECT — fuera del alcance de la Parte 1 (es la Parte 3, entrega semana 12).**

- Frase de defensa: *"Es la Parte 3 del proyecto, planificada para la semana 12; la estructura prevista es un índice invertido construido con SPIMI —que es la versión con memoria acotada del índice que construimos en clase con posting lists `(doc_id: tf)`— y el ranking con TF-IDF + coseno y BM25, tal como aparece en la semana 07."*
- **Punto de cuidado:** si el profesor criticó "código que no podemos explicar", aquí el riesgo es el inverso: **Partes 3/4 mencionadas en el README pero sin una sola línea implementada**. Conviene que el README/roadmap diga explícitamente *"no iniciado"* en lugar de listar archivos previstos (`text/spimi.py`) que no existen, para que no parezca código escrito por otros.

---

## 9. Sección especial — Recuperación ante fallos / logging: ¿falta?

### 9.1 Respuesta directa

**SÍ, FALTA POR COMPLETO.** No hay **ni una línea** de recuperación, logging, WAL, checkpoints, UNDO/REDO en disco, backups ni replicación en el proyecto.

**Evidencia (búsqueda exhaustiva, no impresionista):**

| Búsqueda (`grep`) sobre `C:\Users\illes\Documents\Proyecto-BD2` | Resultado |
|---|---|
| `WAL\|write_ahead\|write-ahead\|log_file\|logfile\|recovery\|checkpoint\|undo_log\|redo` en `*.py` | **0 coincidencias** |
| `WAL\|write-ahead\|recuperaci\|recovery\|checkpoint` en `*.md` | **3 coincidencias**, y las tres son irrelevantes: `docs\conclusiones_experimentales.md:205` habla de *"esa recuperación es un `dict` en memoria"* (recuperación de un RID, no recovery de BD), y `README.md:666-667` son las filas del roadmap de texto/multimedia |
| Archivos de log en disco | **ninguno**: `backend\data\` sólo contiene `alumnos.dat`, `alumnos.dat.free`, `catalog.json`, `departments.dat`, `departments.dat.free`, `employees.aux`, `employees.main`, `users.dat`, `users.dat.free` |
| Módulos de transacciones | `transaction_manager.py` (48 líneas) y `lock_manager.py` (86 líneas). **No hay `log_manager.py` ni `recovery_manager.py`.** |
| Durabilidad real | El `commit()` de `Transaction` (`transaction_manager.py:34-39`) sólo limpia el `_undo_buffer` y libera locks; **no fuerza nada a disco**. Y opera sobre un `dict` en memoria. |

**Es decir: el proyecto no tiene Durabilidad (la "D" de ACID) ni Atomicidad persistente.** Si el proceso muere tras un `COMMIT`, no hay nada que rehacer; si muere a mitad de una transacción, no hay nada que deshacer.

### 9.2 Qué exige realmente cada fuente (para no sobre-exigir ni excusar de más)

**(a) El enunciado del proyecto — Parte 1, sección 2.1.4** (`.enunciado.txt:35-42`) pide **sólo**:

> "**Transacciones**: soporta **BEGIN TRANSACTION** y **END TRANSACTION** para agrupar operaciones.
> **Control de Concurrencia**: implementa algún mecanismo de bloqueo (locks) o control de concurrencia.
> **Demostración obligatoria**: crea una simulación con hilos (threads) donde se vea: múltiples transacciones ejecutándose simultáneamente, situaciones de race condition (competencia por recursos) y cómo tu sistema las maneja correctamente."

→ **El enunciado NO pide recuperación, WAL ni ARIES.** El equipo **cumple** 2.1.4 en lo que el enunciado pide (BEGIN/END + locks + demo con hilos).

**(b) La clase sí lo enseña, y en dos semanas distintas:**

- **Semana 01** (`semana01_teoria_arquitectura_SGBD.txt:510-604`): el **Transaction Manager** tiene como subcomponentes el **Log Manager (WAL)** (*"cada cambio se escribe en el log ANTES de ir a disco… Force-the-Log rule: el log se sincroniza (fsync) en cada COMMIT"*) y el **Recovery Manager** (*"REDO… UNDO… Checkpoints limitan cuánto log hay que releer"*), y el principio WAL con sus 5 pasos.
- **Semana 05** (`semana05_teoria_recuperacion_fallos.txt:1007-1600`): toda la segunda mitad de la clase, titulada **"2. Database Recovery"**, con: tipos de falla (`:1071-1104`), *"Registro de Log… secuencia de eventos que documentan cada operación crítica (INSERT, UPDATE, DELETE)"* (`:1107-1123`), **estructura de los registros de Log** (`:1127-1139`):
  > "Inicio de la transacción Ti: `<Ti, BT>` / Fin: `<Ti, ET>` o `<Ti, Commit>` … o `<Ti, Abort>` / **Cambios en los registros de la BD: `<Ti, X, IA, ID>`** … **IA: Imagen o estado antes de la modificación. ID: imagen o estado después de la modificación.**"
  
  **Estrategias de modificación** (`:1198-1221`): *"**Modificación inmediata**: Permite las operaciones WRITE de una transacción mientras ésta está activa… **Se realizan los cambios en el Log antes de la actualización real a la BD**"* vs *"**Modificación diferida**: Retarda las operaciones WRITE… **En el Log no se registra las imágenes antes**, por lo que los registros son `<Ti, X, ID>` y **no se deshace**"*. **Proceso de recuperación de tres pasadas** (`:1223-1259`) y **dos pasadas** (`:1270-1277`), **checkpoints** (`:1292-1586`) con el algoritmo de 5 pasos (`:1458-1477`):
  > "1. Se obtiene en el archivo de recomienzo la dirección del último CP en el Log. 2. Se crean dos listas `UNDO = L`, `REDO = []`. 3. Se recorre el Log desde el CP al final y se completan las listas. 4. Se recorre el Log desde el final hasta el inicio de c/u de las transacciones en UNDO para deshacer. 5. Se recorre el Log desde el CP hasta el final para rehacer."
  
  Y **Backups / Replicación** (`:1587-1600`).
- **El Laboratorio 05 incluye 3 problemas de recovery** (P5, P6, P7 — `semana05_lab_concurrencia.txt:124-173`), incluyendo *"Aplique el proceso de recuperación utilizando la estrategia **UNDO/REDO**"* y *"según las diferentes estrategias de modificación, **diferida e inmediata**"*.

**(c) Coincidencia con el índice del `README.md`:** el proyecto declara `transactions/` como *"BEGIN/END, LockManager"* (`README.md:118`) y *"✅ Completo"* (`:63`) — **sin mencionar recovery en ningún lado**.

### 9.3 Cómo cerrar este hueco (3 opciones, ordenadas por coste/beneficio)

**Opción A — Documentar (coste: 15 minutos; obligatorio).** Añadir al README (sección 7.5) y al informe incremental:

> "**Alcance de la Parte 1 y recuperación:** el enunciado (2.1.4) exige `BEGIN/END TRANSACTION`, un mecanismo de bloqueo y una demostración con hilos, y eso es lo que implementa `transactions/`. La **recuperación ante fallos** (Write-Ahead Log `<Ti, X, IA, ID>`, estrategias de modificación inmediata/diferida, proceso de recuperación de dos/tres pasadas con checkpoints, UNDO/REDO) es material de clase de las semanas 01 y 05 y **no forma parte del alcance de la Parte 1**; el motor actual no ofrece Durabilidad real: `Transaction.rollback()` deshace con un *undo buffer* en memoria y `commit()` no fuerza nada a disco. Es el primer ítem del roadmap posterior a la Parte 1."

Y en la defensa decirlo **antes** de que lo pregunten. Un hueco declarado es una decisión de alcance; un hueco descubierto es una omisión.

**Opción B — WAL mínimo (coste: ~120 líneas; muy recomendable si hay tiempo antes de la entrega).** Añadir `transactions\log_manager.py`:
1. `append_begin(txn)`, `append_update(txn, key, ia, id)`, `append_commit(txn)`, `append_abort(txn)` escribiendo líneas `Ti,BT` / `Ti,X,IA,ID` / `Ti,Commit` / `Ti,Abort` en `data\wal.log` con `flush()` + `os.fsync()` en el `COMMIT` (**force-the-log rule**, `semana01_teoria_arquitectura_SGBD.txt:563-566`).
2. En `Transaction.escribir`, escribir el registro `<Ti, X, IA, ID>` **antes** de mutar el valor → **modificación inmediata** (`semana05_teoria_...txt:1199-1208`).
3. `recovery_manager.py` con `undo_redo()`: recorrer el log del final al inicio para armar `REDO` (transacciones con `<Ti, Commit>`) y `UNDO` (sin Commit), rehacer desde el inicio y deshacer desde el final → **dos pasadas** (`:1270-1277`). Imprimir las dos listas.
4. Un test que: corre la demo, mata el proceso antes del `COMMIT`, reinvoca la recuperación y comprueba el valor final.

Con eso, el equipo puede **mostrar el log y las listas UNDO/REDO** y responde cualquier pregunta de la semana 05 (incluido *"¿qué diferencia hay entre modificación diferida e inmediata?"*).

**Opción C — Checkpoints (coste: +60 líneas sobre B).** Añadir `checkpoint(activas)` que escribe `<CP, L>` con la lista de transacciones activas, fuerza la salida de los buffers y anota el puntero en un archivo de recomienzo. Con eso se cubre el algoritmo de 5 pasos del slide (`:1458-1477`).

**Recomendación:** A **ahora** (es obligatorio para la defensa) y B+C si queda tiempo. Si el equipo implementa B, este módulo pasa de ser el mayor riesgo a ser **la mejor demo del proyecto**.

---

## 10. Tabla final: componente → clase vs proyecto → veredicto → frase de defensa

Leyenda: **A** = ALIGNED · **AS** = ALIGNED BUT SIMPLIFIED · **D** = DEVIATES (justificable, etiqueta *(a)*) · **R** = DEVIATES (riesgo real *(b)*) · **NC** = NOT COVERED.

| # | Componente | Qué dice la CLASE (fuente) | Qué hace el PROYECTO (archivo:línea) | Veredicto | Frase de defensa de una línea |
|---|---|---|---|---|---|
| 1 | RID | *"RID = (page_id, slot_number)"* (`sem01_teo:505`) | `RID(page, slot)` `heap_file.py:7-24` | **A** | «El RID es la tupla (page_id, slot_id) que define la clase: identificador físico único, estable ante compactación.» |
| 2 | Layout de página | *"Header (24 bytes) + ItemId Array + tuplas"* (`sem01_teo:490-506`); Lab 02: header con n total, n activos, puntero al 1.er eliminado (`sem02_lab:95-113`) | Sin header; `PAGE_SIZE//record_size` slots contiguos `heap_file.py:42` | **R** | «Nuestra página es el bloque de longitud fija de `Fijo2.py` sin cabecera: los metadatos de espacio libre (qué páginas tienen huecos) viven en el archivo auxiliar `.free`, el mismo patrón de `Variable1.py`, y el header de página con n activos y puntero al primer eliminado está identificado como el siguiente ajuste.» |
| 3 | Tamaño de página | *"páginas (bloques de igual tamaño)"* (`sem02_teo:111-118`) | Declara 4096 B; página efectiva 4047/4087 B `heap_file.py:4,56` | **D (a)** | «Declaramos PAGE_SIZE=4096 y la página efectiva es `(4096//record_size)*record_size` porque no partimos registros entre bloques; para `users` son 4047 B y para `departments` 4087 B, exactamente el tamaño de los archivos.» |
| 4 | `read` por RID | *"O(1) sin recorrer secuencialmente todo el archivo"* (`sem02_lab:147-157`) | `_offset = page*page_bytes + slot*record_size` `heap_file.py:60-61,134-140` | **A** | «La lectura por RID es O(1): una aritmética de offset y un `seek`, sin scan.» |
| 5 | Reutilización de espacio (heap) | Free List: *"El header almacena la dirección del primer registro eliminado… lista enlazada"* (`sem02_teo:1801-1841`) | Tombstone por registro + set de páginas en `.free` (pickle) `heap_file.py:43,116-121,148-149` | **AS** | «Reutilizamos el primer slot libre, con borrado lógico y un free list de páginas en `.free` —el patrón de archivo-índice-auxiliar de `Variable1.py`—; no es una lista enlazada con punteros dentro de la página.» |
| 6 | Segunda estrategia de borrado | Lab 02 pide **MOVE THE LAST** *y* **FREE LIST** (`sem02_lab:115-131`) | Solo free list por tombstone | **NC** | «El enunciado pide *una* estrategia de reutilización de espacios libres y esa es la que implementamos; MOVE THE LAST es la otra política del laboratorio y la descartamos porque implicaría mover el último registro de la página y reescribir su RID.» |
| 7 | Registros de longitud variable / Slotted Page | *"ItemId Array contiene (offset, length)… registros desde el final hacia el inicio"* (`sem02_teo:2075-2104`); Lab 02 Parte 2 | Todo longitud fija; `TEXT` → `VARCHAR(255)` `record.py:41`, `sql_parser.py:595` | **AS** | «Nuestro subconjunto de tipos es INT/FLOAT/VARCHAR(n) acotado, así que usamos el layout de longitud fija de `Fijo2.py`; el Slotted Page con slot directory (offset,length) del laboratorio queda como extensión porque no hay campos de tamaño variable.» |
| 8 | Archivo Secuencial: overflow | *"Estrategia del Overflow File (1)… la búsqueda debe realizarse en ambos espacios… reconstruido periódicamente"* (`sem02_teo:2562-2576`) | `.main` + `.aux`; busca binario en main, lineal en aux `sequential_file.py:24-25,90-129` | **A** | «Es la estrategia de overflow de la clase: `.main` ordenado con búsqueda binaria, `.aux` como zona de desbordamiento, y búsqueda en ambos espacios.» |
| 9 | Umbral de reorganización | Enunciado: *">30 % de espacio desperdiciado"* (`.enunciado:20`); clase: *"Cuando el overflow crece demasiado se reconstruye"* (`sem02_teo:2854`) | `REORG_AUX_RATIO = REORG_WASTE_RATIO = 0.3` `sequential_file.py:3-4,199-210` | **A** | «Reorganizamos cuando el área auxiliar o los tombstones superan el 30 % del archivo principal, el umbral que fija el enunciado.» |
| 10 | Búsqueda en el secuencial | *"El costo NO se mide en registros comparados sino en accesos a bloque: ⌈log2 b⌉"* (`sem02_teo:2480-2513`) | Búsqueda binaria real `sequential_file.py:90-111` | **A** | «La búsqueda es binaria sobre el archivo ordenado, con el costo ⌈log2 b⌉ accesos de página de la clase.» |
| 11 | Range scan del secuencial | *"Range queries eficientes: recorren solo el rango físico contiguo"* (`sem02_teo:2523-2524`) | Recorre todo y hace `sort` en memoria `sequential_file.py:147-164` | **D (b menor)** | «Hoy el rango recorre ambos archivos y ordena en memoria; el siguiente paso es localizar el extremo inferior con la búsqueda binaria y leer secuencialmente, aprovechando el orden físico.» |
| 12 | Reorganización → RIDs | Clase: reconstrucción periódica (`sem02_teo:2860-2863`) | `reorganizar()` reescribe `.main` → `rebuild_indexes()` en cada insert secuencial `query_executor.py:266-273` | **R** | «Reorganizar invalida todos los RID, así que reconstruimos los índices; hoy lo hacemos en cada inserción a una tabla secuencial y es O(n) —lo vamos a condicionar a que el contador de reorganizaciones haya cambiado.» |
| 13 | B+ Tree: propiedades | *"Hojas al mismo nivel, enlazadas, nodos al menos a la mitad"* (`sem03_teo:491-512`) | `min_leaf_keys=⌈(order-1)/2⌉`, `min_internal_children=⌈order/2⌉`, hojas `next/prev`, `validate()` verifica las tres `bplus_tree.py:24-34,93-97,308-372` | **A** | «Las tres propiedades están implementadas y verificadas por `validate()`: hojas a la misma profundidad, mínimo ⌈FB/2⌉ entradas y hojas enlazadas.» |
| 14 | B+ Tree: split | *"dividir el nodo y actualizamos el nodo padre (actualización en cascada)"* (`sem03_teo:733`) | `_split_leaf` y `_split_internal` con `(len+1)//2` y cascada `bplus_tree.py:84-150` | **A** | «El split parte el nodo por la mitad y propaga en cascada el nuevo separador, que en las hojas se copia hacia arriba y en los internos se recalcula como la primera clave del subárbol.» |
| 15 | B+ Tree: merge/redistribución | *"Si encajan, fusione; si no, redistribuya; actualice la clave en el padre"* (`sem03_teo:739-749`) | `_rebalance_leaf` rota desde el hermano con holgura o fusiona; `_rebalance_internal` idem; `_after_child_removed` en cascada `bplus_tree.py:183-273` | **A** | «Aplicamos exactamente la política de la clase: redistribuir con el hermano que tenga más del mínimo y, si no alcanza, fusionar y actualizar el padre en cascada.» |
| 16 | B+ Tree: rango | *"Aproveche el enlazado entre hojas… sin volver a descender"* (`sem03_lab:694-696`) | `range_search` baja una vez y recorre `leaf.next` `bplus_tree.py:275-306` | **A** | «El rango baja al extremo inferior y recorre las hojas enlazadas sin volver al árbol, exactamente como pide el laboratorio.» |
| 17 | B+ agrupado | *"En InnoDB las hojas contienen el registro completo (índice en árbol = tabla)"* (`sem03_teo:586`) | `tree.insert(key, deepcopy(record))` `clustered_bplus.py:40` | **A** | «Nuestro B+ agrupado guarda el registro completo en la hoja, como el índice agrupado de InnoDB, y por eso el planner puede evitar el External Sort en el ORDER BY.» |
| 18 | B+ no agrupado | *"Las hojas apuntan a direcciones físicas… no contienen los registros completos"* (`sem03_lab:666`) | `tree.insert(key, rid)` `unclustered_bplus.py:47` | **A** | «El B+ no agrupado es denso y guarda (clave, RID); el ejecutor resuelve el heap fetch con el RID.» |
| 19 | B+ en disco | *"optimizados para E/S de disco… minimizan los accesos"* (`sem03_teo:410-419`); Lab 03 pide el análisis de accesos | Todo en memoria (objetos Python) | **R** | «Diseñamos la estructura y los algoritmos con su análisis de accesos —altura ⌈log_⌈FB/2⌉ M⌉— y verificamos las invariantes en `validate()`; la persistencia paginada del índice es el siguiente paso, y hoy el costo lo razonamos en número de nodos visitados.» |
| 20 | Hash: función de posición | `Bin(Key % 2^D)` (`sem03_teo:1339,1358,1379`) | `hash(key) & ((1<<global_depth)-1)` `extendible_hash.py:51-53` | **A** | «Usamos los D bits menos significativos del hash, que es exactamente `Key % 2^D`, la función del laboratorio.» |
| 21 | Hash: estado inicial | *"D inicia en 1… dos buckets (0 y 1)"* (`sem03_lab:187-190`) | `global_depth=1`, dos `_Bucket(local_depth=1)` `extendible_hash.py:32-37` | **A** | «Arrancamos con profundidad global 1 y dos buckets, como fija el laboratorio.» |
| 22 | Hash: split y crecimiento | *"Si el bucket está lleno, dividir y reinsertar… d=d+1… el directorio es modificado… D=D+1"* (`sem03_teo:1533-1569`) | `_double_directory` + `_split_bucket` con rehash completo `extendible_hash.py:116-161` | **A** | «Si el bucket se llena, duplicamos el directorio si `d == D` y repartimos dividiendo por el siguiente bit y reinsertando todas las claves.» |
| 23 | Hash: fusión y reducción | *"Si dos buckets tienen poco elementos y el mismo prefijo (d-1), mezclar"* (`sem03_teo:1583-1587`); Lab 03 pregunta por *"fusión de buckets, reducción del directorio"* (`sem03_lab:205-207`) | `_try_merge` con buddy `^ (1<<(d-1))`; `_shrink_directory` `extendible_hash.py:198-268` | **A** | «Fusionamos buckets *buddy* con la misma profundidad local cuando la suma de claves cabe, y reducimos la profundidad global cuando las dos mitades del directorio son equivalentes.» |
| 24 | Hash: sin rangos | *"No soporta búsqueda por rango"* (`sem03_teo:1603`) | `items()`/`keys()` sin orden garantizado `extendible_hash.py:270-275` | **A** | «El hash extendible sólo sirve para igualdad exacta; el planner nunca lo propone para rangos ni para ORDER BY.» |
| 25 | Hash: capacidad | *"Factor de bloque: 3"* (`sem03_teo:1340`); Lab 03 FB=3 (`sem03_lab:184-190`) | `bucket_capacity` cuenta **claves distintas** `extendible_hash.py:102` | **AS** | «El factor de bloque lo contamos por entradas de índice (claves distintas) y los RIDs duplicados cuelgan en una lista de la clave; si el bucket se llena hacemos split, que es el algoritmo de Fagin.» |
| 26 | Hash: overflow encadenado | Lab 03: *"encadenamiento máximo N=1; si se supera, rehashing"* (`sem03_lab:194-196`) | No hay overflow; split recursivo `extendible_hash.py:91-107` | **D (a)** | «Implementamos el hashing extendible puro de la diapositiva —siempre divide y rehashea—, así que la rama de buckets de overflow del laboratorio nunca se alcanza.» |
| 27 | Hash en disco | Lab 03: *"cada bucket corresponde a un bloque de tamaño fijo persistido en un archivo binario, NO a una estructura únicamente en memoria"* (`sem03_lab:29-35`) | `_Bucket.records` es un `dict` `extendible_hash.py:4` | **R** | «El proyecto pide el hash **dinámico extendible**; el hash **estático paginado** del laboratorio es la técnica que el propio material presenta como deficiente y su cadena de overflow es innecesaria en nuestra variante porque siempre dividimos. Tenemos identificado paginar el directorio y los buckets como siguiente paso.» |
| 28 | External Sort: fases | *"Fase 1: Run Generation… Fase 2: Multiway Merging… B-1 buffers de entrada + 1 salida"* (`sem04_teo:171-190`) | runs ordenados en RAM → temporales → merge en pasadas con `fan_in` `external_sort.py:53-58,135-199` | **A** | «Es el Two-Phase Multiway Merge Sort: generamos ⌈N/M⌉ runs de `memory_limit_records` registros y los fusionamos con `fan_in` buffers de entrada, que es el B-1+1 del slide.» |
| 29 | External Sort: min-heap | *"seleccione el ID del término más bajo… utilizando un min-heap"* (`sem04_teo:276-279`) | `heapq.heappush(heap, (key, run_index, record))` `external_sort.py:276-298` | **A** | «El k-way merge usa un min-heap con un registro por run, exactamente como indica la diapositiva.» |
| 30 | External Sort: unidad de memoria | *"la memoria RAM asignada es ≤ 1 GB… B/M runs"* (`sem04_teo:149-181`) | `memory_limit_records` (registros, no páginas) | **AS** | «La unidad de memoria es el registro porque el operador trabaja sobre un iterable de tuplas; el modelo de páginas se conserva y `ExternalSortStats` reporta `initial_runs` y `merge_passes` para revisar el costo.» |
| 31 | External Hashing: 2 fases | *"Fase 1: Particionamiento con h_p y B-1 particiones… Fase 2: Construcción en RAM con h_r"* (`sem04_teo:342-377`) | `_partition_iterable` con `hash((depth,key))%partition_count` y `_group_partition` `external_hashing.py:557-584,169-180` | **A** | «Particionamos con h_p en `partition_count-1` buffers de salida y construimos la tabla hash en RAM con una segunda función por partición; si una partición no cabe, la reparticionamos.» |
| 32 | External Hashing: JOIN y DISTINCT | *"¿Como extender para join y distinct? misma función de hash sobre el atributo a… luego verificar coincidencias"* (`sem04_teo:451-515`) | `hash_join` con inner/left/right/full; `group_by`; `SUPPORTED_AGGREGATES` `external_hashing.py:38-39,68,251` | **A** | «La misma función de hash sobre la clave de join garantiza que las tuplas que empatan caigan en la misma partición; con eso implementamos inner, left, right y full, más GROUP BY con count/sum/min/max/avg.» |
| 33 | **Bitmap Index Scan** | *"construir un bitmap de páginas en memoria antes de leer el heap… AND/OR bit a bit… una pasada por el heap"* (`sem04_teo:23-139`) | **No existe**; el planner **rechaza** `kind="bitmap"` `query_planner.py:59-62`; el test lo verifica `test_query_planner.py:636-643` | **NC** | «No implementamos bitmap: el enunciado no lo pide y el problema que resuelve —evitar el heap random-access— lo paliamos devolviendo los RIDs del B+ no agrupado en orden de clave. Reconocería la técnica como el siguiente paso: un bit por página del heap e intersección AND/OR de dos bitmaps antes del fetch.» |
| 34 | BEGIN/COMMIT/ROLLBACK | *"BEGIN TRANSACTION… COMMIT… ROLLBACK"* (`sem05_teo:42-52`) | `Transaction.leer/escribir/commit/rollback` con `_undo_buffer` `transaction_manager.py:8-48` | **A** | «La transacción agrupa operaciones entre BEGIN y END; `commit` hace efectivos los cambios y `rollback` restaura las imágenes *antes* que guardamos en el undo buffer.» |
| 35 | Bloqueos PS/PX | *"Bloqueo Exclusivo (Protocolo PX)"*, *"Bloqueo Compartido (Protocolo PS)"* (`sem05_teo:791,832`) | `acquire_shared` / `acquire_exclusive` por recurso `lock_manager.py:32-68` | **A** | «Implementamos los protocolos PS y PX de la clase, con granularidad de registro: N lectores o 1 escritor, y conversión de PS a PX de la misma transacción.» |
| 36 | 2PL | *"Protocolo 2PL: fase de crecimiento / decrecimiento"* (`sem01_teo:554-557`); 2PL estricto retiene los X-locks (`sem05_conoc:614-617`) | `release_all` sólo en commit/rollback → 2PL estricto `lock_manager.py:74-86` | **A** | «Los bloqueos se liberan únicamente en COMMIT o ROLLBACK, así que la fase de decrecimiento coincide con el fin de la transacción: eso es 2PL estricto, que además evita lecturas sucias.» |
| 37 | Deadlock | *"Detecta deadlocks mediante un wait-for graph"* (`sem01_teo:551-553`); *"dos o más transacciones esperando… que la otra libere"* (`sem05_teo:999-1003`) | Timeout de 2 s → `RecursoBloqueado` `lock_manager.py:19,41-45,61-65` | **R** | «Prevenimos el interbloqueo con timeout en lugar de detectarlo con un wait-for graph: si en 2 s no se obtiene el lock, la transacción aborta y hace ROLLBACK, lo que rompe el ciclo de espera; el wait-for graph está en la lista de mejoras.» |
| 38 | Protocolo PU | *"Bloqueo Actualización (Protocolo PU)… Cola de espera"* (`sem05_teo:918-976`) | No existe | **NC** | «Cubrimos PS y PX, que es lo que pide el enunciado; el PU es la variante que evita el deadlock del caso SREAD→XWRITE y lo tenemos identificado como extensión.» |
| 39 | Grafo de precedencia | *"Serialización por Conflictos… grafo de precedencia… si hay ciclo no es serializable"* (`sem05_teo:508-650`); Lab 05 P3/P4 | No hay código | **NC** | «El grafo de precedencia lo resolvimos a mano en el laboratorio; en runtime no lo verificamos porque con bloqueo pesimista la seriabilidad está garantizada por construcción, y la clase dice que las técnicas pesimistas garantizan la seriabilidad antes de la ejecución.» |
| 40 | Demo multihilo | *"Actualización perdida"* con X=100, −10 y +100 (`sem05_teo:194-330`); enunciado pide hilos (`enunciado:39-42`) | `demo_concurrencia.py` con 2 hilos, `sleep(0.05)` y X=190 esperado `demo_concurrencia.py:7-40` | **A** | «La demo reproduce la actualización perdida del slide con dos hilos: sin locks X varía, con PX se serializan y X queda en 190.» |
| 41 | Concurrencia en el motor real | — | `Transaction` opera sobre un `dict`; `DemoEngine.run()` serializa todo con un mutex `engine.py:69,110-112` | **R** | «El control de concurrencia de la Parte 1 se demuestra con hilos sobre un recurso compartido; el API web toma un mutex porque las operaciones de archivo no son atómicas a nivel de storage, y lo declaramos explícitamente en el README.» |
| 42 | Log Manager (WAL) | *"cada cambio se escribe en el log ANTES de ir a disco… force-the-log: fsync en cada COMMIT"* (`sem01_teo:558-566`) | **No existe** (0 coincidencias de `WAL`/`log_file`) | **NC** | «El WAL no está en el alcance de la Parte 1 —el enunciado sólo pide BEGIN/END, locks y la demo con hilos— y lo tenemos declarado como el primer ítem posterior; hoy `commit()` no fuerza nada a disco, así que el motor no ofrece Durabilidad real.» |
| 43 | Recovery Manager (UNDO/REDO, checkpoints) | *"`<Ti, X, IA, ID>`… UNDO/REDO… dos/tres pasadas… checkpoints"* (`sem05_teo:1107-1600`); Lab 05 P5–P7 | **No existe** | **NC** | «La recuperación es material de las semanas 01 y 05 y no está en el alcance de la Parte 1; sabemos que el proceso es recorrer el log del final al inicio para armar las listas UNDO (sin Commit) y REDO (con Commit) y luego rehacer desde el inicio y deshacer desde el final.» |
| 44 | Espacial (R-Tree/GiST) | *"índice espacial jerárquico… MBR… MINDIST(Q,MBR) ≤ radio… GiST"* (`sem06_teo:979-1034,1262-1302`) | Nada (sólo roadmap `README.md:665`) | **NC** | «Es la Parte 2 del enunciado, prevista para la semana 8: R-Tree con MBR y poda por MINDIST ≤ radio para rango y k-NN, y Haversine para distancia geodésica; hoy no hay código.» |
| 45 | Texto (SPIMI, TF-IDF, BM25) | *"Índice Invertido con Similitud de Coseno: `casa → [1:1, 2:1, 3:2, 4:1]`… TF-IDF & Similitud de Coseno"* (`sem07_teo:866,2203-2218`) | Nada (sólo roadmap `README.md:666`) | **NC** | «Es la Parte 3, semana 12: índice invertido con SPIMI —la versión con memoria acotada de las posting lists `(doc_id: tf)` de clase— y ranking TF-IDF + coseno y BM25; hoy no hay código.» |
| 46 | Catálogo / tamaño de tablas | Lab 01: catálogo del sistema, filas/páginas/tamaño por tabla (`sem01_lab:31-55`) | `_table_info` expone `size_bytes`, `record_size`, `row_count` por tabla `engine.py:200-221` | **A** | «El panel de archivos muestra lo mismo que el catálogo del sistema de PostgreSQL: esquema, tamaño en bytes de cada archivo, tipo de registro y número de filas.» |
| 47 | Planner basado en reglas | Clase: costos por operación Heap/Sorted/Hash/B+Tree (`sem03_teo:808-896`) | `QueryPlanner` con reglas y `reason` por paso `query_planner.py:133-142` | **A** | «El planner aplica las reglas de costo de la clase —hash para igualdad, B+ para rango, B+ agrupado para evitar el sort, external hashing para GROUP BY y join— y cada paso del plan lleva su justificación en texto para el panel de plan de ejecución.» |

---

## 11. Plan de repaso (1 página): preguntas del profesor y respuesta correcta

### 11.1 Guion de 90 segundos para abrir la defensa (módulo por módulo)

> «La Parte 1 son cuatro bloques. **Almacenamiento**: Heap File paginado con registros de longitud fija empaquetados con `struct` —el `Fijo2.py` de clase— con borrado lógico y free list; y Archivo Secuencial Paginado con `.main` ordenado, `.aux` como overflow, eliminación lazy y reorganización al 30 %, que es la estrategia de overflow del slide. **Indexación**: B+ Tree agrupado y no agrupado con la política de split y de merge/redistribución de clase y hojas enlazadas para los rangos; Hash Extendible de Fagin con profundidad global y local y `Key % 2^D`. **Algoritmos externos**: External Sort de dos fases con k-way merge y min-heap, y Grace Hashing para GROUP BY y join. **SQL y concurrencia**: parser, planner basado en reglas y ejecutor, más LockManager PS/PX con 2PL estricto y demo multihilo de la actualización perdida. **Lo que declaramos fuera de alcance**: recuperación con WAL —material de las semanas 01 y 05, no la pide el enunciado en la Parte 1—, bitmap index scan, y las Partes 2 y 3 (espacial y texto).»

### 11.2 Las 20 preguntas más probables y su respuesta

| # | Pregunta del profesor | Respuesta correcta (con la fuente) |
|---|---|---|
| 1 | «¿De qué tamaño es tu página?» | «Declaro `PAGE_SIZE = 4096` y la página efectiva es `(4096 // record_size) * record_size`: 4047 B para `users` (record de 57 B, 71 slots) y 4087 B para `departments` (record de 61 B, 67 slots) — es exactamente el tamaño de los `.dat`. No parto registros entre páginas porque la diapositiva de longitud fija dice que un registro no puede cruzar el límite del bloque.» |
| 2 | «¿Dónde está el header de la página con el número de registros activos?» | «No tengo header de página: uso el bloque compacto de `Fijo2.py` y el control de espacio libre en el archivo `.free` — el patrón de archivo auxiliar con posiciones de `Variable1.py`. El header con `num_active` y puntero al primer eliminado está identificado como el siguiente ajuste, y es lo que el Lab 02 pide.» |
| 3 | «¿Por qué el `.free` es un pickle y no un puntero en la página?» | «Porque `Variable1.py` de la semana 02 resuelve el acceso aleatorio a registros con un archivo de índice aparte (`index.write(struct.pack("Q", pos))`); aplico el mismo patrón a los slots libres. Ventaja: la página queda idéntica al bloque de longitud fija y no gasto bytes de cabecera. Desventaja: una escritura extra por operación.» |
| 4 | «¿Cómo sabes cuál es la página efectiva si cambia con el esquema?» | «`slots_per_page = PAGE_SIZE // record_size` y `page_bytes = slots_per_page * record_size`; los dos se recalculan del esquema en cada operación (`heap_file.py:42,56`), así que el archivo es autoconsistente sin metadatos.» |
| 5 | «¿Tu Archivo Secuencial está paginado?» | «No con páginas del heap: es el *Ordered/Sorted File* de Elmasri con el overflow file de la diapositiva, sobre el archivo binario de longitud fija. El costo lo mido como la clase: la búsqueda binaria cuesta ⌈log2 b⌉ accesos.» |
| 6 | «¿Cuándo reorganizas?» | «Cuando el área auxiliar o los tombstones superan el 30 % del archivo principal (`REORG_AUX_RATIO = REORG_WASTE_RATIO = 0.3`), que es el umbral del enunciado; la reorganización mezcla `.main` y `.aux`, ordena por clave y vacía el auxiliar.» |
| 7 | «¿Qué pasa con los índices cuando reorganizas?» | «Todos los RID cambian porque `.main` se reescribe completo, así que reconstruyo los índices con `rebuild_indexes()`. Es correcto pero costoso: hoy lo hago en cada insert a una tabla secuencial y lo voy a condicionar a que el contador de reorganizaciones cambie.» |
| 8 | «¿Aplicaste MOVE THE LAST?» | «No. El enunciado pide *una* estrategia de reutilización de espacios libres e implementé free list con borrado lógico. MOVE THE LAST mueve el último registro a la posición del eliminado y obligaría a reescribir su RID; lo descarté deliberadamente.» |
| 9 | «¿Y los registros de longitud variable y el Slotted Page?» | «Mi subconjunto de tipos es INT/FLOAT/VARCHAR(n) con `n` fijo, así que uso longitud fija (`Fijo2`). El Slotted Page con slot directory (offset,length), registros desde el final y crecimiento del directorio desde el inicio está en la diapositiva y en la Parte 2 del Lab 02; no lo necesité y está declarado como extensión.» |
| 10 | «¿Cuál es el mínimo de entradas por nodo en tu B+?» | «⌈FB/2⌉ con FB = 4: `min_leaf_keys = ⌈(order-1)/2⌉ = 2` y `min_internal_children = ⌈order/2⌉ = 2`; `validate()` falla si un nodo queda por debajo o si las hojas no están a la misma profundidad.» |
| 11 | «¿Cómo eliminas en el B+?» | «Igual que la clase: busco la hoja, quito el par; si el nodo baja del mínimo, primero redistribuyo con un hermano que tenga más del mínimo y, si no cabe, fusiono con el hermano actualizando la clave del padre; la cascada puede llegar hasta la raíz y reducir la altura.» |
| 12 | «¿Cuántos accesos a disco hace una búsqueda en tu B+?» | «Teóricamente ⌈log_⌈FB/2⌉ M⌉, que es el costo de búsqueda de la diapositiva. En mi implementación la estructura está en memoria, así que el costo real son los nodos visitados; el `validate()` y el benchmark reportan la altura del árbol para poder contrastarlo.» |
| 13 | «¿Cuántos bits del hash usas en el extendible?» | «Los `D` bits **menos** significativos: `hash(key) & ((1 << global_depth) - 1)`, que es exactamente `Bin(Key % 2^D)`, la función del laboratorio. Por eso duplicar el directorio concatenando la copia es correcto: cada índice `i` y `i + 2^(D-1)` comparten bucket.» |
| 14 | «¿Qué pasa si el bucket se llena?» | «Si `local_depth == global_depth` duplico el directorio y luego divido: creo un bucket nuevo, redirijo los índices del directorio que tienen el bit `1 << old_depth` y reinserto todas las claves; ambas profundidades locales suben a `d + 1`. Es el algoritmo de Fagin de la diapositiva.» |
| 15 | «¿Y si se vacía un bucket?» | «Fusiono con su *buddy* —el índice del directorio con el bit `1 << (d-1)` invertido— sólo si tiene la misma profundidad local y la suma de claves distintas cabe en un bucket; después reduzco la profundidad global mientras las dos mitades del directorio sean idénticas. Eso responde la pregunta del Lab 03 sobre fusión y reducción del directorio.» |
| 16 | «¿Tu hash usa buckets de overflow encadenados, como pide el laboratorio?» | «No: implementé el hashing extendible puro de la diapositiva, que siempre divide y rehashea, así que el encadenamiento máximo N=1 del laboratorio nunca se alcanza. El hash estático paginado con cadenas de overflow es la técnica anterior que el propio material señala como deficiente, y el proyecto pide el hash dinámico.» |
| 17 | «Explícame el External Sort.» | «Two-Phase Multiway Merge Sort: fase 1 lee `memory_limit_records` registros a RAM, los ordena y los escribe como run a un temporal; fase 2 abre `fan_in` runs a la vez —los B-1 buffers de entrada más la salida— y con un min-heap saca siempre la clave menor, escribiendo el resultado; si quedan más runs que buffers, repito la fusión en pasadas adicionales, que es el *Merge Pass 1 / Merge Pass 2* del slide.» |
| 18 | «¿Cómo hace el GROUP BY externo?» | «Grace Hashing en dos fases: particiono con `h_p` en `partition_count` archivos temporales, un buffer de salida por partición, de modo que todas las tuplas con la misma clave caen en la misma partición; luego leo una partición a la vez y construyo la tabla hash en RAM con una segunda función `h_r` para agregar. Si una partición no cabe, la reparticiono recursivamente. Para el equi-join uso la misma `h_p` en ambas relaciones, así las particiones se corresponden y sólo comparo partición i con partición i.» |
| 19 | «¿Cómo controlas la concurrencia?» | «Con un LockManager por clave con protocolos PS y PX: N lectores o un escritor, y conversión de PS a PX de la misma transacción. Todos los locks se liberan sólo en COMMIT o ROLLBACK, así que es 2PL estricto y no puede haber lecturas sucias. El interbloqueo lo prevengo con un timeout de 2 segundos que aborta la transacción y hace ROLLBACK.» |
| 20 | «¿Dónde está tu recuperación ante fallos?» | «No está, y es una decisión de alcance: la sección 2.1.4 del enunciado pide BEGIN/END TRANSACTION, un mecanismo de bloqueo y la demo con hilos, y eso está implementado. El WAL con registros `<Ti, X, IA, ID>`, las estrategias de modificación inmediata y diferida y el proceso de recuperación de dos o tres pasadas con checkpoints son material de las semanas 01 y 05 y son el primer ítem después de la Parte 1. Hoy `commit()` no fuerza nada a disco, así que el motor no ofrece Durabilidad real y lo tenemos declarado en el README.» |

### 11.3 Las 6 preguntas trampa (estas son las que causaron la crítica)

| # | Pregunta trampa | Por qué duele | Respuesta |
|---|---|---|---|
| T1 | «¿Por qué tu `README` dice "detección de conflictos" si no hay wait-for graph?» | **Contradicción entre documentación y código** (`README.md:198,311-312` vs `lock_manager.py`). Es exactamente el tipo de cosa que hace decir "no pueden explicar su código". | «El README estaba mal redactado: hacemos *prevención* por timeout, no detección por wait-for graph. Lo corregimos a "locks PS/PX, 2PL estricto y resolución de interbloqueos por timeout".» **Corregir el README antes de la entrega.** |
| T2 | «¿Por qué hay dos ejecutores (`query/executor.py` y `query/query_executor.py`)?» | Dos implementaciones del mismo concepto: parece código de dos personas sin integrar. | «`query_executor.py` es la ruta vigente que usa el API; `executor.py` es el ejecutor end-to-end anterior (PR #37) que conservamos porque `tests/test_end_to_end.py` y `examples/demo_parte1.py` dependen de él. Está documentado en `README.md:161-164`.» **Ideal: dejar uno y adaptar los tests, o marcarlo como deprecado con un comentario en la cabecera.** |
| T3 | «¿Por qué importas `deepcopy` en el B+ agrupado?» | Pregunta de línea, y la respuesta revela si entienden su propio diseño. | «Porque en el índice agrupado la hoja guarda el registro completo: sin `deepcopy` el índice y la variable del llamador compartirían el mismo `dict` y una modificación externa corrompería el índice.» (`clustered_bplus.py:1,40`) |
| T4 | «¿Por qué reconstruyes todos los índices en cada INSERT?» | Es O(n) por inserción: parecerá inexperto. | «Porque la reorganización del secuencial cambia todos los RID y no puedo saber si se disparó sin consultar el estado; la corrección es comparar `n_reorganizaciones` antes y después y reconstruir sólo si cambió — es un cambio de tres líneas que vamos a hacer.» |
| T5 | «¿Por qué `slots_per_page` usa `max(1, ...)`?» | Pregunta de caso borde. | «Para que un `record_size` mayor que `PAGE_SIZE` no dé cero slots y no cause división por cero en `_num_paginas`; en ese caso la página es un único registro.» (`heap_file.py:42,57`) |
| T6 | «`TEXT` se convierte en `VARCHAR(255)`. ¿Qué pasa si el texto tiene 300 caracteres?» | Revela si conocen el límite de su propio motor. | «Se trunca silenciosamente a 255 bytes en `record.py:62` (`[: f.size]`). Es una limitación conocida: el motor no tiene campos de longitud variable y por eso el Slotted Page está en el roadmap.» |

### 11.4 Checklist de acción antes de la entrega/oral (en orden de impacto)

1. ☐ **Corregir el README** (`:198`, `:311-312`): quitar "detección de conflictos" y "crecimiento de locks"; escribir *"locks PS/PX por clave, 2PL estricto (liberación sólo en COMMIT/ROLLBACK) y prevención de interbloqueos por timeout de 2 s"*.
2. ☐ **Añadir al README/informe el párrafo de alcance de recuperación** (texto listo en §9.3, Opción A). Decirlo en voz alta en la defensa antes de que lo pregunten.
3. ☐ **Añadir `wait-for graph`** al `LockManager` (~25 líneas) y usarlo en `demo_concurrencia.py` para imprimir un ciclo real de interbloqueo. Convierte el mayor riesgo de la semana 05 en una demo.
4. ☐ **(Opcional, ~120 líneas) Implementar el WAL mínimo** de §9.3, Opción B: `log_manager.py` con `<Ti,BT>`, `<Ti,X,IA,ID>`, `<Ti,Commit>`, `<Ti,Abort>`, `fsync` en COMMIT, más `recovery.py` con las dos pasadas y un test con "crash" simulado. Si se hace, sube el proyecto de "cumple el enunciado" a "cubre la clase".
5. ☐ **Condicionar `rebuild_indexes()`** al cambio del contador `n_reorganizaciones` (`query_executor.py:266-273`).
6. ☐ **(Opcional, ~40 líneas) Bitmap index scan** en el planner: `kind="bitmap"` implementado como `bplus_unclustered` + bitmap de páginas, usado cuando hay dos o más predicados sobre columnas indexadas. Cierra el único hueco técnico de la semana 04 y se ve muy bien en el panel de plan.
7. ☐ **Añadir `PAGE_HEADER`/`FILE_HEADER`** al heap (o, como mínimo, la frase de §1.2.1 y §1.2.6 en el informe).
8. ☐ **Marcar `query/executor.py` como legado** con un comentario en su cabecera y una fila en el README (ya está documentado en `README.md:161-164`).
9. ☐ **En el roadmap, marcar las Partes 2 a 5 como "no iniciadas"** en lugar de listar archivos previstos (`indexes/rtree.py`, `text/spimi.py`) que no existen.
10. ☐ **Confirmar con el profesor que SPIMI y BM25 se dictaron**: en el texto extraído de la semana 07 aparecen TF-IDF y similitud de coseno con índice invertido, pero **no** `SPIMI` ni `BM25` (el PDF se titula "…Textual **1**").

---

*Informe generado en modo revisión (solo lectura sobre `BD2\` y sobre el código fuente del proyecto). Sin modificaciones a archivos de `C:\Users\illes\Documents\BD2` ni a los módulos de `Proyecto-BD2` fuera de `.review\` y `.review_tmp\`.*
