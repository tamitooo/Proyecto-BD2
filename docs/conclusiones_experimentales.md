# Conclusiones experimentales (Parte 1)

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

### 3.1 Tiempos

| Métrica | N | B+ agrupado | B+ no agrupado | Hash extendible |
|---|---|---|---|---|
| Construcción (ms) | 1 000 | 44.2 | 18.1 | **14.7** |
| Construcción (ms) | 10 000 | 620.6 | 475.9 | **150.8** |
| Construcción (ms) | 100 000 | 14 566.2 | 8 911.6 | **2 759.7** |
| Igualdad exacta *hit* (µs) | 1 000 | 9.98 | 1.48 | 1.59 |
| Igualdad exacta *hit* (µs) | 10 000 | 10.37 | 2.30 | **2.09** |
| Igualdad exacta *hit* (µs) | 100 000 | 13.97 | 2.72 | **1.58** |
| Igualdad exacta *miss* (µs) | 100 000 | 2.53 | 1.06 | 1.14 |
| Búsqueda por rango (µs) | 1 000 | 80.28 | **7.24** | N/A |
| Búsqueda por rango (µs) | 10 000 | 712.24 | **63.84** | N/A |
| Búsqueda por rango (µs) | 100 000 | 8 456.41 | **948.56** | N/A |
| Recorrido ordenado (µs) | 1 000 | 8 157.9 | **336.1** | N/A |
| Recorrido ordenado (µs) | 100 000 | 948 546.8 | **131 141.2** | N/A |
| Inserción (µs) | 100 000 | 30.70 | 22.58 | **1.88** |
| Borrado (µs) | 100 000 | **36.89** | 47.57 | 7.77 |

### 3.2 Espacio

| Índice | 1 000 | 10 000 | 100 000 |
|---|---|---|---|
| B+ agrupado | 44 773 | 455 775 | 4 712 759 |
| B+ no agrupado | 13 020 | 130 170 | 1 442 190 |
| Hash extendible | **12 280** | **125 089** | **1 377 275** |

(El B+ agrupado ocupa ≈ 3.3× más que los otros dos porque duplica los
registros completos: ≈ 47 bytes de estructura por registro, frente a
≈ 14 bytes del no agrupado y del hash.)

### 3.3 Interpretación

1. **Construcción: el hash es el más barato** (2.76 s frente a 8.91 s del B+
   no agrupado y 14.57 s del B+ agrupado a 100 000 claves). El B+ agrupado
   paga la copia del registro completo en cada hoja y el rebalanceo.
   Los tres escalan de forma aproximadamente **lineal con N**.
2. **Igualdad exacta: hash ≥ B+ no agrupado > B+ agrupado.** El hash hace
   O(1) promedio (1.58 µs a 100 000, prácticamente plano); el B+ agrupado
   es el más lento (9.98 → 13.97 µs) porque cada acierto **materializa el
   registro completo** (copia defensiva) en lugar de devolver una referencia.
3. **Rango: el B+ no agrupado arrasa** (948 µs frente a 8 456 µs del
   agrupado, 8.9× mejor a 100 000). El agrupado recorre las hojas copiando
   cada registro; el no agrupado solo devuelve RID + clave. El hash **no
   puede** resolver rangos.
4. **Recorrido ordenado (ORDER BY): el mismo patrón**, 131 ms frente a
   949 ms a 100 000 claves. Es el costo de que el índice B+ pueda sustituir
   al External Sort: el agrupado lo logra, pero copiando registros.
5. **Mutaciones: el hash es el más estable** (1.88 µs de inserción y 7.77 µs
   de borrado a 100 000, sin degradación con N). Los B+ pagan rebalanceo:
   el borrado del agrupado crece de 7.91 a 36.89 µs y el del no agrupado de
   7.37 a 47.57 µs.
6. **Espacio: el B+ agrupado es el más caro** (4.7 MB a 100 000), y los
   otros dos quedan muy cerca entre sí (1.38–1.44 MB).

---

## 4. Conclusiones: cuándo usar cada estructura

| Escenario de consulta | Estructura recomendada | Motivo (evidencia medida) |
|---|---|---|
| Igualdad exacta sobre una columna, muchas lecturas | **Hash extendible** | Menor tiempo de consulta (1.58 µs) y de construcción (2.76 s) a 100 000 |
| Igualdad + rangos sobre la misma columna | **B+ no agrupado** | Resuelve ambos (2.72 µs igualdad, 948 µs rango) sin el sobrecosto del agrupado |
| `ORDER BY` frecuente sobre la clave de orden físico | **B+ agrupado** | Único que permite al planner **evitar** el External Sort |
| Tabla con muchas altas/bajas y consultas por clave | **Heap File + índice B+/Hash** | Inserción/borrado O(1) (2 094 µs de borrado) y búsqueda indexada |
| Tabla consultada casi siempre por clave primaria, con pocas mutaciones | **Archivo Secuencial Paginado** | Búsqueda binaria ~700× más rápida que el *scan* del heap a 100 000 |
| Carga masiva inicial | **Heap File** (o carga masiva directa) | No requiere reorganizaciones durante la carga |
| `ORDER BY` sin índice disponible | **External Sort** | Funciona siempre, memoria acotada |
| `GROUP BY` / equi-`JOIN` sobre datasets grandes | **External Hashing** | O(N+M) promedio con particionado en disco |

---

## 5. Limitaciones y trabajo futuro

1. **Entorno de medición.** Los tiempos absolutos están dominados por la
   interceptación de E/S del entorno (0.46 ms por escritura, 2.56 ms por
   lectura de 43 bytes). Repetir los benchmarks en un equipo sin esa capa
   daría valores absolutos mucho menores; las conclusiones sobre
   complejidad y orden relativo no cambian.
2. **Inserción/borrado a 100 000 registros** no se midieron uno a uno
   (`N/A`); se usó carga masiva verificada byte a byte para las métricas de
   búsqueda y espacio. Levantar el límite con `--mutation-limit 100000` es
   posible en un host más rápido.
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
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000

# 2) Gráficas comparativas (PNG en benchmark_results/plots/)
python -m benchmarks.generate_charts

# 3) Verificación de la metodología (carga masiva == API pública)
python -m unittest tests.test_benchmark_heap_vs_sequential -v
```
