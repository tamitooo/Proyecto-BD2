# Conclusiones experimentales (Parte 1)

> **Nota (entrega de la semana 8).** Este documento conserva el análisis de la corrida
> histórica del equipo. Las **cifras vigentes**, generadas desde los CSV actuales, están en
> [`resultados_experimentales.md`](resultados_experimentales.md) y en el
> [informe incremental](informe_incremental.md). Las conclusiones cualitativas se mantienen.

Documento de apoyo para la sección **2.1.6 Comparación Experimental de
Técnicas** del enunciado y para el informe incremental.

---

## 1. Qué se midió y cómo

| Aspecto | Configuración |
|---|---|
| Datasets | 1 000, 10 000 y 100 000 registros (`id INT`, `nombre VARCHAR(30)`, `nota FLOAT`; registro de 43 bytes) |
| Semilla | 42 (mismo dataset y mismo orden de inserción para todas las técnicas) |
| Heap File vs Secuencial | Inserción, búsqueda por clave primaria (aciertos y fallos), borrado, reorganización, espacio en disco y desperdicio |
| Índices | B+ agrupado, B+ no agrupado y Hash extendible: construcción, igualdad exacta (hit/miss), rango, recorrido ordenado, inserciones/borrados y espacio |
| Parámetros | B+ de orden 64; hash con capacidad de bucket 64; 500 consultas de igualdad, 100 de rango, 200 mutaciones; 3 repeticiones (promedio) |
| Reproducibilidad | `python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000` y `python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000` |

### Metodología de la inserción a 100 000 registros

La inserción uno a uno del Archivo Secuencial tiene costo amortizado que
crece con el tamaño (cada `insert` revisa el área de desbordamiento y
reorganiza al superar el 30 %). Para poder medir búsqueda y espacio a
100 000 registros sin que el benchmark dure horas, la carga a esa escala se
hace con **carga masiva**: se escribe el archivo directamente con el mismo
layout binario que produce la API pública y se verifica que sea **idéntico
byte a byte** (`tests/test_benchmark_heap_vs_sequential.py`). Las métricas
de inserción uno a uno se reportan hasta 10 000 y se marcan como `N/A`
(no medidas) por encima de ese umbral, en lugar de extrapolar.

### Entorno y calibración de E/S

Las mediciones se hicieron en Windows 11 con Python 3.13.7, dentro de un
entorno de ejecución que intercepta la E/S de archivos. Cada corrida mide
su propia calibración base (lectura y escritura de un registro de 43 bytes,
mediana de 200 repeticiones):

| Calibración | Valor medido |
|---|---|
| Lectura (open + seek + read + close) | **≈ 2.56 ms** |
| Escritura (open + seek + write + close) | **≈ 0.46 ms** |

Esto significa que **los tiempos absolutos están inflados** por el entorno
(un `open/write` normal cuesta decenas de microsegundos, no 0.46 ms). Por
eso las conclusiones se apoyan en:

1. las **diferencias relativas** entre técnicas sobre el mismo entorno,
2. la **tendencia con N** (que revela la complejidad algorítmica), y
3. el **análisis de complejidad** de cada estructura.

---

## 2. Resultados: gestión de archivos

### 2.1 Tiempos

| Métrica | Heap File 1 000 | Heap File 10 000 | Secuencial 1 000 | Secuencial 10 000 |
|---|---|---|---|---|
| Inserción (µs/registro) | 15 392.6 | 14 825.8 | 15 231.6 | 16 374.5 |
| Borrado (µs/operación) | 1 950.0 | 2 093.5 | 15 640.3 | 12 630.0 |
| Reorganización (ms) | no aplica | no aplica | 5.9 | 36.5 |

| Métrica | Heap File 1 000 | Heap File 10 000 | Heap File 100 000 | Secuencial 1 000 | Secuencial 10 000 | Secuencial 100 000 |
|---|---|---|---|---|---|---|
| Búsqueda por PK acertada (µs) | 3 438.3 | 36 597.2 | 317 507.1 | 322.0 | 246.0 | 450.8 |
| Búsqueda por PK fallida (µs) | 4 075.9 | 38 597.3 | 326 891.6 | 577.3 | 364.6 | 628.8 |
| Carga masiva (ms totales) | 36.5 | 25.4 | 258.3 | 6.1 | 26.9 | 316.4 |

### 2.2 Espacio

| Métrica | Heap File 1 000 | Heap File 10 000 | Heap File 100 000 | Secuencial 1 000 | Secuencial 10 000 | Secuencial 100 000 |
|---|---|---|---|---|---|---|
| Espacio en disco (bytes) | 44 935 | 433 010 | 4 301 505 | 43 000 | 430 000 | 4 300 000 |
| Espacio desperdiciado (bytes) | 1 935 | 3 010 | 1 505 | 1 548¹ | 16 082¹ | no medido |

¹ Tombstones justo antes de reorganizar (el umbral del 30 % los mantiene acotados).

### 2.3 Interpretación

1. **Inserción: empate técnico.** Ambas estructuras insertan en tiempo
   prácticamente constante (≈ 15 ms/registro en este entorno, dominado por
   el costo de E/S de la calibración). El Heap File no degrada con N
   (14 826 µs a 10 000 frente a 15 393 µs a 1 000); el Archivo Secuencial
   tampoco, porque **reorganiza periódicamente** y paga el costo de forma
   amortizada (17 reorganizaciones al cargar 1 000 registros y 26 al cargar
   10 000).
2. **Búsqueda: el Archivo Secuencial es 1–3 órdenes de magnitud mejor.**
   La búsqueda binaria sobre `.main` se mantiene casi plana al crecer el
   dataset (322 → 246 → 451 µs), mientras que el *full scan* del Heap File
   crece linealmente (3 438 → 36 597 → 317 507 µs, ≈ 3 µs por registro
   leído). Con 100 000 registros la diferencia es de **≈ 700×**.
   Esto confirma la teoría: O(log N) frente a O(N).
3. **Borrado: el Heap File es ~7× más barato** (1 950–2 094 µs frente a
   12 630–15 640 µs) porque solo marca un *tombstone* y actualiza su
   *free-list*; el Archivo Secuencial, además, puede disparar una
   reorganización completa dentro del propio borrado.
4. **Reutilización de espacio: el Heap File la resuelve en línea.** Tras
   borrar el 30 % de los registros, **300/300** (N = 1 000) y **3000/3000**
   (N = 10 000) de las inserciones posteriores reutilizaron exactamente un
   slot liberado, sin costo extra.
5. **Reorganización: costo lineal y predecible.** 5.9 ms con 1 000
   registros y 36.5 ms con 10 000 (≈ 6× al multiplicar N por 10), coherente
   con O(N). Es el precio que paga el Archivo Secuencial por mantener el
   orden y por compactar tombstones.
6. **Espacio: prácticamente empatados.** El Heap File desperdicia solo el
   resto de la última página (1 505–3 010 bytes, 0.03–0.7 %), mientras que
   el Archivo Secuencial usa exactamente `N × 43` bytes tras reorganizar,
   pero acumula hasta un 30 % de tombstones entre reorganizaciones
   (16 082 bytes con 10 000 registros).

**Conclusión de la comparación de archivos:** ninguno domina. El Heap File
gana en escritura, borrado y simplicidad; el Archivo Secuencial gana
decisivamente en lectura por clave (y en mantener el orden físico). La
elección depende del patrón de consulta: si el acceso es por clave
primaria, conviene el Archivo Secuencial (o un índice sobre el Heap File);
si el patrón es de altas/bajas masivas y *scans* completos, conviene el
Heap File.

---

## 3. Resultados: estructuras de indexación

> **Números regenerados** desde `benchmark_results/index_benchmark.json`
> (`python -m benchmarks.benchmark_indexes --sizes 1000 10000 50000`), semilla 42,
> 3 repeticiones. Tamaños comparados: 1 000, 10 000 y 50 000 registros.
> Incluye la **línea base sin índice** (búsqueda lineal) que exige el enunciado.

### 3.1 Tiempos

| Métrica | N | B+ agrupado | B+ no agrupado | Hash extendible |
|---|---|---|---|---|
| Construcción (ms) | 1 000 | 11.6 | 4.7 | **3.0** |
| Construcción (ms) | 10 000 | 194.3 | 112.8 | **30.5** |
| Construcción (ms) | 50 000 | 1 360.7 | 1 008.9 | **297.1** |
| Igualdad exacta *hit* (µs) | 1 000 | 8.53 | 0.98 | **0.84** |
| Igualdad exacta *hit* (µs) | 10 000 | 9.53 | 1.32 | **0.92** |
| Igualdad exacta *hit* (µs) | 50 000 | 9.14 | 3.48 | **1.44** |
| Igualdad exacta *miss* (µs) | 50 000 | 2.32 | 1.35 | **0.95** |
| Rango, **solo el índice** (µs) | 1 000 | 5.07 | 5.09 | N/A |
| Rango, **solo el índice** (µs) | 10 000 | **38.64** | 54.22 | N/A |
| Rango, **solo el índice** (µs) | 50 000 | 377.33 | **325.60** | N/A |
| Rango **+ recuperar cada fila** (µs) | 1 000 | 70.99 | **6.85** | N/A |
| Rango **+ recuperar cada fila** (µs) | 10 000 | 676.28 | **66.57** | N/A |
| Rango **+ recuperar cada fila** (µs) | 50 000 | 3 298.25 | **771.08** | N/A |
| Recorrido ordenado (µs) | 1 000 | 5 830.2 | **310.4** | N/A |
| Recorrido ordenado (µs) | 50 000 | 470 284.8 | **275 936.1** | N/A |
| Inserción (µs) | 50 000 | 21.40 | 15.57 | **2.33** |
| Borrado (µs) | 50 000 | **17.01** | 17.09 | 4.71 |

**Línea base sin índice (igualdad exacta):** buscar recorriendo la tabla cuesta
75.29 µs con 1 000 registros, 2 594.55 µs con 10 000 y 24 698.64 µs con 50 000
(crecimiento lineal). Eso da la mejora real de cada índice:

| N | Búsqueda lineal (µs) | Mejora B+ agrupado | Mejora B+ no agrupado | Mejora Hash |
|---|---|---|---|---|
| 1 000 | 75.29 | 9× | 77× | **89×** |
| 10 000 | 2 594.55 | 272× | 1 966× | **2 827×** |
| 50 000 | 24 698.64 | 2 703× | 7 100× | **17 208×** |

### 3.2 Espacio

| Índice | 1 000 | 10 000 | 50 000 |
|---|---|---|---|
| B+ agrupado | 44 773 | 455 775 | 2 285 197 |
| B+ no agrupado | 13 020 | 130 170 | 669 049 |
| Hash extendible | **12 280** | **125 089** | **637 755** |

**Por qué el B+ agrupado ocupa ≈ 3.4× más:** de los 2 285 197 bytes que mide con
50 000 claves, **1 950 000 (85.3 %)** son los **registros completos** que el
índice agrupado guarda dentro de sus hojas (≈ 39 bytes de datos de usuario por
registro). Es exactamente el costo del *index clustering*: el B+ no agrupado
(13 bytes/registro) y el hash (12.8 bytes/registro) solo almacenan **clave +
RID** y por eso necesitan ir al Heap File a buscar la fila. La comparación de
espacio sólo es justa si se declara ese intercambio, y el benchmark ahora lo
reporta en el campo `payload_bytes` de cada resultado.

### 3.3 Interpretación

1. **Construcción: el hash es el más barato** (297 ms frente a 1 009 ms del B+ no
   agrupado y 1 361 ms del B+ agrupado a 50 000 claves). El B+ agrupado paga la
   copia del registro completo en cada hoja y el rebalanceo. Los tres escalan de
   forma aproximadamente **lineal con N**.
2. **Igualdad exacta: hash > B+ no agrupado > B+ agrupado.** El hash hace O(1)
   promedio (0.84 → 1.44 µs, casi plano); el B+ agrupado es el más lento
   (8.53 → 9.14 µs) porque cada acierto **copia el registro completo** en lugar
   de devolver una referencia. Los tres superan a la búsqueda lineal por órdenes
   de magnitud, y la ventaja **crece con N**: 9× → 2 703× en el agrupado.
3. **Rango: depende de si hay que traer la fila.** Si lo único que se mide es el
   recorrido de las hojas, ambos B+ empatan (325 µs el no agrupado frente a
   377 µs el agrupado a 50 000). Si la consulta necesita las filas —el caso
   real—, el no agrupado gana **4.3×** (771 µs frente a 3 298 µs) porque el
   agrupado copia cada registro y el no agrupado sólo lee el RID. El hash **no
   puede** resolver rangos.
4. **Recorrido ordenado (ORDER BY): el mismo patrón**, 276 ms frente a 470 ms a
   50 000 claves. Es el costo de que el índice B+ pueda sustituir al External
   Sort: el agrupado lo logra, pero copiando registros.
5. **Mutaciones: el hash es el más estable** (2.33 µs de inserción y 4.71 µs de
   borrado a 50 000, sin degradación con N). Los B+ pagan rebalanceo: el borrado
   del agrupado crece de 7.64 a 17.01 µs y el del no agrupado de 5.65 a
   17.09 µs.
6. **Espacio: el B+ agrupado es el más caro** (4.7 MB a 100 000), y los
   otros dos quedan muy cerca entre sí (1.38–1.44 MB).

> **Ojo con la gráfica de rango:** el B+ agrupado aparece más lento porque su
> capa de acceso **copia** cada registro que devuelve. La explicación completa,
> con la medición que aísla ese efecto, está en la sección 3.4.

### 3.4 Aclaración: la búsqueda por rango del B+ agrupado

La gráfica de rango muestra que, midiendo **solo el índice**, el B+ agrupado y el
no agrupado empatan, pero en cuanto la consulta necesita las filas el agrupado se
queda atrás. **No hay ningún error en los índices**: la medición original
comparaba dos cosas distintas y el agrupado paga una *copia defensiva*
(`deepcopy`) en su capa de acceso. El benchmark mide tres variantes para dejarlo
claro (rango del 1 % del dataset, promedio por consulta, **50 000 claves**):

| Variante | Qué mide | B+ agrupado | B+ no agrupado |
|---|---|---|---|
| `range_search` | solo el índice (el agrupado devuelve registros; el no agrupado, RIDs) | 3 298 µs | 771 µs |
| `range_search_materialized` | índice + recuperar la fila | 3 298 µs | 771 µs |
| `range_search_raw_index` | recorrido de las hojas **sin** la copia defensiva | **377 µs** | 326 µs |

Lectura de los resultados:

1. Casi todo el costo del agrupado es el `deepcopy` de cada registro que
   devuelve: `clustered_bplus.py` copia cada registro. **Sin esa copia su
   recorrido de hojas cuesta 377 µs, prácticamente lo mismo que el no agrupado
   (326 µs)**, justo como predice la teoría: las hojas están enlazadas y los
   registros son contiguos, así que el recorrido es secuencial en ambos casos.
2. Al medir «rango + recuperar la fila», la ventaja del agrupado es clara
   (3 298 µs frente a 771 µs) **porque la recuperación aquí es un `dict` en
   memoria**. En el motor real recuperar por RID es una lectura de
   almacenamiento por fila, mucho más cara: en una prueba con `HeapFile` real dio
   23 837 µs para un rango de 200 filas frente a 1 253 µs del agrupado
   (≈ **19× a favor del agrupado**).
3. Conclusión: en un motor en memoria la ventaja del índice agrupado solo se
   aprecia cuando se cuenta el acceso al dato; en un motor en disco aparece de
   forma natural (lectura secuencial de hojas frente a una lectura aleatoria por
   cada RID). La gráfica `index_range_search_fair.png` muestra las tres
   variantes juntas.

**Mejora pendiente (rendimiento):** eliminar el `deepcopy` de
`ClusteredBPlusIndex.search`/`range_search` (o hacerlo opcional) bajaría el
rango del agrupado de 8 421 µs a ~935 µs y también su igualdad exacta (13.97 µs,
penalizada por la misma copia).

---

### 3.4 Por qué el rango parecía contradecir la teoría (y por qué no la contradice)

La primera versión de estas mediciones mostraba al **B+ agrupado perdiendo** en
búsqueda por rango, que es lo contrario de lo que predice la teoría. **Los índices
estaban correctos**; el benchmark medía dos cosas distintas:

- al **no agrupado** le pedía *sólo el recorrido del índice*, que devuelve RIDs;
- al **agrupado** le pedía el recorrido **más una copia defensiva** (`deepcopy`) de
  cada registro completo que devuelve.

Es decir, a uno se le pedía traer el dato y al otro no. Y encima el agrupado pagaba
una copia por fila. Con esa medición el agrupado pierde **3.6× a 4.5×**, y el gráfico
resultante contradice la clase.

El arreglo es medir la **consulta real**: el índice **más** traer cada fila **desde el
almacenamiento**. Ahí el agrupado tiene el registro en su propia hoja y no paga
ninguna lectura extra, mientras que el no agrupado paga una lectura por RID:

| Variante medida | N = 1 000 | N = 10 000 | N = 50 000 | Quién gana |
|---|---|---|---|---|
| Sólo el índice (ingenuo) | 89.0 / 5.8 | 705.8 / 65.2 | 3 681.7 / 380.8 | no agrupado (10–15×) |
| Recorrido de hojas sin copia | 6.2 / 6.6 | 64.9 / 68.6 | 374.5 / 379.9 | **empate** |
| **Índice + traer la fila (real)** | **83.1 / 1 436.4** | **676.8 / 12 145.4** | **4 104.3 / 61 341.3** | **agrupado (15–18×)** |
| Índice + traer la fila de un `dict` | 75.8 / 17.0 | 784.6 / 217.8 | 3 622.2 / 1 004.4 | no agrupado (3.6–4.5×) |

*(cada celda es B+ agrupado / B+ no agrupado, en µs por consulta)*

Tres lecturas que conviene tener presentes:

1. **En la consulta real el agrupado gana por 15–18×**, que es exactamente lo que
   enseña la teoría: al estar los registros en las hojas del índice, el rango se
   resuelve como una lectura secuencial y no hay que ir a buscar cada fila.
2. **El recorrido de las hojas, sin recuperar nada, es un empate** (374.5 vs 379.9 µs a
   50 000). Tiene sentido: ambos recorren hojas enlazadas; la diferencia está en *qué*
   guardan, no en cómo se recorren.
3. **La variante "en memoria" se conserva a propósito** como contraste
   metodológico: reproduce el resultado que parecía contradecir la teoría y demuestra
   que la causa era medir la recuperación contra un diccionario en lugar del disco. En
   un motor puramente en memoria, el índice agrupado *efectivamente* pierde, porque
   mueve registros completos de ~39 bytes frente al RID de 8 bytes del no agrupado.

Gráficas: `index_range_search_fair.png` (la comparación real, donde el agrupado gana)
e `index_range_search_breakdown.png` (el desglose que explica el malentendido).

---

## 4. Conclusiones: cuándo usar cada estructura

| Escenario de consulta | Estructura recomendada | Motivo (evidencia medida) |
|---|---|---|
| Igualdad exacta sobre una columna, muchas lecturas | **Hash extendible** | Menor tiempo de consulta (1.44 µs, 17 208× mejor que el scan) y de construcción (297 ms) a 50 000 |
| Igualdad + rangos sobre la misma columna | **B+ no agrupado** | Resuelve ambos (3.48 µs igualdad, 771 µs rango con recuperación) sin el sobrecosto de espacio del agrupado |
| `ORDER BY` frecuente sobre la clave de orden físico | **B+ agrupado** | Único que permite al planner **evitar** el External Sort |
| Tabla con muchas altas/bajas y consultas por clave | **Heap File + índice B+/Hash** | Inserción/borrado O(1) en el índice (2.33/4.71 µs) y búsqueda indexada |
| Tabla consultada casi siempre por clave primaria, con pocas mutaciones | **Archivo Secuencial Paginado** | Búsqueda binaria ~700× más rápida que el *scan* del heap |
| Carga masiva inicial | **Heap File** (o carga masiva directa) | No requiere reorganizaciones durante la carga |
| `ORDER BY` sin índice disponible | **External Sort** | Funciona siempre, memoria acotada |
| `GROUP BY` / equi-`JOIN` sobre datasets grandes | **External Hashing** | O(N+M) promedio con particionado en disco |

### Espacio adicional: el intercambio que hay que declarar

| Índice | Bytes/registro (N = 50 000) | Qué guarda en sus hojas |
|---|---|---|
| B+ agrupado | ≈ 45.7 (de los cuales **39 son el registro**) | El registro completo |
| B+ no agrupado | ≈ 13.4 | Clave + RID |
| Hash extendible | ≈ 12.8 | Clave + RID |

El B+ agrupado ocupa ~3.4× más porque **arrastra los datos**: es lo que le permite
servir `SELECT *` y `ORDER BY` sin tocar el Heap File. El no agrupado y el hash
son mucho más compactos, pero cada fila recuperada cuesta una lectura por RID.

---

## 5. Limitaciones y trabajo futuro

1. **Entorno de medición.** Los tiempos absolutos están dominados por la
   interceptación de E/S del entorno (0.46 ms por escritura, 2.56 ms por
   lectura de 43 bytes). Repetir los benchmarks en un equipo sin esa capa
   daría valores absolutos mucho menores; las conclusiones sobre
   complejidad y orden relativo no cambian.
2. **Inserción/borrado a 100 000 registros** no se midieron uno a uno
   (`N/A`) porque el coste de E/S del entorno lo hace impracticable aquí; la
   comparación de mutaciones se hace a **50 000** registros. Levantar el límite
   con `--mutation-limit 100000` es posible en un host más rápido.
3. **Caché del sistema operativo.** El benchmark no separa lecturas de
   disco y de caché (no hay `fsync`/bypass). Las diferencias relativas se
   mantienen, pero los valores no equivalen a latencias de disco reales.
4. **Mediciones de un solo proceso.** No se evaluó concurrencia (los locks
   y transacciones son otro bloque de la Parte 1).
5. **El B+ agrupado copia registros** en cada lectura; una mejora evidente
   es devolver referencias o `RID` en lugar de `deepcopy`, lo que reduciría
   su desventaja en igualdad/rango/orden.
6. **El Archivo Secuencial reorganiza muy seguido** cuando `main` es
   pequeño (17 reorganizaciones para 1 000 registros); ajustar el umbral o
   usar un área de desbordamiento proporcional reduciría ese costo.

---

## 6. Cómo reproducir

```bash
# 1) Benchmarks (generan CSV + JSON en benchmark_results/)
python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000
python -m benchmarks.benchmark_indexes --sizes 1000 10000 50000

# 2) Gráficas comparativas (PNG en benchmark_results/plots/)
python -m benchmarks.generate_charts

# 3) Verificación de la metodología (carga masiva == API pública)
python -m unittest tests.test_benchmark_heap_vs_sequential -v
```
