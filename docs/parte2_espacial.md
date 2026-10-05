# Parte 2 · Base de datos espacial (R-Tree)

> Diseño, sintaxis SQL, resultados experimentales y cómo reproducirlos.
> Las tablas numéricas de la §5 se generan desde `benchmark_results/spatial_benchmark.csv`
> con `python -m benchmarks.generate_report_tables`: ningún número se escribe a mano.

---

## 1. Qué pide el enunciado y qué se entregó

| Sección | Requisito | Estado |
|---|---|---|
| 2.2.1 | Índice **R-Tree** para puntos 2D (latitud, longitud) | ✅ `indexes/rtree.py`, split cuadrático |
| 2.2.1 | Consultas por **rango** (p. ej. tiendas en un radio de 5 km) | ✅ `RTREE_RANGE_SCAN` |
| 2.2.1 | **k-NN** (los k vecinos más cercanos) | ✅ `RTREE_KNN`, best-first con MINDIST |
| 2.2.1 | **Intersección con polígonos** | ✅ `RTREE_POLYGON`, poda por MBR + ray casting |
| 2.2.1 | Distancia **Euclidiana** y **Geodésica (Haversine)** | ✅ las dos, en SQL, en el R-Tree y en el mapa |
| 2.2.2 | **Panel de mapa interactivo** (Leaflet, Google Maps…) con resultados resaltados | ✅ `frontend/src/panels/MapPanel.tsx`: **Leaflet + OpenStreetMap**, zoom, pan, clic para fijar el punto, polígono por clics |
| 2.2.3 | `SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;` | ✅ **tal cual** (ver §4) |
| 2.2.3 | `SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;` | ✅ **tal cual** (`mi_ubicacion` es una variable de sesión) |
| 2.2.4 | Secuencial vs R-Tree vs **GiST de PostgreSQL**; rango 1/5/10 km; k-NN 10/50/100; 1 000/10 000/100 000 puntos; **construcción**, **consulta (prom. de 100)** y **memoria/espacio** | ✅ `benchmarks/benchmark_spatial.py` con **PostGIS**, ver §5 |

---

## 2. Decisiones de diseño (y por qué)

### 2.1 Split **cuadrático**, no R\*-tree

El material de clase (semana 06) define el R-Tree con **``QuadraticSplit``**:
``PickSeeds`` elige las dos entradas más alejadas maximizando
``area(MBR(E₁ ∪ E₂)) − area(E₁) − area(E₂)`` y ``PickNext`` reparte el resto al
grupo cuya MBR crezca menos. La **Práctica 2** y el examen piden eso mismo. Un
R\*-tree (con reinserto forzado) daría mejor llenado, pero **sería un R-Tree
distinto al que se evalúa**, y en la Parte 1 ya quedó claro que la coherencia con
lo que enseña la clase es lo que el profesor revisa. Se implementó el cuadrático.

### 2.2 Los índices se **reconstruyen** al abrir el catálogo

Es la política que ya tenía la Parte 1 (documentada y probada). Mantenerla evita
dos comportamientos distintos entre índices y hace que el R-Tree herede la
persistencia sin código nuevo: el manifiesto guarda la definición (tabla, lat, lon)
y al arrancar se reconstruye con **carga masiva**.

### 2.3 El plano del índice depende de la métrica

El R-Tree es una estructura plana, pero Haversine vive en la esfera. La solución:

* **Euclidiana** → el plano es directamente ``(x, y) = (lon, lat)`` en grados.
* **Haversine** → el plano es una **proyección local equirectangular en metros**:
  ``x = (lon − lon₀) · 111 320 · cos(lat₀)``, ``y = (lat − lat₀) · 111 320``, con
  ``lat₀`` el centro del dataset.

Con eso **MINDIST es una cota inferior real** de la distancia geodésica y el k-NN
es **exacto**: la cota sólo decide el orden de visita de los nodos, y la distancia
real se calcula siempre con Haversine sobre las coordenadas originales. El error
de la proyección es del orden de ``Δlon·(cos(lat) − cos(lat₀))``: **≈ 0.1 % a 20 km
del centro**, despreciable para consultas locales (que es el caso de uso del
enunciado).

### 2.4 Carga masiva obligatoria

Insertar 20 000 puntos uno a uno con ``ChooseLeaf`` tardaba **3 811 ms**; con
``bulk_load`` (empaquetado ordenado por celda, niveles equilibrados),
**86 ms**: **44× más rápido** y con **100 % de factor de llenado** frente al 72 %
de la inserción incremental. A 100 000 puntos la diferencia es la que separa "se
puede medir" de "no se puede medir". El reparto de cada nivel es **equilibrado**
(cada nodo recibe ``base`` o ``base+1`` hijos) para no dejar el último nodo por
debajo del mínimo ``m``.

---

## 3. La estructura implementada

```
NODO HOJA     :  (MBR, RID)          ← el objeto y su identificador
NODO INTERNO  :  (MBR, hijo)         ← MBR que cubre TODO el subárbol
RAÍZ          :  nodo interno (o hoja si el árbol es diminuto)
```

* ``m = ceil(M/2)`` con ``M = 16`` por defecto.
* Los MBR de un mismo nivel **pueden solaparse**: el R-Tree no es una partición
  disjunta del espacio (es el error que advierte el material de clase).
* ``validate()`` comprueba las invariantes: raíz con ≥ 2 hijos, ``m ≤ entradas ≤
  M`` en todo nodo no raíz, el MBR del padre **contiene** a los hijos, todas las
  hojas a la misma profundidad y el tamaño consistente con las entradas.

**MINDIST** (la fórmula que pide la clase):

```
MINDIST(Q, R) = sqrt( Σ dᵢ² )        con  dᵢ² = (Qᵢ − Lᵢ)²  si Qᵢ < Lᵢ
                                              (Qᵢ − Uᵢ)²  si Qᵢ > Uᵢ
                                              0           si Lᵢ ≤ Qᵢ ≤ Uᵢ
```

**k-NN** (Receta G de la clase): min-heap de ``(MINDIST, nodo)`` empezando por la
raíz; se saca el de menor cota; si ya hay K resultados y la cota supera la K-ésima
mejor distancia se corta (**poda global**); en una hoja se calcula la distancia
**real** y se actualiza el top-K; en un nodo interno se encolan los hijos con su
MINDIST. Complejidad típica ``O(K log n)``, peor caso ``O(n log n)``.

**Importante para la defensa:** la distancia real **sólo** se calcula con los
puntos de las hojas visitadas; los nodos internos se ordenan con MINDIST. Y
MINDIST **no** se usa para elegir semillas en la inserción: eso lo hace el área
(``PickSeeds``).

---

## 4. La sintaxis SQL añadida

### 4.1 Las consultas del enunciado, tal cual

```sql
-- Índice espacial sobre el par (latitud, longitud)
CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE;

-- 2.2.3 · ejemplo 1: rango
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;

-- 2.2.3 · ejemplo 2: k-NN contra "mi_ubicacion"
SET mi_ubicacion = POINT(-12.0464, -77.0428);     -- o un clic en el panel de mapa
SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
```

**`ubicacion`** no es una columna física: el esquema sólo admite `INT`, `FLOAT` y
`VARCHAR`, así que el punto se guarda como dos columnas. El ejecutor
(`QueryExecutor._spatial_column_for`) traduce el primer argumento de `distancia(...)`
o `dentro_de(...)` en este orden:

1. si es una columna de la tabla (`distancia(lat, ...)`), se usa tal cual;
2. si es el **nombre de un índice R-Tree**, se usa su par (lat, lon);
3. si la tabla tiene **un solo** índice R-Tree, `ubicacion` es su punto;
4. sin índice, se busca un par de columnas por nombre (`lat`/`lon`,
   `latitud`/`longitud`, `latitude`/`longitude`) y se resuelve con escaneo.

Si nada aplica, el error lo explica y sugiere el `CREATE INDEX` correspondiente.

**`mi_ubicacion`** es una **variable de sesión**: el segundo argumento de
`distancia(...)` puede ser `POINT(lat, lon)` o el nombre de una variable (con o sin
`@`). Se define con `SET mi_ubicacion = POINT(lat, lon)` o la envía el frontend: cada
clic en el mapa fija el punto, y el panel de consultas lo manda en
`POST /api/query` como `{"variables": {"mi_ubicacion": [lat, lon]}}`. Si se usa sin
definir, el error dice exactamente cómo definirla.

### 4.2 El resto de la sintaxis espacial

```sql
-- Intersección con polígono (vértices "lat lon")
SELECT * FROM tiendas
WHERE dentro_de(ubicacion, POLYGON((-12.20 -77.20, -12.20 -76.90,
                                   -12.00 -76.90, -12.00 -77.20)));

-- Métrica Euclidiana (radio en grados) en lugar de Haversine (radio en metros)
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.04, -77.04), EUCLIDEAN) < 0.05;

-- Combinado con predicados normales
SELECT nombre FROM tiendas
WHERE categoria = 'A' AND distancia(ubicacion, POINT(-12.04, -77.04)) < 3000;

-- Plan
EXPLAIN ANALYZE SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
```

| Consulta | `access_path` con R-Tree | sin R-Tree |
|---|---|---|
| Rango por distancia | `RTREE_RANGE_SCAN` | `HEAP_SCAN` + `FILTER` (distancia exacta por fila) |
| k-NN (`ORDER BY distancia(...) LIMIT k`) | `RTREE_KNN` | `HEAP_SCAN` + `EXTERNAL_SORT` **por la distancia** |
| Polígono | `RTREE_POLYGON` | — |

Con y sin índice el **resultado es el mismo** (sólo cambia el plan): lo verifican
`tests/test_cumplimiento.py` y `tests/test_spatial_sql.py` contra fuerza bruta.
Los resultados incluyen `_lat`, `_lon` y `_distance`, que usa el mapa.

### 4.3 Coherencia del índice

* **INSERT / UPDATE / DELETE** mantienen el R-Tree (inserción con `ChooseLeaf` +
  split cuadrático; el borrado reconstruye por carga masiva).
* El índice se **guarda en el manifiesto del catálogo** (tabla, latitud y longitud)
  y se **restaura al reiniciar** el motor reconstruyéndolo con carga masiva.
* La métrica elegida en SQL o en el mapa llega hasta el índice. Si difiere del plano
  en el que se construyó el árbol (metros para Haversine, grados para Euclidiana),
  la caja de búsqueda y la cota MINDIST se convierten de unidad con un margen del 2 %,
  y el resultado se verifica siempre con la distancia exacta.

---

## 5. Resultados experimentales

**Metodología.** Promedio de **100 consultas** por medición (más 3 de calentamiento
no cronometradas), semilla fija 42, datasets de 1 000, 10 000 y 100 000 puntos
alrededor de Lima con focos de densidad. Los tiempos de PostgreSQL incluyen la ida y
vuelta cliente-servidor por `psycopg2` (servidor local).

**Qué se mide como construcción:** carga masiva del R-Tree frente a
`CREATE INDEX … USING gist` + `ANALYZE`. La carga de la tabla con `COPY` no se cuenta,
igual que no se cuenta la del R-Tree.

**Qué se mide como espacio (comparación justa):**

* **R-Tree:** bytes del índice **serializado** en su formato de disco
  (`RTree.serialize()`), con **todos** los nodos y **todas** las entradas (MBR de
  32 B + puntero/RID de 8 B, ≈ 43 B por punto). La serialización tiene prueba de ida
  y vuelta (`RTree.deserialize`). Se reporta aparte la memoria que retiene en Python
  (`tracemalloc`), que es ~10× mayor por el costo de los objetos de Python.
* **GiST:** `pg_relation_size(índice)`, es decir, **sólo** el índice. El tamaño de la
  tabla se reporta aparte como contexto.

> **Corrección respecto de la versión anterior.** Antes el "espacio" del R-Tree era
> `nodos × 64` (426 816 B a 100 000 puntos, unos 4.3 B por punto, imposible porque
> cada entrada guarda un MBR). El de GiST era `pg_total_relation_size(tabla) +
> pg_relation_size(índice)`: incluía la tabla y contaba el índice dos veces
> (26.5 MB). Las dos medidas eran incorrectas y no eran comparables entre sí.

<!-- BEGIN:AUTO:parte2_tablas -->
_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._

Entorno de la corrida: Linux-6.18.44-fc-v70-x86_64-with-glibc2.39 · Python 3.12.3 · PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) + PostGIS 3.4.2.

**Rango (radio 1 km), promedio de 100 consultas**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.817 ms | 0.038 ms | 0.163 ms | 21.3× | 5.0× | R-Tree 4.3× |
| 10 000 | 8.289 ms | 0.242 ms | 0.197 ms | 34.2× | 42.1× | GiST 1.2× |
| 100 000 | 88.545 ms | 2.055 ms | 0.342 ms | 43.1× | 258.7× | GiST 6.0× |

**Rango (radio 5 km)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.807 ms | 0.077 ms | 0.202 ms | 10.5× | 4.0× | R-Tree 2.6× |
| 10 000 | 8.337 ms | 0.778 ms | 0.588 ms | 10.7× | 14.2× | GiST 1.3× |
| 100 000 | 88.845 ms | 11.630 ms | 10.032 ms | 7.6× | 8.9× | GiST 1.2× |

**Rango (radio 10 km)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.838 ms | 0.188 ms | 0.290 ms | 4.5× | 2.9× | R-Tree 1.5× |
| 10 000 | 8.437 ms | 2.462 ms | 1.395 ms | 3.4× | 6.0× | GiST 1.8× |
| 100 000 | 89.167 ms | 38.093 ms | 43.485 ms | 2.3× | 2.1× | R-Tree 1.1× |

**k-NN (k = 10)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.904 ms | 0.418 ms | 0.220 ms | 2.2× | 4.1× | GiST 1.9× |
| 10 000 | 9.494 ms | 1.921 ms | 0.237 ms | 4.9× | 40.1× | GiST 8.1× |
| 100 000 | 116.289 ms | 11.350 ms | 0.258 ms | 10.2× | 451.2× | GiST 44.0× |

**k-NN (k = 50)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.899 ms | 0.550 ms | 0.352 ms | 1.6× | 2.6× | GiST 1.6× |
| 10 000 | 10.387 ms | 2.269 ms | 0.396 ms | 4.6× | 26.2× | GiST 5.7× |
| 100 000 | 148.088 ms | 11.033 ms | 0.433 ms | 13.4× | 341.8× | GiST 25.5× |

**k-NN (k = 100)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.903 ms | 0.658 ms | 0.512 ms | 1.4× | 1.8× | GiST 1.3× |
| 10 000 | 9.914 ms | 2.706 ms | 0.619 ms | 3.7× | 16.0× | GiST 4.4× |
| 100 000 | 174.897 ms | 12.949 ms | 0.633 ms | 13.5× | 276.5× | GiST 20.5× |

**Todas las consultas con 100 000 puntos**

| Consulta | Secuencial | R-Tree propio | GiST/PostGIS |
|---|---|---|---|
| Rango 1 km | 88.545 ms | 2.055 ms (43.1×) | 0.342 ms (258.7×) |
| Rango 5 km | 88.845 ms | 11.630 ms (7.6×) | 10.032 ms (8.9×) |
| Rango 10 km | 89.167 ms | 38.093 ms (2.3×) | 43.485 ms (2.1×) |
| k-NN k=10 | 116.289 ms | 11.350 ms (10.2×) | 0.258 ms (451.2×) |
| k-NN k=50 | 148.088 ms | 11.033 ms (13.4×) | 0.433 ms (341.8×) |
| k-NN k=100 | 174.897 ms | 12.949 ms (13.5×) | 0.633 ms (276.5×) |
| Polígono (4 vértices) | — | 11.127 ms | — |

**Tiempo de construcción y espacio del índice**

| N | Construcción R-Tree | Construcción GiST | Índice R-Tree (serializado) | Índice GiST (pg_relation_size) | R-Tree en memoria Python | Tabla PostgreSQL (contexto) |
|---|---|---|---|---|---|---|
| 1 000 | 4.5 ms | 9.5 ms | 42.0 KiB | 48.0 KiB | 515.0 KiB | 88.0 KiB |
| 10 000 | 52.2 ms | 49.0 ms | 419.4 KiB | 384.0 KiB | 4.29 MiB | 832.0 KiB |
| 100 000 | 715.5 ms | 287.0 ms | 4.09 MiB | 3.94 MiB | 42.92 MiB | 8.05 MiB |

**Lectura numérica (calculada del CSV)**

- Rango 1 km con 1 000 puntos: R-Tree 0.038 ms vs GiST 0.163 ms → el R-Tree es 4.3× más rápido que PostGIS.
- Escalabilidad del R-Tree (rango 1 km, de 10 000 a 100 000 puntos): 0.242 ms → 2.055 ms (8.5× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
- Escalabilidad del GiST (rango 1 km, de 10 000 a 100 000 puntos): 0.197 ms → 0.342 ms (1.7× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
- Con resultado de tamaño fijo (k-NN k=10) el R-Tree crece de forma sublineal: 1.921 ms → 11.350 ms (5.9× para 10× datos).
- Secuencial (rango 1 km) de 10 000 a 100 000: 8.289 ms → 88.545 ms (10.7×, lineal en N).
- k-NN del R-Tree con 100 000 puntos: k=10 11.350 ms y k=100 12.949 ms (apenas cambia con k: O(k log n)).
- k-NN k=10 con 100 000 puntos: GiST 0.258 ms vs R-Tree 11.350 ms → GiST 44× más rápido (C + operador <-> integrado en el optimizador).
- Rango 10 km con 100 000 puntos: R-Tree 38.093 ms vs GiST 43.485 ms (con resultados grandes domina el costo de devolver filas, no la búsqueda).
- Espacio con 100 000 puntos: R-Tree serializado 4.09 MiB (42.9 B/punto) vs GiST 3.94 MiB (41.3 B/punto).
<!-- END:AUTO:parte2_tablas -->

Gráficas en `benchmark_results/plots/`: `spatial_range_{1,5,10}km.png`,
`spatial_knn_k{10,50,100}.png`, `spatial_speedup_*.png`, `spatial_build.png`,
`spatial_space.png` y `spatial_dashboard.png`.

### 5.1 Lectura de los resultados

1. **Los dos índices eliminan el crecimiento lineal de la búsqueda secuencial.** La
   secuencial crece ~10× cuando N crece 10×, porque recorre todo. En el rango, el
   tiempo de los índices crece sobre todo porque **crece el número de resultados**:
   con datos 10× más densos, un radio de 1 km devuelve ~10× más puntos. Cuando el
   resultado tiene tamaño fijo (k-NN con k = 10), el R-Tree crece de forma
   sublineal. Las cifras exactas, comparando siempre **el mismo par de tamaños**
   (10 000 → 100 000), están en la "Lectura numérica" de arriba.
2. **PostGIS gana en k-NN por mucho.** Su k-NN es un *Index Scan* ordenado por el
   operador `<->`, implementado en C e integrado en el optimizador. El nuestro es
   best-first en Python y calcula Haversine por candidato. El índice GiST de la
   comparación es **2D sobre `geometry(Point, 4326)`**, no 3D ni sobre `geography`
   (ver §6).
3. **El R-Tree propio gana con datasets pequeños.** Con 1 000 puntos y radio de 1 km
   es más rápido que PostGIS porque no paga planificación ni ida y vuelta al
   servidor. A partir de 10 000 puntos PostGIS se impone en radios pequeños.
4. **Con radios grandes, R-Tree y GiST quedan parejos.** A 10 km cada consulta
   devuelve miles de puntos y domina el costo de producir el resultado, no el de la
   búsqueda.
5. **El espacio en disco es equivalente.** Medidos de forma comparable (índice
   serializado frente a `pg_relation_size`), los dos ocupan ~41-43 B por punto: es
   el costo de un MBR más un puntero por entrada.
6. **La proyección no rompe la exactitud.** Rango, k-NN y polígono devuelven
   **exactamente** el mismo conjunto que la fuerza bruta, con ambas métricas
   (`tests/test_rtree.py`, `tests/test_spatial_sql.py`, `tests/test_cumplimiento.py`).
   El índice poda, no aproxima.

> Diferencia mínima de conteos con PostGIS: `ST_DWithin` sobre `geography` usa el
> **esferoide WGS84**, y el motor propio usa Haversine sobre una **esfera** de radio
> medio. Por eso los conteos difieren en menos del 1 % en el borde del radio. No es
> un error del índice.

### 5.2 Cuándo usar cada técnica

| Escenario | Técnica recomendada | Motivo |
|---|---|---|
| Producción, muchos datos, k-NN o radios pequeños | **GiST de PostGIS** | Índice en C, k-NN por *Index Scan* ordenado, integrado en el optimizador |
| Dataset pequeño (≈ 1 000 puntos) y consultas por radio | **R-Tree propio** | Sin planificación ni ida y vuelta: más rápido que PostGIS a esa escala |
| Radios grandes (muchos resultados) | **Cualquiera de los dos índices** | Domina el costo de devolver filas; ambos quedan parejos |
| Intersección con polígonos | **R-Tree propio** | Poda por el MBR del polígono + punto-en-polígono exacto |
| Sin servidor de base de datos | **R-Tree propio** | Decenas de veces más rápido que el escaneo y sin dependencias |
| Muy pocos datos o una sola consulta | **Secuencial** | No compensa construir un índice |

---

## 6. El baseline: PostGIS, GiST 2D sobre `geometry`

El baseline es **GiST de PostgreSQL con PostGIS**. El índice es
`CREATE INDEX … USING gist (geom)` sobre una columna **`geometry(Point, 4326)`**:
un R-Tree **2D** sobre cajas en grados. El rango usa `geom && ST_Expand(...)`
(filtro de caja indexable) más `ST_DWithin(geom::geography, …, metros)`
(comprobación exacta en metros). El k-NN usa `ORDER BY geom <-> punto LIMIT k`
sobre la columna indexada y después reordena por `ST_Distance` exacta.

La versión exacta del servidor queda en `benchmark_results/spatial_benchmark.json`
(`environment.postgres_server`). La corrida publicada usa **PostgreSQL 16 +
PostGIS 3.4.2**. Antes el equipo también midió con PostgreSQL 17 + PostGIS 3.6.2 en
Windows, con conclusiones equivalentes.

### Un detalle de rendimiento que hay que conocer

La forma "obvia" de escribir la consulta **no usa el índice**:

| Forma de la consulta | Plan de PostgreSQL |
|---|---|
| `WHERE ST_DWithin(geom::geography, punto::geography, 5000)` | **Seq Scan** |
| `WHERE geom && ST_Expand(punto, grados) AND ST_DWithin(geom::geography, …)` | **Bitmap Index Scan** sobre el GiST |
| `ORDER BY geom::geography <-> punto::geography LIMIT 10` | **Seq Scan** |
| `ORDER BY geom <-> punto LIMIT 10` | **Index Scan** sobre el GiST |

El índice GiST está sobre la columna `geometry`. Si se castea a `geography` dentro
del `WHERE` o del `ORDER BY`, PostgreSQL ya no puede usarlo. Conviene decirlo en la
defensa: demuestra que entendimos **cómo usa el optimizador el índice**, no sólo que
el índice existe.

### Modos del benchmark

`--pg-mode postgis` es el baseline del enunciado y falla si no hay PostGIS.
`--pg-mode earthdistance` usa el GiST nativo de `cube` + `earthdistance`.
`--pg-mode auto` prefiere PostGIS. Sin servidor o sin `psycopg2`, el benchmark mide
secuencial y R-Tree y marca PostgreSQL como no disponible. `--pg-dsn` (o
`BD2_PG_DSN`) apunta a otro servidor.

---

## 7. Pruebas

| Archivo | Qué cubre |
|---|---|
| `tests/test_rtree.py` | MINDIST (con el ejemplo de la diapositiva y la propiedad de cota inferior), MBR, invariantes, rango y k-NN contra fuerza bruta, carga masiva, polígonos y métricas |
| `tests/test_spatial_sql.py` | Parser de `distancia(...)`, `POINT(...)`, `dentro_de(...)`; `CREATE INDEX … USING RTREE`; que rango, k-NN y polígono usen el R-Tree y coincidan con el escaneo |
| `tests/test_cumplimiento.py` | SQL **literal** del enunciado con y sin índice, `SET`/`mi_ubicacion`, Euclidiana por R-Tree, mantenimiento con INSERT/UPDATE/DELETE, restauración al reiniciar, serialización y espacio del R-Tree |

---

## 8. Cómo reproducirlo

```bash
# 1) Benchmark espacial (CSV + JSON en benchmark_results/), necesita PostGIS
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --pg-mode postgis

# 2) Gráficas y tablas del informe (desde el CSV)
python -m benchmarks.generate_spatial_charts
python -m benchmarks.generate_report_tables

# 3) Pruebas
python -m pytest tests/test_rtree.py tests/test_spatial_sql.py tests/test_cumplimiento.py -q

# 4) Demo por consola
python -m examples.demo_parte2
```

---

## 9. Limitaciones y trabajo futuro

1. **Proyección local.** Con Haversine el árbol se construye sobre una proyección
   equirectangular centrada en el dataset. Para datos de una ciudad o región es
   exacta en la práctica (margen de seguridad del 2 % y verificación exacta), pero
   con datos de escala continental habría que indexar en 3D sobre la esfera.
2. **Índice en memoria.** El R-Tree se serializa (y así se mide su espacio), pero en
   ejecución vive en memoria y se reconstruye al abrir el catálogo, igual que los
   índices de la Parte 1. Un índice paginado en disco sería el siguiente paso.
3. **Borrado por reconstrucción.** `DELETE` reconstruye el árbol por carga masiva en
   lugar de aplicar `CondenseTree`. Es correcto pero `O(n)` por borrado.
4. **Sin R\*-tree.** Se mantuvo el split cuadrático de la clase. El reinserto forzado
   del R\*-tree reduciría el solapamiento con datos sesgados.
5. **k-NN en Python.** Es la parte más lenta frente a PostGIS. Una cota más ajustada o
   una implementación compilada cerrarían parte de la brecha.
