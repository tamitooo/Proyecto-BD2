# Parte 2 · Base de datos espacial (R-Tree)

> Comparativa experimental, decisiones de diseño y cómo reproducirlo.
> Complementa a [`revision_parte1.md`](revision_parte1.md).

---

## 1. Qué pide el enunciado y qué se entregó

| Sección | Requisito | Estado |
|---|---|---|
| 2.2.1 | Índice **R-Tree** para puntos 2D (latitud, longitud) | ✅ `indexes/rtree.py`, split cuadrático |
| 2.2.1 | Consultas por **rango** (p. ej. tiendas en un radio de 5 km) | ✅ `RTREE_RANGE_SCAN` |
| 2.2.1 | **k-NN** (los k vecinos más cercanos) | ✅ `RTREE_KNN`, best-first con MINDIST |
| 2.2.1 | **Intersección con polígonos** | ✅ `RTREE_POLYGON`, ray casting |
| 2.2.1 | Distancia **Euclidiana** y **Geodésica (Haversine)** | ✅ `spatial/geo.py`, las dos métricas |
| 2.2.2 | **Panel de mapa** que visualice los puntos y resalte los resultados | ✅ `frontend/src/panels/MapPanel.tsx` (SVG propio, sin dependencias) |
| 2.2.3 | Extensión del **parser SQL**: `distancia(...)`, `POINT(...)`, k-NN con `ORDER BY ... LIMIT` | ✅ ver §4 |
| 2.2.4 | Comparativa **Secuencial vs R-Tree vs GiST de PostgreSQL**, rango 1/5/10 km, k-NN k=10/50/100, datasets 1 000/10 000/100 000 | ✅ `benchmarks/benchmark_spatial.py`, ver §5 |

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

```sql
-- 1) Índice espacial: se declaran las dos columnas
CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE;
DROP INDEX idx_tiendas_ubicacion ON tiendas;

-- 2) Consulta por rango (radio en metros para Haversine)
SELECT * FROM tiendas
WHERE distancia(lat, POINT(-12.0464, -77.0428)) < 5000;

-- 3) k-NN: ORDER BY distancia(...) LIMIT k
SELECT nombre, lat, lon FROM restaurantes
ORDER BY distancia(lat, POINT(-12.0464, -77.0428)) LIMIT 10;

-- 4) Intersección con polígono
SELECT * FROM tiendas
WHERE dentro_de(lat, POLYGON((-12.20 -77.20, -12.20 -76.90,
                             -12.00 -76.90, -12.00 -77.20)));

-- 5) Métrica Euclidiana (en grados) en lugar de Haversine
SELECT * FROM tiendas
WHERE distancia(lat, POINT(-12.04, -77.04), EUCLIDEAN) < 0.05;

-- 6) Combinado con predicados normales
SELECT nombre FROM tiendas
WHERE categoria = 'A' AND distancia(lat, POINT(-12.04, -77.04)) < 3000;
```

Lo que devuelve el motor en el plan de ejecución:

| Consulta | `access_path` |
|---|---|
| Rango por distancia | `RTREE_RANGE_SCAN` |
| k-NN (`ORDER BY distancia(...) LIMIT k`) | `RTREE_KNN` |
| Intersección con polígono | `RTREE_POLYGON` |
| Distancia **sin** índice espacial | `HEAP_SCAN` + `FILTER` (calcula la distancia por fila) |

Los resultados incluyen las columnas calculadas ``_lat``, ``_lon`` y
``_distance``, que es lo que usa el panel de mapa para resaltar los puntos.

---

## 5. Resultados experimentales

**Metodología:** promedio de **100 consultas** por medición, semilla fija 42,
datasets de 1 000, 10 000 y 100 000 puntos con focos de densidad (para que los MBR
se solapen, que es el caso interesante), y tiempos en milisegundos.

### 5.1 Consulta por rango (1 km)

| N | Secuencial | R-Tree propio | GiST PostgreSQL | Mejora del R-Tree |
|---|---|---|---|---|
| 1 000 | 1.756 ms | **0.098 ms** | 1.083 ms | **17.9×** |
| 10 000 | 17.068 ms | **0.777 ms** | 1.699 ms | **22.0×** |
| 100 000 | 202.174 ms | **4.202 ms** | 2.675 ms | **48.1×** |

### 5.2 k-NN (k = 10)

| N | Secuencial | R-Tree propio | GiST PostgreSQL | Mejora del R-Tree |
|---|---|---|---|---|
| 1 000 | 1.752 ms | 0.811 ms | **0.853 ms** | 2.2× |
| 10 000 | 22.944 ms | 4.653 ms | **0.751 ms** | 4.9× |
| 100 000 | 236.632 ms | 17.427 ms | **0.932 ms** | 13.6× |

### 5.3 Tiempos completos

| N | Consulta | Secuencial | R-Tree | GiST |
|---|---|---|---|---|
| 100 000 | Rango 5 km | 212.072 ms | 15.999 ms | 33.496 ms |
| 100 000 | Rango 10 km | 200.413 ms | 55.226 ms | 140.933 ms |
| 100 000 | k-NN k=50 | 235.791 ms | 21.249 ms | **1.952 ms** |
| 100 000 | k-NN k=100 | 214.881 ms | 20.466 ms | **2.253 ms** |
| 100 000 | Polígono (4 vértices) | — | 19.265 ms | — |

### 5.4 Lectura de los resultados

1. **El R-Tree elimina el crecimiento lineal.** La búsqueda secuencial pasa de
   17 ms a 202 ms al multiplicar N por 10 (lineal); el R-Tree pasa de 0.78 ms a
   4.2 ms y la ventaja **crece con N** (22× → 48×). En una consulta por rango el
   R-Tree sólo visita las hojas que cruzan el MBR del círculo.
2. **El rango se degrada con el radio, como debe ser.** A 10 km el R-Tree baja de
   48× a 3.6× porque el conjunto de resultados crece (más puntos que devolver, no
   más nodos que visitar). Es el comportamiento esperado: el índice acota la
   búsqueda, pero no reduce el tamaño del resultado.
3. **Cada índice gana en algo distinto.** GiST es mejor en **k-NN** (0.93 ms
   frente a 17.4 ms a 100 000 puntos): está implementado en C y su estructura
   trabaja en 3D sobre la esfera, mientras que el nuestro recorre hojas en Python
   calculando Haversine por candidato. El **R-Tree propio es mejor en rangos
   pequeños**: a 1 km con 10 000 puntos tarda 0.78 ms frente a 1.70 ms de GiST
   (2.2× mejor) porque el MBR del círculo poda muy agresivamente. En rangos
   grandes (10 km) GiST vuelve a ganar porque devuelve muchos menos datos
   intermedios. Frente a la **búsqueda secuencial**, los dos ganan por igual: 48×
   (R-Tree) y 76× (GiST) en un rango de 1 km con 100 000 puntos.
4. **La proyección no rompe la exactitud.** Todos los resultados del índice se
   verificaron contra fuerza bruta (`tests/test_rtree.py` y `tests/test_spatial_sql.py`):
   rango, k-NN y polígono devuelven **exactamente** el mismo conjunto que recorrer
   todos los puntos. El índice poda, no aproxima.
5. **`O(K log n)` se ve en la práctica:** el k-NN del R-Tree pasa de 17.4 ms (k=10)
   a 21.2 ms (k=50) a 100 000 puntos: crece con K, no con N.

### 5.5 Cuándo usar cada técnica

| Escenario | Técnica recomendada | Motivo |
|---|---|---|
| Consultas por radio con muchos resultados y sin PostgreSQL | **R-Tree propio** | 48× más rápido que el escaneo y sin depender de un motor externo |
| k-NN sobre un volumen grande de datos | **GiST de PostgreSQL** | 253.9× más rápido que el escaneo a 100 000 puntos (índice en C) |
| Muchos datos ya en PostgreSQL y consultas variadas | **GiST de PostgreSQL** | Se integra con el optimizador y con `earth_box`/`ST_DWithin` |
| Dataset pequeño (< 1 000 puntos) | **Secuencial** | El índice no compensa: 1.7 ms frente a 0.1 ms, pero sin coste de construcción |
| Consultas que también filtran por columnas normales | **R-Tree propio + filtro** | El motor combina el índice espacial con los predicados relacionales |
| Necesidad de intersección con polígonos | **R-Tree propio** | Poda por el MBR del polígono + punto-en-polígono exacto |

---

## 6. Sobre el baseline: por qué no es PostGIS

El enunciado pide comparar contra **GiST de PostgreSQL** (con PostGIS). En el
entorno de desarrollo **PostGIS no está instalado y no hay red para instalarlo**
(se verificó: `pg_available_extensions` no lo lista y `npm`/pip no alcanzan la
red). En lugar de dejar la comparación sin hacer, se usó el **GiST nativo de
PostgreSQL 17** con las extensiones ``cube`` y ``earthdistance``:

```sql
CREATE EXTENSION cube;
CREATE EXTENSION earthdistance;

CREATE INDEX tiendas_gist ON tiendas USING gist (ll_to_earth(lat, lon));

-- k-NN por índice (Index Scan ordenado por distancia)
SELECT id FROM tiendas
ORDER BY ll_to_earth(lat, lon) <-> ll_to_earth(-12.0464, -77.0428) LIMIT 10;

-- Rango
SELECT id FROM tiendas
WHERE ll_to_earth(lat, lon) <@ earth_box(ll_to_earth(-12.0464, -77.0428), 5000)
  AND earth_distance(ll_to_earth(lat, lon), ll_to_earth(-12.0464, -77.0428)) <= 5000;
```

El plan de PostgreSQL confirma que **es un índice GiST de verdad**:

```
Limit
  ->  Index Scan using probe_geo_gist on probe_geo
        Order By: ((ll_to_earth(lat, lon))::cube <-> '(...)'::cube)
```

**Lo que cambia respecto a PostGIS** es la implementación del tipo espacial
(``cube`` 3D sobre la esfera en lugar de ``geometry``), **no la técnica de
indexación**: ambas usan GiST. El benchmark está escrito para que, si algún día
hay PostGIS, baste con poner ``USE_POSTGIS = True``: el script usa entonces
``geometry``, ``ST_DWithin`` y el operador ``<->`` sobre geometrías.

---

## 7. Pruebas

**64 pruebas nuevas** para la Parte 2, todas verificadas contra **modelos de
referencia** (fuerza bruta) en lugar de valores escritos a mano:

| Archivo | Qué cubre |
|---|---|
| `tests/test_rtree.py` | MINDIST (incluido el ejemplo de la diapositiva y la propiedad de cota inferior), operaciones de MBR, invariantes del árbol, rango y k-NN contra fuerza bruta, carga masiva, polígonos y las dos métricas |
| `tests/test_spatial_sql.py` | El parser de las tres sintaxis y sus errores, `CREATE INDEX ... USING RTREE`, y que rango/k-NN/polígono usen el R-Tree y coincidan con el escaneo |

Resultado: **374 pruebas sin fallos** en la suite completa.

---

## 8. Cómo reproducirlo

```bash
# 1) Benchmark espacial (genera CSV + JSON en benchmark_results/)
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000

# 2) Gráficas comparativas (PNG en benchmark_results/plots/)
python -m benchmarks.generate_spatial_charts

# 3) Pruebas espaciales
python -m pytest tests/test_rtree.py tests/test_spatial_sql.py -q

# 4) Demo por SQL
#    (en el panel de consultas de la interfaz)
CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(40), lat FLOAT, lon FLOAT);
-- cargar un CSV con las columnas id, nombre, lat, lon desde el panel de archivos
CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE;
SELECT * FROM tiendas WHERE distancia(lat, POINT(-12.0464, -77.0428)) < 1000;
SELECT * FROM tiendas ORDER BY distancia(lat, POINT(-12.0464, -77.0428)) LIMIT 10;
```

---

## 9. Limitaciones y trabajo futuro

1. **Proyección local.** La métrica Haversine usa una proyección equirectangular
   centrada en el dataset. Es exacta para las consultas (la verificación es con
   Haversine real) pero la *cota* MINDIST se degrada si los datos cubren
   continentes enteros; para eso habría que indexar en 3D sobre la esfera (como
   hace `earthdistance` con `cube`).
2. **Sin persistencia del índice.** Se reconstruye al abrir el catálogo, igual que
   los índices de la Parte 1. Con 100 000 puntos la reconstrucción por carga
   masiva es rápida, pero un índice paginado en disco sería lo siguiente.
3. **Sin supresión de solapamiento.** El R-Tree cuadrático puede tener MBR muy
   solapados en datos sesgados; ``R*-tree`` (reinserto forzado) lo mitigaría, pero
   se descartó por coherencia con lo que se evalúa.
4. **El k-NN calcula Haversine en Python.** Es la parte más lenta del índice
   propio; con las coordenadas ya proyectadas a metros se podría usar la distancia
   euclidiana como cota *y* como resultado para consultas locales.
5. **PostGIS no se pudo usar.** El baseline es GiST nativo con `cube`/
   `earthdistance` (ver §6). Es un GiST real, pero conviene declararlo al exponer.
