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
| 2.2.4 | Comparativa **Secuencial vs R-Tree vs GiST de PostgreSQL**, rango 1/5/10 km, k-NN k=10/50/100, datasets 1 000/10 000/100 000 | ✅ `benchmarks/benchmark_spatial.py`, **con PostGIS 3.6.2**, ver §5 |

**El baseline es PostGIS de verdad** (ver §6): se instaló PostGIS 3.6.2 sobre
PostgreSQL 17 y el benchmark usa `geometry(Point,4326)`, GiST, `ST_DWithin` y el
operador `<->`. No queda ninguna salvedad metodológica.

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

| N | Secuencial | R-Tree propio | GiST/PostGIS | Mejora del R-Tree | Mejora de PostGIS |
|---|---|---|---|---|---|
| 1 000 | 1.756 ms | **0.098 ms** | 0.276 ms | **17.9×** | 6.4× |
| 10 000 | 17.068 ms | **0.777 ms** | 0.507 ms | **22.0×** | 33.6× |
| 100 000 | 179.433 ms | 4.047 ms | **1.028 ms** | 44.3× | **174.5×** |

### 5.2 k-NN (k = 10)

| N | Secuencial | R-Tree propio | GiST/PostGIS | Mejora del R-Tree | Mejora de PostGIS |
|---|---|---|---|---|---|
| 1 000 | 1.752 ms | 0.811 ms | **0.392 ms** | 2.2× | 4.5× |
| 10 000 | 22.944 ms | 4.653 ms | **0.713 ms** | 4.9× | 32.2× |
| 100 000 | 216.119 ms | 19.090 ms | **0.758 ms** | 11.3× | **285.2×** |

### 5.3 Tiempos completos a 100 000 puntos

| Consulta | Secuencial | R-Tree propio | GiST/PostGIS |
|---|---|---|---|
| Rango 1 km | 179.433 ms | 4.047 ms (44.3×) | **1.028 ms (174.5×)** |
| Rango 5 km | 182.081 ms | 16.484 ms (11.0×) | **8.536 ms (21.3×)** |
| Rango 10 km | 179.044 ms | 55.523 ms (3.2×) | **27.152 ms (6.6×)** |
| k-NN k=10 | 216.119 ms | 19.090 ms (11.3×) | **0.758 ms (285.2×)** |
| k-NN k=50 | 216.533 ms | 20.514 ms (10.6×) | **1.262 ms (171.6×)** |
| k-NN k=100 | 221.423 ms | 20.808 ms (10.6×) | **1.797 ms (123.2×)** |
| Polígono (4 vértices) | — | 17.073 ms | — |

### 5.4 Lectura de los resultados

1. **Los dos índices eliminan el crecimiento lineal.** La búsqueda secuencial se
   mantiene plana en ~180-220 ms porque recorre todo (es lineal en N); el R-Tree
   pasa de 0.78 ms a 4.0 ms y PostGIS de 0.28 ms a 1.03 ms al multiplicar N por
   10. La ventaja **crece con N**: el R-Tree va de 22× a 44× en rango de 1 km, y
   PostGIS de 34× a 175×.
2. **PostGIS gana en casi todo, y por mucho en k-NN.** A 100 000 puntos su k-NN
   es **285× más rápido** que el escaneo secuencial, frente a 11× del R-Tree
   propio. Las razones: el índice está implementado en C, su estructura es 3D
   sobre la esfera (`geography`) y el operador `<->` está integrado en el
   optimizador. Nuestro k-NN recorre hojas en Python y calcula Haversine por
   candidato.
3. **El R-Tree propio gana en rangos pequeños con pocos datos.** A 1 000 puntos
   y 1 km tarda 0.098 ms frente a 0.276 ms de PostGIS (2.8× mejor): con un
   dataset diminuto el coste de planificación y de ida y vuelta de PostgreSQL
   pesa más que el del algoritmo. A partir de 10 000 puntos PostGIS se impone.
4. **El rango se degrada con el radio en las tres técnicas**, como debe ser: a
   10 km hay muchos más puntos que devolver. El R-Tree baja de 44× a 3.2× y
   PostGIS de 175× a 6.6×. El índice acota la búsqueda, no reduce el resultado.
5. **`O(K log n)` se ve en la práctica:** el k-NN del R-Tree apenas cambia con K
   (19.1 ms con k=10 y 20.8 ms con k=100 a 100 000 puntos), mientras que el
   secuencial se mantiene en ~220 ms porque siempre recorre todo.
6. **La proyección no rompe la exactitud.** Todos los resultados del índice se
   verificaron contra fuerza bruta (`tests/test_rtree.py` y
   `tests/test_spatial_sql.py`): rango, k-NN y polígono devuelven **exactamente**
   el mismo conjunto que recorrer todos los puntos. El índice poda, no aproxima.

### 5.5 Cuándo usar cada técnica

| Escenario | Técnica recomendada | Motivo |
|---|---|---|
| Producción con muchos datos y consultas espaciales variadas | **GiST de PostGIS** | 175× en rango y 285× en k-NN a 100 000 puntos; integrado en el optimizador |
| k-NN sobre volúmenes grandes | **GiST de PostGIS** | Es donde la diferencia es mayor (285× frente a 11× del propio) |
| Dataset pequeño (< 10 000 puntos) y consultas por radio | **R-Tree propio** | Con 1 000 puntos es 2.8× más rápido que PostGIS: no paga planificación ni ida y vuelta |
| Intersección con polígonos | **R-Tree propio** | Poda por el MBR del polígono + punto-en-polígono exacto |
| Sin servidor de base de datos disponible | **R-Tree propio** | 44× más rápido que el escaneo, sin dependencias externas |
| Consultas que combinan filtros relacionales y espaciales | **Los dos** | El motor propio combina ambos; PostGIS lo hace con el optimizador |

---

## 6. El baseline: PostGIS, cumplido al pie de la letra

El enunciado pide comparar contra **GiST de PostgreSQL (con PostGIS)**. **El baseline
medido es exactamente eso**: PostGIS 3.6.2 sobre PostgreSQL 17, con
``geometry(Point, 4326)``, índice GiST, ``ST_DWithin`` y el operador ``<->``.

El informe JSON del benchmark lo declara:

```json
"environment": {
  "gist_backend": "postgis",
  "postgis_available": true
}
```

### Cómo se instaló

Al principio PostGIS **no estaba** en la máquina (no había ningún archivo
`*postgis*` en `share/extension`, `lib` ni `bin`), así que se instaló el paquete
oficial:

1. Descarga de `postgis-bundle-pg17x64-setup-3.6.2-1.exe` desde
   `download.osgeo.org/postgis/windows/pg17/` (99.9 MB).
2. **Verificación de integridad**: el MD5 calculado
   (`9b4243f53e1c06889a3295f44fde6202`) coincide con el publicado por OSGeo.
3. Instalación con el asistente (marca **PostGIS 3.6**, sin "Create spatial
   database") sobre PostgreSQL 17.
4. Activación y comprobación:

```bash
psql -U postgres -c "CREATE EXTENSION postgis;"
psql -U postgres -c "SELECT postgis_full_version();"
# POSTGIS="3.6.2 3.6.2" [EXTENSION] PGSQL="170" GEOS="3.14.1dev" PROJ="8.2.1"
```

### Un detalle de rendimiento que hay que conocer (si no, PostGIS parece lento)

La forma "obvia" de escribir la consulta **no usa el índice**. Se midió:

| Forma de la consulta | Plan de PostgreSQL | Tiempo (20 000 puntos) |
|---|---|---|
| `WHERE ST_DWithin(geom::geography, punto::geography, 5000)` | **Seq Scan** | 64.8 ms |
| `WHERE geom && ST_Expand(punto, grados) AND ST_DWithin(geom::geography, …, 5000)` | **Bitmap Index Scan on …_gist** | **9.2 ms** |
| `ORDER BY geom::geography <-> punto::geography LIMIT 10` | **Seq Scan** | 32.6 ms |
| `ORDER BY geom <-> punto LIMIT 10` | **Index Scan using …_gist** | **0.55 ms** |

La causa: **el índice GiST es sobre la columna `geometry`**, y al castear a
`geography` dentro del `WHERE`/`ORDER BY` PostgreSQL pierde la capacidad de usarlo.
La forma canónica y correcta es:

```sql
-- Rango: filtro de caja (indexable) + distancia exacta en metros
SELECT * FROM tiendas
WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(-77.0428, -12.0464), 4326), 0.05)
  AND ST_DWithin(geom::geography,
                 ST_SetSRID(ST_MakePoint(-77.0428, -12.0464), 4326)::geography,
                 5000);

-- k-NN: el operador <-> sobre la columna indexada
SELECT id FROM tiendas
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(-77.0428, -12.0464), 4326)
LIMIT 10;
```

El benchmark usa **estas** formas (el k-NN además reordena por `ST_Distance` exacta
para devolver el orden correcto). Es un punto que conviene mencionar en la defensa
porque demuestra que se entendió **cómo el optimizador usa el índice**, no sólo que
existe.

### El modo `earthdistance` se conserva como alternativa

El benchmark acepta `--pg-mode`:

* **`postgis`** — el baseline del enunciado (usa `geometry`, `ST_DWithin`, `<->`);
* `earthdistance` — usa `cube` + `earthdistance` (GiST nativo), por si no hay PostGIS;
* `auto` — **prefiere PostGIS** y sólo cae a `earthdistance` si no está.

También acepta `--pg-dsn` (o `BD2_PG_DSN`) para apuntar a otro servidor. Así la
comparación es reproducible en cualquier máquina, con o sin PostGIS.

### Qué decir en la defensa

> *"El baseline es GiST de PostgreSQL con PostGIS 3.6.2. Se instaló el paquete
> oficial, se verificó el MD5 y se creó el índice GiST sobre
> `geometry(Point,4326)`. Un detalle que aprendimos: la consulta hay que escribirla
> de forma que el optimizador **use** el índice —con `geom && ST_Expand(...)` para
> el rango y `<->` sobre la columna indexada para el k-NN—; con `geom::geography`
> en el `WHERE` PostgreSQL hace un Seq Scan y la medición sale 7× peor."*

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
#    PostGIS está instalado, así que --pg-mode postgis es el baseline del enunciado
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --pg-mode postgis

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
5. **PostGIS sí se usó.** El baseline es PostGIS 3.6.2 con `geometry`/GiST (ver §6),
   no una aproximación. La extensión `earthdistance`/`cube` queda sólo como
   alternativa para máquinas sin PostGIS.
