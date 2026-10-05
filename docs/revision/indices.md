# Revisión técnica: índices, uso de índices en el planner/ejecutor y experimentos

**Proyecto:** Minigestor de BD multimodal (Parte 1) — `C:\Users\illes\Documents\Proyecto-BD2`
**Alcance revisado:** `indexes/` (B+ genérico, B+ agrupado, B+ no agrupado, hash extendible),
`query/query_planner.py`, `query/query_executor.py`, `query/catalog.py`,
`benchmarks/benchmark_indexes.py` (+ `generate_charts.py`, resultados y plots) y los tests de
estas estructuras.
**Método:** lectura línea a línea contra Ramakrishnan/Gehrke cap. 10–11, Silberschatz cap. 11 e
internals de PostgreSQL; más 7 experimentos ejecutados en modo lectura (scripts temporales en
`.review_tmp/`, ningún archivo del repo modificado). Se corrieron además los 105 tests del área:
**105 passed**.

---

## 1. Resumen ejecutivo

### 1.1 Lo que está bien (y es defendible)

- **El B+ tree (`indexes/bplus_tree.py`) es sólido.** Verifiqué con un *stress test* contra un
  modelo de referencia (órdenes 3, 4, 5, 6, 8, 16, 64; 4 semillas × 3 000 operaciones cada una,
  con duplicados, borrados por valor y por clave, y `validate()` tras **cada** operación):
  **cero discrepancias**. Off-by-one de capacidad, punto de split, fusión/redistribución y
  colapso de raíz están correctos (detalle en §2.1).
- **El hash extendible es correcto en el camino crítico**: duplicación de directorio
  (`_double_directory`, línea 124), split con `local_depth`/`global_depth`, redistribución por
  `_bucket_for` y *shrink* del directorio pasan un test aleatorio contra un modelo `dict`
  (300 semillas × 3 capacidades × 400 operaciones, validando invariantes y contenidos en cada
  paso): **cero fallos**.
- **B+ no agrupado sobre clave no única está bien resuelto**: las hojas guardan **listas de
  RIDs** por clave (`BPlusTree.insert` línea 71: `leaf.values[idx].append(value)`), que es la
  forma aceptable de manejar duplicados en un índice no agrupado; `search` devuelve la lista
  completa y `delete(key, rid)` borra un solo RID.
- **El planner sí usa índices en los casos básicos** (verificado ejecutando el motor real, §3):
  igualdad con hash → `HASH_INDEX_LOOKUP`; igualdad con B+ → `BPLUS_*_LOOKUP`; rango con B+ →
  `BPLUS_*_RANGE_SCAN`; `ORDER BY` ASC sobre la columna indexada → `BPLUS_*_INDEX_SCAN` **sin**
  `EXTERNAL_SORT`; `ORDER BY` DESC → `EXTERNAL_SORT`.
- **No hay "plan que miente" por caída silenciosa a scan completo**: el ejecutor lanza
  `QueryExecutionError` ante un operador de acceso desconocido
  (`query_executor.py:806`), no escanea a escondidas. Los desajustes plan/ejecución que sí
  encontré son de **calidad del plan**, no de corrección (ver 1.2-A).
- **El índice no se queda "viejo" en las rutas normales del ejecutor**: con `DELETE` + reuso de
  slot del heap y con `UPDATE`, los índices quedan coherentes (probado, §3.5).
- Los **7 ejes** que pide el enunciado están presentes como métricas en
  `benchmark_results/index_benchmark.{csv,json}`: `build`, `exact_hit`, `exact_miss`,
  `range_search` (+`_materialized`, `_raw_index`), `ordered_scan`, `insert`, `delete`,
  `serialized_size`, en N = 1 000 / 10 000 / 100 000.

### 1.2 Lo que está mal — prioridad

| # | Severidad | Problema | Evidencia |
|---|---|---|---|
| **A1** | **Alta (credibilidad del planner)** | Con `WHERE age >= 19 AND age <= 23` el planner usa **solo un extremo** del intervalo y deja el otro a un `FILTER` posterior. El índice B+ ya sabe hacer rango cerrado (`range_search(start, end)`) pero el planner **empareja 1 predicado con 1 índice** y no compone intervalos. | `query_planner.py:280-289` (bucle predicado×índice), `:189-205` (residual), `bplus_tree.py:275` |
| **A2** | **Alta (credibilidad del planner)** | Todo `WHERE ... OR ...` (documentado como soportado en `README.md:484`) **desactiva por completo el uso de índices**: el ejecutor borra los predicados antes de planificar. `EXPLAIN` muestra `HEAP_SCAN` sin explicar nada. Los índices existen y podrían usarse con *index union*. | `query_executor.py:140` y `:634`: `replace(query, predicates=()) if query.or_groups else query` |
| **A3** | **Alta (distorsiona el benchmark)** | `ClusteredBPlusIndex` guarda **copias completas** del registro y hace `deepcopy` en `insert`, `search`, `range_search` y `scan`. Consecuencia: el índice agrupado **pierde la comparación de igualdad exacta** (13,97 µs vs 2,72 µs del no agrupado a 100 000) aunque su recorrido de hojas sea el más rápido. El propio equipo lo documenta como "mejora pendiente". | `clustered_bplus.py:40, 47, 64, 88, 90, 92`; `conclusiones_experimentales.md:253-255` |
| **A4** | Media-alta (correctitud de borde) | Clave `NULL` en una columna indexada: el parser acepta `NULL` (`sql_parser.py:994`) pero **ningún índice tiene semántica de NULL**. Verificado: `BPlusTree.search(None)` → `TypeError: '<' not supported between instances of 'NoneType' and 'int'` (el `bisect` de `_find_leaf`, `bplus_tree.py:56`) y `insert(None, v)` → el mismo `TypeError`; el hash, en cambio, **acepta** `None` como clave normal (`hash(None)` → 0) y `WHERE col = NULL` devolvería filas insertadas con NULL, violando la lógica de 3 valores. En el motor integrado, `INSERT ... NULL` en columna indexada INT muere antes, en `int(v)` de `storage/record.py:58` (no en el índice). | verificado con `.review_tmp`; `bplus_tree.py:53-64`, `extendible_hash.py:45-53, 94`, `query_executor.py:1065`, `storage/record.py:58` |
| **A5** | Media (correctitud del planner) | El modelo de costo no valoriza "el orden ya viene resuelto": una igualdad por hash (110 puntos) gana a un escaneo ordenado B+ (70) aunque el `ORDER BY` sea obligatorio. Caso verificado: con `ix_id_hash(id)` y `ix_sal` B+ agrupado sobre `salary`, `WHERE id = 3 ORDER BY salary` produce `HASH_INDEX_LOOKUP + EXTERNAL_SORT` en lugar de `BPLUS_CLUSTERED_INDEX_SCAN + FILTER` (sin sort). | `query_planner.py:324-332` (`kind_priority`/`max`), `:373-382` (`_order_bonus`), `:299-310` (candidato de orden, 70) |
| **B1** | **Alta (enunciado)** | Los experimentos **no tienen baseline de scan lineal/secuencial** en igualdad ni en rango. Sin baseline no se puede afirmar "mejora X×", que es justo lo que exige la comparación experimental. La comparación de **espacio** también es injusta de base: el B+ agrupado se mide *pickleando los registros completos* que ya viven en el heap. | `benchmark_indexes.py` (no existe métrica `linear_scan`), `conclusiones_experimentales.md:125-152` |
| **B2** | Media | Números del informe (`docs/conclusiones_experimentales.md:125-140`) **no coinciden** con el JSON vigente (p. ej. construcción a 100 000: doc 14 566 ms vs JSON 12 760 ms; igualdad hit 100 000 B+ no agrupado: doc 2,72 vs JSON 2,13 µs; borrado 100 000: doc 36,89/47,57 vs JSON 33,30/50,45 µs). El JSON no registra máquina, CPU, hora ni desviación estándar. | `benchmark_results/index_benchmark.json` vs `docs/conclusiones_experimentales.md` |
| **B3** | Media | La "recuperación de fila" del no agrupado se mide contra un **`dict` en memoria** (`rid_to_record`), no contra `HeapFile`: subestima la ventaja real del agrupado ~19×. El equipo lo midió aparte a mano y lo menciona (`conclusiones_experimentales.md:204-208`), pero la métrica publicada sigue siendo la del dict. | `benchmark_indexes.py:186-191, 671-676` |
| **B4** | Media | Falta la comparación **directa** `BPLUS_*_INDEX_SCAN` (evitar sort) vs `EXTERNAL_SORT` con el mismo N y la misma selectividad, y `LIMIT` no se empuja al índice (se materializa todo y luego se recorta). | `query_executor.py:209-231`, `query_planner.py:249-267` |
| **C1** | Media (defensa oral) | `ExtendibleHash._try_merge` (fusión de *buddies* + *shrink* del directorio, `:194-268`) **no es texto estándar**: el hashing extendible de libro no fusiona en `delete`. Es la construcción más difícil de justificar del repo. Además `_split_bucket` y `_try_merge` recorren el directorio completo (`:147`, `:241`), y `max_depth=64` por defecto permitiría un directorio de 2^64 entradas si el hash es malo (`_double_directory` sólo se protege con `OverflowError`). | `extendible_hash.py:116-268` |
| **C2** | Media | Los tres índices son **100 % en memoria**: no hay serialización ni persistencia en `indexes/` (grep de `pickle|save|dump|to_disk` sólo devuelve `bulk_load`/`load_factor`). `pickle` aparece únicamente en el benchmark para medir tamaño. El catálogo persiste sólo **metadatos** y reconstruye por escaneo completo (`catalog.py:280-296, 385-428`). Hay que decirlo explícitamente en el informe (hoy no está). | `query/catalog.py:385-428`, `benchmark_indexes.py:337-363` |
| **C3** | Media | La consistencia índice↔almacenamiento depende de que **toda** mutación pase por el ejecutor (`DELETE` reconstruye en secuencial `query_executor.py:370-371`, `UPDATE` reconstruye en heap `:481-484`). Si el almacenamiento cambia por fuera, el B+ **agrupado devuelve registros congelados** (probado, §3.5). Es un invariante que el profesor puede cuestionar y que no está escrito como contrato. | `clustered_bplus.py:40, 47, 64`; `query_executor.py:370-371, 481-484` |

**Prioridad sugerida:** A1 → A2 → A3/B1 → A5 → A4 → B2/B3/B4 → C1/C2/C3.
Un arreglo pequeño (A1 + A2 + A5 ≈ 60 líneas en `query_planner.py`/`query_executor.py`) mejora
mucho más la nota de "uso de índices" que cualquier optimización de constante.

---

## 2. Corrección de cada estructura

### 2.1 B+ tree genérico — `indexes/bplus_tree.py` — **VEREDICTO: correcto**

| Aspecto | Veredicto | Evidencia |
|---|---|---|
| Semántica de `order` | Correcta y coherente: `max_keys = order-1` (`:25-26`), máx. `order` hijos por nodo interno. Es la convención "orden *d* = máx. hijos" de Ramakrishnan; **no hay dos definiciones mezcladas**, pero tampoco está definida en el README (sólo se menciona el uso del índice para `ORDER BY`, `README.md:279`) → conviene un párrafo corto en §7 del README. | `:25-34` |
| Capacidad / off-by-one | Sin off-by-one. El split se dispara con `len(keys) > max_keys` (`:79`) y `_split_leaf` reparte `(len+1)//2` (`:86`): con order=4 → 4 claves → 2 y 2. Nunca deja un lado por debajo del mínimo `ceil((order-1)/2)` (`:29-30`). | `:79-91`, `:114` |
| Split de hoja | **Copy-up** correcto (la clave central **se queda** en la hoja derecha, se enlazan `next`/`prev`). | `:84-106` |
| Split de interno | **Push-up** correcto: `right.children = node.children[split:]` y los separadores se recalculan como primera clave de cada hijo (`_first_key`). Prefijo de claves estables, no hay claves repetidas en internos. | `:119-150`, `:44-46` |
| Búsqueda | Igualdad: `_find_leaf` con `bisect_right` sobre separadores-duplicado (`:53-57`) + `bisect_left` en la hoja (`:61`) → consistente con la ruta. Rango: recorre hojas por la cadena de `next` con los cuatro tipos de límite y `limit` (`:275-306`). | `:59-64`, `:275-306` |
| Claves duplicadas | Se guardan como **lista de valores por clave** (`:70-71`); `search` devuelve todos los valores. Correcto para usar el B+ como índice no agrupado sobre columna no única. | `:70-73` |
| Borrado | Redistribución izquierda/derecha y fusión de hojas + `_after_child_removed`/`_rebalance_internal` en cascada, colapso de raíz. Verificado por *stress* aleatorio (0 fallos). | `:152-273` |
| Contador `_size` | Coherente: +1 por valor insertado, −1 por valor borrado, −len(values) si se borra la clave entera (`:169`). | `:66-77, 152-181` |
| `validate()` | Fuerte: comprueba overflow/underflow, `separator == first_key(child)`, punteros `parent`, misma profundidad de hojas, cadena `prev/next`, crecimiento ordenado, ausencia de claves duplicadas como entradas separadas y el contador. | `:308-372` |

**Observaciones menores (no son bugs, pero pueden preguntarse):**

1. `min_leaf_keys = ceil((order-1)/2)` (`:29-30`) mientras `min_internal_children = ceil(order/2)`
   (`:33-34`). Para order=4 da 2 y 2; para order=3 da 1 y 2. Ambos satisfacen ≥ mitad, pero el
   cálculo asimétrico obliga a explicarlo ("¿por qué el mínimo de hojas no es
   `floor(order/2)`?"). Recomendación: derivar ambos de `order` con la misma fórmula y comentarla.
2. `delete(key, value)` con `value` inexistente devuelve `False` **cuando la clave existe**
   (`:162-164`). Es correcto, pero `_execute_insert` (`query_executor.py:1073`) usa ese valor de
   retorno ignorándolo; un test que borre un `rid` ya borrado pasaría desapercibido.
3. `_refresh_upwards` (`:48-51`) recalcula **todos** los separadores desde el nodo hasta la raíz
   en cada inserción sin split. Con `order=64` es O(altura × order) por inserción; explica parte
   del costo de construcción del agrupado. Es una decisión de simplicidad defendible, pero hay
   que decirla.
4. `validate()` no comprueba que las claves del subárbol derecho sean *estrictamente* mayores que
   el separador (sólo `first_key`), lo cual es consistente con la implementación pero no con la
   definición dura "clave < separador ≤ subárbol derecho"; un profesor muy formal podría
   preguntarlo. Basta con responder que el árbol usa **separadores-duplicado** (primera clave del
   hijo derecho), como en PostgreSQL/InnoDB.

### 2.2 B+ agrupado — `indexes/clustered_bplus.py` — **VEREDICTO: correcto, pero caro y sin contrato**

| Aspecto | Veredicto | Evidencia |
|---|---|---|
| Almacenamiento de registros completos en hojas | Correcto conceptualmente (hojas = filas), pero **duplica datos** con el heap. | `:40` |
| Copia defensiva | `deepcopy` en `insert` (`:40`), `search` (`:47`), `range_search` (`:64`) y `update` (`:90`). Es la causa medida de que el agrupado sea el más lento en igualdad (13,97 vs 2,72 µs) y en rango (8 421 vs 953 µs) — el propio informe lo admite (`conclusiones_experimentales.md:253-255`). | `:40, 47, 64, 90` |
| Restricción UNIQUE | `insert` comprueba `tree.search(key)` antes de insertar (`:37-38`); `update` valida colisión y hace rollback (`:82-93`). Verificado con los tests existentes. | `:34-40, 75-95` |
| `delete(key, record)` | Borra **una** ocurrencia; el valor almacenado es el registro completo → coincide con lo que envía el ejecutor (`row`). | `:69-73`, `query_executor.py:1088` |
| Invariante crítico | El índice **no relee el almacenamiento**: si el heap/seq cambia por fuera, el B+ agrupado devuelve la versión congelada. Probado en `.review_tmp/probe_misc.py`: `SELECT *` devuelve `salary=999.0` y `SELECT WHERE salary = 100.0` devuelve `{id:1, salary:100.0}` con la misma fila. En el motor real esto **no** ocurre porque `UPDATE`/`DELETE`/`INSERT` del ejecutor reconstruyen/mantienen los índices (§3.5), pero no está documentado como contrato. | `:47, 64` |
| `update()` | Hace `search(old_key)` + `delete` + `insert` (`:78-95`). Correcto; no usa `BPlusTree.update` porque no existe. | `:75-95` |

### 2.3 B+ no agrupado — `indexes/unclustered_bplus.py` — **VEREDICTO: correcto**

| Aspecto | Veredicto | Evidencia |
|---|---|---|
| No única con lista de RIDs | Correcto: el árbol guarda `key → [rid, rid, ...]`. Probado: `WHERE name = 'Ana'` devolvió los dos RIDs correctos y `DELETE ... AND age = 22` eliminó sólo uno. | `:47`, `bplus_tree.py:70-71` |
| `search` / `range_search` devuelven RIDs | Correcto y esperado; `range_entries`/`scan_entries` exponen las claves para ordenar. | `:62-102` |
| UNIQUE | `insert`/`insert_key`/`update` comprueban duplicado y hay rollback simple (`:44, 53, 120-132`). | `:32-56, 111-134` |
| Resolución de RID | El ejecutor la hace con `table.read_rid(rid)` (`query_executor.py:808-814`) y **descarta** los RIDs que ya no existen (`if row is not None`), y esto es lo que vuelve segura la integración con el archivo secuencial. | `query_executor.py:808-814` |
| Riesgo residual | El índice no se reindexa si `reorganizar()` cambia todos los RIDs; el ejecutor lo compensa reconstruyendo (`query_executor.py:273, 371, 475, 484`). Es un contrato frágil: cualquier nueva ruta de escritura que olvide `rebuild_indexes` produce resultados incorrectos. | `query/catalog.py:400-407` |
| `update()` | Con `new_rid` opcional para el caso "misma clave, nuevo RID" (`:111-134`). Correcto. | `:111-134` |

### 2.4 Hash extendible — `indexes/extendible_hash.py` — **VEREDICTO: correcto; `delete` no es estándar**

| Aspecto | Veredicto | Evidencia |
|---|---|---|
| Directorio y profundidades | Correcto: inicia con `global_depth=1` y 2 buckets (`:33-37`); `_double_directory` hace `directory + directory[:]` y sube `global_depth` (`:116-125`); `_directory_index` usa los `d` bits menos significativos (`:51-53`). | `:33-53, 116-125` |
| Split | Correcto: sube `local_depth`, duplica el directorio si `old_depth == global_depth`, crea el nuevo bucket y redirige los índices con el bit de split puesto (`:127-157`). El bit usado (`1 << old_depth`) es el bit que distingue el nuevo bucket. | `:127-157` |
| Redistribución | Correcto y sin pérdidas: se vacía el bucket original y cada clave se reubica con `_bucket_for` (`:151-157`). Verificado a fondo: si dos buckets terminaran apuntando a la misma clave, la asignación `target.records[key] = values` **sobrescribiría**; razoné que es imposible (el índice de un bucket es un prefijo de longitud `local_depth` de su hash) y el *stress* de 300 semillas no encontró pérdidas. Vale la pena añadir un `assert` defensivo. | `:151-157` |
| UNIQUE | `insert` rechaza duplicados si `unique=True` y agrega valores si no (`:94-100`); `validate()` comprueba `len(values)==1` para únicos (`:380-383`). | `:80-105, 380-383` |
| Duplicados no únicos | Se guardan todos los valores bajo la misma clave (`:98`), sin disparar split. Correcto. | `:94-100` |
| `max_depth` | Protege contra hashes inseparables lanzando `OverflowError` (`:116-134`) y hay test dedicado. Pero el default es **64** (`:20`): un hash muy malo podría intentar un directorio de 2^64 entradas antes de rendirse. En la práctica con `hash_func=int` medí `global_depth=11` y 2 048 entradas de directorio con 100 000 claves. | `:20, 116-134`; medido |
| **`delete` + `_try_merge` + `_shrink_directory`** | **Funciona, pero NO es texto estándar.** El hashing extendible de libro **no fusiona** buckets al borrar. Además: `_try_merge` sólo fusiona si los *buddies* tienen la misma `local_depth` y la suma de claves distintas cabe (`:198-245`); el merge recorre **todo** el directorio (`:241-243`) igual que el split (`:147-149`), o sea O(2^d) por operación. | `:163-268` |
| `hash_func` por defecto | `hash` de Python es **randomizado por proceso** (PYTHONHASHSEED) para `str`. El benchmark usa `hash_func=int` (`benchmark_indexes.py:253`) y `catalog._make_index` construye `ExtendibleHash` **sin** `hash_func` (`catalog.py:305`), es decir usa `hash()` sobre strings → el índice no es reproducible entre corridas (no afecta resultados porque se reconstruye, pero rompe cualquier intento de persistirlo). | `:29`, `catalog.py:305, 409-415` |
| Contadores | `_size` cuenta pares (clave, valor) y `validate()` cruza `total_entries` contra `_size` (`:387-390`). | `:42-43, 385-390` |

**Conclusión §2.4:** no encontré corrupción ni pérdida de claves. Lo cuestionable es de diseño
(merge no estándar, O(2^d) y `max_depth` laxo), y son las tres cosas que el equipo debe saber
defender con seguridad.

### 2.5 Persistencia — **los tres índices son en memoria (declararlo)**

- No existe en `indexes/` ninguna función de serialización/persistencia (búsqueda de
  `pickle|save|dump|load|serializ` → sólo `bulk_load` y `load_factor`).
- `pickle` se usa **sólo** en el benchmark para estimar tamaño (`benchmark_indexes.py:337-363`,
  desconectando temporalmente `next/prev` para evitar `RecursionError`).
- El catálogo persiste únicamente **metadatos** (`catalog.describe_tables`, `catalog.py:223-244`)
  y al restaurar **reconstruye desde cero** escaneando el almacenamiento
  (`catalog.py:280-296` y `385-428`).
- Consecuencia honesta que conviene escribir en el informe: **el índice no sobrevive al
  reinicio**; el arranque paga un *rebuild* O(N). Hoy esto no está dicho en ningún documento.

---

## 3. Uso de índices en el planner y en el ejecutor

Todo lo de esta sección está **verificado ejecutando el motor real** (`.review_tmp/probe_engine.py`,
catálogo con tabla `probe(id INT PK, name VARCHAR, age INT)` sobre heap e índices
hash(id), B+ agrupado(age) y B+ no agrupado(name), replicando `backend/engine.py`).

### 3.1 Lo que funciona bien

| Consulta | Plan producido | `used_indexes` | Ejecución |
|---|---|---|---|
| `WHERE id = 3` | `HASH_INDEX_LOOKUP` | `idx_probe_id_hash` | índice, correcto |
| `WHERE age = 20` | `BPLUS_CLUSTERED_LOOKUP` | `idx_probe_age_bplus` | índice, correcto |
| `WHERE age > 20` | `BPLUS_CLUSTERED_RANGE_SCAN` | `idx_probe_age_bplus` | índice, correcto |
| `WHERE age BETWEEN 19 AND 23` | `BPLUS_CLUSTERED_RANGE_SCAN` | idem | índice, correcto |
| `WHERE name = 'Ana'` (no única) | `BPLUS_UNCLUSTERED_LOOKUP` | `idx_probe_name_bplus` | 2 RIDs → 2 filas, correcto |
| `ORDER BY age` | `BPLUS_CLUSTERED_INDEX_SCAN` | idem | **sin `EXTERNAL_SORT`** |
| `ORDER BY age DESC` | `HEAP_SCAN` + `EXTERNAL_SORT` | — | correcto (no hay *reverse scan*) |
| `WHERE id = 3 ORDER BY id` | `HASH_INDEX_LOOKUP` | hash | sin sort (todas las filas tienen el mismo `id`) |
| `WHERE id = 3 ORDER BY age` | `HASH_INDEX_LOOKUP` + `EXTERNAL_SORT` | hash | correcto |
| `WHERE age >= 19 AND id = 3` | `HASH_INDEX_LOOKUP` + `FILTER` | hash | correcto (elige la igualdad más selectiva) |

`EXPLAIN` y `EXPLAIN ANALYZE` están bien conectados: el primero no ejecuta, el segundo añade
`runtime_steps` con `in/out` y milisegundos por operador
(`query_executor.py:625-737`; salida real capturada en §3.4).

### 3.2 Defecto A1 — rangos con dos extremos: el índice se usa a medias

```
SELECT * FROM probe WHERE age >= 19 AND age <= 23
  access_path: BPLUS_CLUSTERED_RANGE_SCAN | used_indexes: ['idx_probe_age_bplus']
  steps: ['BPLUS_CLUSTERED_RANGE_SCAN', 'FILTER']
EXPLAIN ... : 1. BPLUS_CLUSTERED_RANGE_SCAN ...
              2. FILTER [probe] - predicados no resueltos por el camino de acceso
```

Causa exacta: `_choose_access_candidate` recorre `for predicate in query.predicates` y para cada
predicado busca **un** índice (`query_planner.py:280-289`); el ganador consume **un** predicado y
el resto cae al `FILTER` (`:189-205`). El rango abierto se ejecuta en
`query_executor.py:1144-1160` (`_range_bounds`): para `>=` devuelve `(value, None, True, True)`.

Impacto: el motor recorre y **materializa** todo el rango abierto (`age >= 19`, que en un dataset
grande puede ser casi toda la tabla) y recién después filtra. Es el caso más visible de "hay
índice y no se explota del todo" y es exactamente lo que el profesor pidió mejorar.

Además, el sintagma equivalente `WHERE age BETWEEN 19 AND 23` **sí** produce un único predicado
`between` y aprovecha ambos extremos, lo que hace la diferencia aún más llamativa en la demo:
dos consultas semánticamente idénticas producen planes distintos.

### 3.3 Defecto A2 — `OR` desactiva los índices y el `EXPLAIN` no lo dice

```
SELECT * FROM probe WHERE age > 20 OR id = 1
  access_path: HEAP_SCAN | used_indexes: []
  steps: ['HEAP_SCAN']
```

Código responsable (`query_executor.py:139-141` y `:633-635`):

```python
plan = planner.plan(
    replace(query, predicates=()) if query.or_groups else query
)
```

El plan se calcula **sin predicados**, así que el planner no puede saber que existían
(`QuerySpec.or_groups` no se consulta nunca en `query_planner.py`). El filtro posterior sí es
correcto (`_execute_select` reconstruye `filter_predicates` desde `or_groups` en `:158-162`),
pero:

- el `EXPLAIN` de esa consulta **no menciona el OR** (no hay `FILTER` en `steps`, ni `reason`, ni
  `details.disjunction`), sólo aparece en `runtime_steps` al ejecutar;
- `README.md:484` documenta `OR` como soportado sin advertir que pierde todos los índices;
- la solución de libro existe y es barata: *index union* (lookup por cada rama cuando la rama es
  igualdad/rango sobre una columna indexada, y scan sólo si alguna rama no lo es).

El caso `IN` ni siquiera llega a predicado: el parser no implementa `IN` (`KEYWORDS` no lo
incluye, `sql_parser.py:108-113`) ni `NOT`, `LIKE`, paréntesis en `WHERE`; conviene decirlo en la
defensa para no recibir la pregunta por sorpresa.

### 3.4 Defecto A5 — *tie-break* que fuerza un sort evitable

`_choose_access_candidate` puntúa cada candidato (`query_planner.py:334-371`) y elige con
`max(candidates, key=lambda c: (c.score, kind_priority[c.index.kind]))` (`:329-332`), donde
`kind_priority = {hash: 3, bplus_clustered: 2, bplus_unclustered: 1}` (`:324-328`).

Con `idx_id_hash` y `idx_id_bplus` (ambos sobre `id`) y la consulta
`WHERE id = 5 ORDER BY id`, ambos candidatos obtienen **110**: el hash por igualdad (110, `:339`)
y el B+ agrupado por `90 + bonus(15)` (`:345-348` con `_order_bonus` `:373-382`). El desempate
por `kind_priority` elige el **hash**; en ese caso el resultado es correcto y sin sort porque
`_order_is_covered` (`:401-406`) detecta que el `ORDER BY` es sobre la misma columna de la
igualdad y todas las filas tienen el mismo valor.

El problema aparece cuando el `ORDER BY` está en **otra** columna indexada. Verificado con
`QueryPlanner` (`ix_id_hash` sobre `id`, `ix_sal` B+ agrupado sobre `salary`):

| Consulta | Plan elegido | Pasos |
|---|---|---|
| `WHERE id = 3 ORDER BY id` | `HASH_INDEX_LOOKUP` | sin sort (correcto) |
| `WHERE id = 3 ORDER BY salary` | `HASH_INDEX_LOOKUP` | **+ `EXTERNAL_SORT`** |
| `WHERE id = 3 AND salary > 1 ORDER BY salary` | `HASH_INDEX_LOOKUP` | **+ `FILTER` + `EXTERNAL_SORT`** |
| `WHERE id > 3 ORDER BY salary` | `BPLUS_CLUSTERED_INDEX_SCAN` | + `FILTER` (sin sort) |

En las filas 2 y 3 el escaneo ordenado del B+ sobre `salary` (70 puntos, `:299-310`) pierde
contra la igualdad por hash (110 puntos) **sin ningún término de costo que compare "orden ya
resuelto" contra "orden a pagar"**: el bonus de orden (+15) sólo se aplica cuando el predicado
está en la propia columna del `ORDER BY` (`_order_bonus`, `:373-382`). El resultado es un
`EXTERNAL_SORT` evitable, que es justo el caso que el planner dice evitar. No es un error de
corrección (sigue dando resultados correctos), pero es lógica de costo poco defendible: el
criterio debería ser lexicográfico cuando el `ORDER BY` es obligatorio
(`preserva_orden` primero, `score` después), o el bonus de orden debería superar la diferencia
hash(110) vs. B+(70). El test `test_query_planner.py:703-735` hoy fija el comportamiento actual,
así que cualquier arreglo debe actualizarlo.

### 3.5 Integración índice↔almacenamiento (probada)

Ejecutando el motor real (`.review_tmp/probe_stale.py`, `.review_tmp/probe_null.py`):

- `DELETE FROM d WHERE id = 1` seguido de `INSERT INTO d VALUES (1, 777.0)` (el heap **reutiliza**
  el slot `(0,0)`) deja los tres índices coherentes: `SELECT WHERE salary = 100.0` → `[]` y
  `SELECT WHERE salary = 777.0` → la fila nueva. El hash se limpia en `_index_delete`
  (`query_executor.py:1082-1092`) y el reuso de slot no rompe nada.
- `UPDATE t SET age = 99 WHERE id = 3` reconstruye todos los índices (`:481-484`): el B+ agrupado
  pasa de devolver `age=33` a `age=99` (correcto, pero **O(N) por UPDATE**).
- Los índices de mi prueba con **metadatos desalineados** (`register_index(..., implementation=ExtendibleHash(unique=True))`
  sin `unique=True` en los metadatos, `catalog.py:344-351`) mostraron que el `unique` efectivo es
  el de la **implementación**, no el de los metadatos: el planner/`EXPLAIN` puede informar
  `unique: false` mientras el índice **sí** rechaza duplicados. Es una trampa de API que conviene
  cerrar (derivar `metadata.unique` de `implementation.unique` siempre, o lanzar si difieren).

### 3.6 Verificación de la sospecha "el plan dice índice pero el ejecutor escanea"

**No ocurre.** `_execute_access_path` (`query_executor.py:743-806`) despacha por `operator` y
lanza `QueryExecutionError(f"unsupported access path: {operator}")` al final; no hay `except`
que degrade a `HEAP_SCAN`. Los paths `BPLUS_*_RANGE_SCAN` llaman de verdad a
`index.range_search(start, end, include_start, include_end)` (`:786-795`) y los `*_LOOKUP` a
`index.search(...)` (`:775-778`). La única "mentira" posible es de omisión: el `EXPLAIN` con `OR`
dice `HEAP_SCAN` sin explicar el motivo (§3.3), y `DELETE`/`UPDATE` no planifican con índices en
absoluto (siempre `HEAP_SCAN`/`SEQUENTIAL_SCAN`, `:330, 394-396, 435-437, 502-504`), cosa que el
profesor puede señalar como oportunidad perdida (`DELETE FROM t WHERE id = 3` podría usar el hash
de la PK).

### 3.7 GUI

`frontend/src/panels/PlanPanel.tsx` consume bien `access_path`, `used_indexes`, `steps` (con
`reason` e `index`) y `runtime_steps` (`:27-77`), así que el trabajo del planner se ve en la GUI.
Dos detalles:

- `:39` usa `plan.used_indexes.map(...)` con `key={index}` sobre strings; para `INSERT`/`UPDATE`/
  `CREATE TABLE` el ejecutor envía `list(table.indexes)` que son **nombres** (strings), así que
  funciona, pero esos planes declaran índices "usados" sin haber usado ninguno
  (`query_executor.py:304, 506, 564`): el panel puede mostrar chips de índices en un INSERT, lo
  que es engañoso en una demo.
- `runtime_steps` en el panel sólo muestra tiempo/entrada/salida; `EXPLAIN` en SQL sí imprime el
  texto completo (`_render_plan`, `query_executor.py:697-737`). Vale la pena exponer el plan
  textual en la GUI para que la demo no dependa del panel de consultas.

---

## 4. Experimentos: qué falta y cómo medirlo bien

### 4.1 Cobertura de los 7 ejes del enunciado

| Eje | ¿Está? | Métrica / evidencia | Comentario |
|---|---|---|---|
| (a) Igualdad exacta | ✅ | `exact_hit`, `exact_miss` | **Sin baseline de scan lineal** |
| (b) Rango | ✅ | `range_search`, `range_search_materialized`, `range_search_raw_index` | el arreglo de justicia está a medias (falta baseline) |
| (c) Ordenamiento | ✅ | `ordered_scan` | **no** compara contra `External Sort` con el mismo N |
| (d) Tiempo de construcción | ✅ | `build` (×3 repeticiones) | sin *warm-up* ni desviación estándar |
| (e) Tiempo de consulta | ✅ | `avg_us`, `median_us`, `p95_us` | ✅ 500 consultas × 3 pasadas |
| (f) Espacio extra | ⚠️ | `serialized_size` (pickle) | **injusto para el agrupado**: mide el registro completo |
| (g) Inserciones/borrados frecuentes | ✅ | `insert`, `delete` | usa el mismo índice ya construido y valida al final |

Gráficas: `generate_charts.py` regenera `index_build_time`, `index_exact_lookup`,
`index_range_search`, `index_range_search_fair`, `index_ordered_scan`, `index_size`,
`index_mutations`, `index_dashboard` (`:281-435`). La gráfica *fair* existe y muestra las tres
variantes de rango (verificada, `benchmark_results/plots/index_range_search_fair.png`), pero
**no** incluye ninguna barra de scan lineal, que es la referencia que pide el enunciado.

### 4.2 Problemas metodológicos concretos

1. **Falta el baseline de scan lineal/secuencial (crítico).** No hay ninguna métrica que haga un
   `full scan` del mismo dataset con la misma clave y el mismo rango. Sin eso, las tablas del
   informe no permiten afirmar "el índice es X× mejor", que es el objetivo del apartado 2.1.6.
   *Cómo medirlo bien:* añadir al benchmark dos adaptadores "baseline": `linear_scan_equal`
   (recorrer la lista de registros comparando `record['id'] == key`) y
   `linear_scan_range` (recorrer y quedarse con `low <= key <= high`), sobre **la misma lista de
   registros ya construida** y con las **mismas** `existing_keys` y `ranges` (mismo
   `range_fraction`). Es ~30 líneas en `benchmark_indexes.py` (`_make_adapters`, `:193-268`) y
   dos series nuevas en `generate_charts.py`.
2. **La "materialización" del no agrupado se mide contra un `dict`** (`rid_to_record`,
   `benchmark_indexes.py:186-191` y `:671-676`), es decir el *fetch* por RID cuesta ~0. El propio
   informe dice que con `HeapFile` real el rango de 200 filas costó 23 837 µs contra 1 253 µs del
   agrupado (≈19×) (`conclusiones_experimentales.md:204-208`) — esa medición está hecha a mano y
   **no** está en el JSON. *Arreglo:* nueva métrica `range_search_materialized_real` usando
   `HeapFile.read` sobre un heap de prueba, o al menos mover esa medición al benchmark para que
   sea reproducible.
3. **Espacio extra injusto.** `serialized_size` picklea el objeto índice
   (`_serialized_size_bytes`, `:337-363`), y para el agrupado eso incluye todos los registros
   (4,71 MB a 100 000 contra 1,44 MB y 1,38 MB). El agrupado **no es "espacio extra"**: su
   estructura sustituye al heap. *Arreglo:* reportar dos columnas — (i) tamaño de la estructura
   de índice (clave + RID / clave + offset) y (ii) espacio total del índice `incluyendo` el
   payload, dejando claro en la nota que el agrupado reemplaza al heap.
4. **Falta la comparación directa con `External Sort`.** El eje (c) mide `ordered_scan` del
   índice, pero no mide `ExternalSort.sort` sobre los mismos datos. *Arreglo:* una métrica
   `external_sort` (llamando a `operators/external_sort.py` con el mismo N) y un gráfico
   "ordenar con índice vs. `External Sort`" para el mismo N; así se cuantifica la afirmación
   "el B+ evita el sort".
5. **Sin *warm-up* ni dispersión.** `_benchmark_build` mide 3 repeticiones y sólo reporta
   `total_ms` (`:280-310`); no hay primera pasada descartada ni desviación estándar/IC, y
   `query_repeats=3` (`:61`) mezcla 1 500 muestras por métrica sin reportar varianza. *Arreglo:*
   una pasada de calentamiento por adaptador, reportar `stdev`/`cv` y fijar en el JSON
   `platform`, `python_version`, `cpu` y `timestamp`. Nota: la caché del SO **no** se controla
   (el propio informe lo admite, `:248-250`), lo cual es aceptable si se dice.
6. **Números del informe ≠ JSON (B2).** Ejemplos: build 100 000 ms 14 566 (doc) vs 12 760 (JSON);
   B+ no agrupado igualdad hit 100 000 2,72 (doc) vs 2,13 µs (JSON); delete 100 000 36,89/47,57
   (doc) vs 33,30/50,45 µs (JSON). Hay que regenerar el documento desde el JSON o adjuntar el
   CSV/JSON como fuente de verdad con fecha y máquina.
7. **La configuración de comparación es "comparable" pero hay que explicarla:** `order=64` en B+
   y `bucket_capacity=64` en hash (`:63-64`), ambos 64 claves por nodo/bucket; el hash usa
   `hash_func=int` (`:253`) y el dataset tiene claves `0..N-1` más un `shuffle`, así que el hash
   ve claves "aleatorias" — razonable. El dataset usa `(i*37) % 100003` para `value`
   (`_make_dataset`, `:154-169`), que **genera valores repetidos** a partir de N>100 003; para
   las métricas de `id` no afecta.
8. **`_percentile` (`:116-128`)** usa el método del "índice más cercano hacia arriba", no
   interpolación: es correcto, pero debe documentarse (con 1 500 muestras no cambia nada).

### 4.3 Lo que sí está bien medido

Mismo dataset y mismo orden de inserción para los tres índices (`_make_dataset` con
`rng.shuffle` y `rng = random.Random(seed + size)`, `:154-169`), mismas consultas
(`existing_keys`, `missing_keys`, `ranges` generados una sola vez por N y usados por los tres
adaptadores, `:678-712`), `query_repeats=3` con `perf_counter_ns`, `build_repeats=3` con
`validate()` fuera del cronómetro (`:296-298`), y las mediciones de mutación validan la
estructura al terminar (`:605-607, 646-648`). Eso es más de lo que suele verse en proyectos
similares.

---

## 5. Lista priorizada de arreglos concretos

> Todos los cambios son localizados; las líneas son las del estado actual del repo.

### Prioridad 1 — Uso de índices en el planner (es lo que pidió el profesor)

1. **Componer intervalos sobre la misma columna** — `query_planner.py:276-332`.
   Propuesta: agrupar `query.predicates` por columna; si una columna tiene 2+ predicados de rango
   o una igualdad + rango, construir `start/end/include_start/include_end` y pasarlos al ejecutor.
   Mínimo viable: extender `_AccessCandidate` con `extra_predicates: Tuple[Predicate, ...]` y
   `_AccessCandidate.details["range"] = {"start":..,"end":..,"include_start":..,"include_end":..}`,
   consumir **todos** los predicados usados en `_residual_predicates` (`:431-443`) y que
   `_execute_access_path` (`query_executor.py:780-795`) lea ese rango compuesto en vez de
   `_range_bounds(predicate)`.
   *Efecto:* `WHERE age >= 19 AND age <= 23` deja de materializar todo el rango abierto y
   desaparece el `FILTER` redundante del `EXPLAIN`.
2. **`OR` con *index union*** — `query_executor.py:139-141` y `:633-635`, más planner.
   Propuesta: no borrar los predicados; en el planner, si `query.has_disjunction` y **cada**
   grupo tiene ≥1 predicado que un índice puede resolver, emitir un paso
   `INDEX_UNION_OR` con la lista de índices y predicados (`used_indexes` con todos); el ejecutor
   ejecuta cada rama con su índice, deduplica por RID y aplica el `FILTER` del OR como red de
   seguridad. Si alguna rama no tiene índice, mantener `HEAP_SCAN` **pero** añadir un `FILTER`
   al plan con `details.disjunction=True` y un `reason` del tipo
   `"OR: no todas las ramas tienen índice, se usa scan"`. Hoy el `EXPLAIN` no explica nada.
3. **Corregir el *tie-break* de orden** — `query_planner.py:324-332`.
   Propuesta: elegir por `(preserva_orden_si_order_by_obligatorio, score, kind_priority)`;
   alternativamente, aplicar `_order_bonus` (`:373-382`) también cuando el índice está en la
   columna del `ORDER BY` aunque el predicado consumido sea de otra columna, y subir el bonus para
   que domine la diferencia hash(110) vs B+(70). Actualizar el test
   `test_query_planner.py:703-735`, que hoy fija el desempate actual.
   *Efecto verificado que se busca:* `WHERE id = 3 ORDER BY salary` (con B+ agrupado sobre
   `salary`) debería dar `BPLUS_CLUSTERED_INDEX_SCAN + FILTER` en vez de
   `HASH_INDEX_LOOKUP + EXTERNAL_SORT`.
4. **`LIMIT` empujado al índice** — `query_executor.py:220-231` y `query_planner.py:249-267`.
   `BPlusTree.range_search`/`scan` ya aceptan `limit` (`bplus_tree.py:275-306`); `scan` no lo
   acepta en `ClusteredBPlusIndex.scan` (`:66-67`) pero `range_search(limit=...)` sí. Propuesta:
   pasar `statement.limit` como `limit` del path de acceso cuando no hay `FILTER` ni `ORDER BY`
   pendientes, y saltar el recorte posterior. Hoy `SELECT * FROM t WHERE age > 0 LIMIT 10`
   materializa toda la tabla.

### Prioridad 2 — Correctitud de borde y defensa

5. **Rechazar/handling de `NULL` en columnas indexadas** — `query_executor.py:1053-1092`
   (usar `.get(meta.column)` + validar `is None` y lanzar `QueryExecutionError` claro antes de
   tocar el índice y antes del `pack`), `extendible_hash.py:45-53, 80-105` (rama explícita
   `if key is None`), `bplus_tree.py:53-64` (idem: hoy `search(None)` lanza
   `TypeError: '<' not supported between instances of 'NoneType' and 'int'`). Y en el
   parser/README: declarar `NULL` fuera de alcance o implementar la semántica de tres valores.
   Mínimo: un test que verifique un error legible en lugar de `TypeError`/`IndexError`.
6. **Cerrar la trampa `unique` metadatos vs implementación** — `catalog.py:344-351`.
   Propuesta: `inferred_unique = getattr(implementation, "unique", False)` **siempre** y lanzar
   `CatalogError` si `unique is not None and bool(unique) != inferred_unique`.
7. **Documentar el contrato índice↔almacenamiento** — nuevo bloque en
   `docs/guia_issues_y_entregables.md` (sección "contrato de integración", ya existe para el
   secuencial) y comentario en `clustered_bplus.py:1-10`: *el B+ agrupado es la fuente de verdad
   de sus registros; ninguna mutación puede tocar el almacenamiento sin actualizar/reconstruir el
   índice*. Añadir un test que lo demuestre (estilo `.review_tmp/probe_misc.py`).
8. **Marcar los índices como en memoria** — README (§7) y docstrings de los tres módulos:
   "estructura en memoria; no persiste; se reconstruye al arrancar (`Catalog.rebuild_index`)".

### Prioridad 3 — Experimentos

9. **Baselines de scan lineal** (`benchmark_indexes.py:193-268` + `generate_charts.py:281-435`):
   métricas `linear_scan_equal`, `linear_scan_range` con el mismo dataset y las mismas claves.
10. **Materialización real por RID**: añadir `range_search_materialized_real` leyendo de un
    `HeapFile` temporal (o reutilizar la medición manual de `conclusiones_experimentales.md:204-208`
    y convertirla en benchmark reproducible).
11. **Métrica `external_sort`** para el eje (c) y un gráfico índice-vs-sort.
12. **Espacio en dos columnas** (estructura vs estructura+payload) y nota explícita de que el
    agrupado reemplaza al heap.
13. **Robustez estadística**: *warm-up*, `stdev`/`cv`, y metadatos de máquina/fecha/versión de
    Python en el JSON; regenerar `docs/conclusiones_experimentales.md` desde el JSON vigente
    (los números actuales no coinciden).
14. **`_split_bucket` con `assert` defensivo** (`extendible_hash.py:155-157`): antes de asignar,
    comprobar que la clave no existe ya en `target.records` (protege contra futuros cambios de la
    función hash) y bajar el `max_depth` por defecto a algo defendible (p. ej. 32) o validar
    `2^max_depth` contra un límite de directorio.

### Prioridad 4 — Rendimiento y claridad (no bloquean la nota)

15. **`deepcopy` opcional en `ClusteredBPlusIndex`** (`:40, 47, 64`): parámetro
    `copy_records=True` y en el benchmark usar `copy_records=False` para medir el algoritmo; el
    propio informe identifica esta mejora (`conclusiones_experimentales.md:253-255`).
16. **`_execute_insert` del archivo secuencial reconstruye TODOS los índices por cada INSERT**
    (`query_executor.py:266-273`, vía `catalog.rebuild_indexes` → escaneo completo,
    `catalog.py:425-428`): convierte `INSERT` en O(N). Es la causa de que cargar 100 000 filas en
    `employees` sea inviable. Propuesta: no reindexar si el índice es de tipo hash/agrupado sobre
    columna que no cambia de posición (sólo los **no agrupados** dependen del RID) o reconstruir
    una sola vez al terminar el lote/import.
17. **Unificar `query/executor.py` y `query/query_executor.py`** (el primero es un motor antiguo
    completo de 668 líneas que nadie usa desde `backend/engine.py:23`): el profesor puede abrir el
    archivo equivocado en la demo.
18. **`query_planner.py:3`**: el docstring dice "Igualdad: Hash > B+ clustered > B+ unclustered";
    con el bonus de orden eso deja de ser cierto en algunos casos (ver 3.4). Alinear código y
    comentario.

---

## 6. Riesgos en la defensa oral

| Pregunta probable del profesor | Qué responder / riesgo |
|---|---|
| *"Explícame por qué `WHERE age >= 19 AND age <= 23` usa el índice y luego filtra. ¿No sabe el índice hacer rango cerrado?"* | **Riesgo alto.** Hay que reconocer que el planner empareja 1 predicado ↔ 1 índice (`query_planner.py:280-289`) y que `range_search` sí acepta ambos extremos (`bplus_tree.py:275`). Es el arreglo #1 de §5. No improvisar: mostrarlo como limitación conocida con plan de arreglo y decir que `BETWEEN` ya lo hace bien. |
| *"¿Por qué un `OR` no usa ningún índice? El README dice que OR está soportado."* | **Riesgo alto.** La respuesta honesta: el ejecutor borra los predicados al planificar (`query_executor.py:140`), por eso el plan es `HEAP_SCAN`; OR está soportado *semánticamente* (resultados correctos) pero no *físicamente*. Tener preparada la explicación de *index union* y por qué hoy no está. |
| *"El B+ agrupado tiene que ser el mejor en igualdad; ¿por qué tu gráfica dice que es el peor?"* | Responder con §3.4 del propio informe: el `deepcopy` de la capa de acceso (`clustered_bplus.py:40,47,64`) domina el tiempo, y la métrica `range_search_raw_index` (sin copia) lo demuestra (935 µs vs 1 108 µs). Es bueno que la medición exista; **malo** que la métrica principal del gráfico siga siendo la que incluye la copia. |
| *"¿Contra qué estás comparando? ¿Cuánto mejora el índice frente a un scan lineal?"* | **Riesgo alto (falta el baseline).** Hoy no hay respuesta numérica reproducible; sólo la afirmación "el scan del heap crece linealmente" medida en el benchmark de archivos. Arreglo #9. |
| *"¿Dónde está el índice en disco? ¿Qué pasa si reinicio?"* | Responder: los índices son **en memoria** (`indexes/` no serializa nada) y el catálogo persiste sólo metadatos; al arrancar se reconstruyen con `Catalog.rebuild_index` (`catalog.py:385-428`). Hay que decirlo **antes** de que lo pregunten, y reconocer el costo O(N) de arranque. |
| *"¿Cómo manejas claves duplicadas en el B+ no agrupado?"* | Responder bien: lista de RIDs por clave (`bplus_tree.py:70-71`), `delete(key, rid)` borra un RID; `validate()` además prohíbe claves duplicadas como entradas separadas (`:365-366`). Punto fuerte. |
| *"¿Y NULL? `WHERE x = NULL`."* | **Riesgo medio-alto.** Verificado: con un B+ indexado, `search(None)` lanza `TypeError: '<' not supported between instances of 'NoneType' and 'int'` (no un resultado vacío); el hash acepta `None` como clave; y `INSERT ... NULL` en una columna INT indexada falla en `storage/record.py:58` con `TypeError` y rollback. Responder que NULL está fuera del subconjunto soportado (los tipos son INT/FLOAT/VARCHAR) y que el arreglo es explícito (arreglo #5). No decir "no pasa nada": se puede reproducir en 5 segundos. |
| *"¿Por qué fusionas buckets al borrar en el hash extendible? Eso no está en el libro."* | **Riesgo medio.** El hashing extendible estándar no fusiona. Explicar que es una extensión propia para evitar que el directorio crezca sin control, con la condición de fusión (misma `local_depth` + claves combinadas ≤ capacidad, `extendible_hash.py:198-245`) y que hay tests; reconocer que **no** está en Ramakrishnan y que la operación es O(2^d) por el recorrido del directorio (`:241-243`). Si no se puede explicar con seguridad, ofrecer desactivarla con un flag y documentarlo como extensión. |
| *"¿Cómo garantizas que el índice no quede desactualizado?"* | Explicar el invariante: `INSERT` → `_index_insert` con rollback; `DELETE` → `_index_delete`; `UPDATE` → `rebuild_indexes` completo; `SequentialFile.reorganizar()` → `rebuild_indexes` (`query_executor.py:273, 371, 475, 484`). Reconocer que es frágil (todo depende del ejecutor) y que el B+ agrupado guarda copias, por lo que una mutación externa al ejecutor produce lecturas obsoletas (demostrable con `.review_tmp/probe_misc.py`). |
| *"¿Por qué el `EXPLAIN` de un `INSERT` muestra 'índices usados'?"* | Es `used_indexes: list(table.indexes)` (`query_executor.py:304`), es decir *declarados*, no *usados*; en la GUI aparecen chips de índices en un INSERT (`PlanPanel.tsx:39`). Corregir o explicar. |
| *"¿Qué significa `order=4` en tu B+? ¿Cuántas claves caben por nodo?"* | Responder: `order` = máximo de **hijos** en un nodo interno = máximo de claves+1; las hojas guardan hasta `order-1` claves (`bplus_tree.py:25-34`). Es la convención del libro, pero no está documentada en el README: añadirlo. |
| *"¿Cuál es el mínimo de claves de una hoja y por qué `ceil((order-1)/2)`?"* | Explicar que con esa fórmula el split `(n+1)//2` nunca deja un lado por debajo del mínimo; señalar la asimetría con `min_internal_children = ceil(order/2)` (`:29-34`) y normalizarla si se quiere una respuesta limpia. |
| *"Muéstrame un `EXPLAIN` que demuestre que evitas el sort."* | `ORDER BY age` sobre `idx_probe_age_bplus` da `BPLUS_CLUSTERED_INDEX_SCAN` sin `EXTERNAL_SORT`; `ORDER BY age DESC` da `HEAP_SCAN + EXTERNAL_SORT`. **Cuidado:** no existe *reverse scan* (`query_planner.py:294-298`), así que `DESC` siempre ordena; decirlo antes de que lo pregunten. Y si aparece un `WHERE` de igualdad por hash junto a un `ORDER BY` con índice B+ en otra columna, el plan **sí** ordena (ver §3.4): hay que saber explicar por qué. |
| *"¿Por qué el `delete` de tu B+ a 100 000 crece más que el del hash?"* | Responder con el rebalanceo (redistribución/fusión en cascada, `bplus_tree.py:183-273`) contra O(1) del hash; los números del JSON (33,30/50,45/7,77 µs) y la nota de que la altura es logarítmica. |
| *"¿Cómo sé que tus números del informe son los del benchmark?"* | Hoy **no** coinciden con el JSON (B2). Regenerar el documento desde `benchmark_results/index_benchmark.json` antes de la entrega. |
| *"Enséñame el índice en la GUI."* | El panel de plan muestra ruta de acceso, índices usados, plan lógico con justificación y traza real (`PlanPanel.tsx:27-77`); el panel de archivos muestra índices por tabla (`README.md:322`). Ojo con los chips engañosos del INSERT (§6, pregunta 10). |

---

### Anexo: scripts de verificación usados (sólo lectura, en `.review_tmp/`)

| Script | Qué demuestra |
|---|---|
| `.review_tmp/probe_bplus.py` | B+ contra modelo de referencia: 7 órdenes × 4 semillas × 3 000 ops, con `validate()` → 0 fallos |
| `.review_tmp/probe_hash.py` | Hash extendible contra `dict`: 300 semillas × capacidades 2/3/4 × 400 ops → 0 fallos |
| `.review_tmp/probe_engine.py` | Planes reales de 16 consultas + `EXPLAIN`/`EXPLAIN ANALYZE` (§3.1–3.4) |
| `.review_tmp/probe_null.py`, `probe_types2.py` | NULL en columna indexada (errores crudos), `int`/`float` en hash, divergencia índice↔storage |
| `.review_tmp/probe_stale.py` | `DELETE` + reuso de slot: índices coherentes; B+ agrupado obsoleto si se muta por fuera |
| `.review_tmp/probe_misc.py` | Crecimiento del directorio del hash (d=11 a 100 000) y registro congelado del agrupado |
| `.review_tmp/probe_cost.py` | Construcción/inserción/borrado por estructura a 2 000/4 000/8 000 |
| `python -m pytest tests/test_{bplus_tree,clustered_bplus,unclustered_bplus,extendible_hash,query_planner}.py -q` | **105 passed** |
