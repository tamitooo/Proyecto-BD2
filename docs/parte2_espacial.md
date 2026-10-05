# Parte 2 — Base de Datos Espacial

## Diseño

La tabla conserva latitud y longitud en columnas escalares y el R-Tree se declara sobre el par:

```sql
CREATE INDEX idx_tiendas_geo ON tiendas (lat, lon) USING RTREE;
```

El alias lógico `ubicacion` puede usarse en consultas espaciales cuando la tabla tiene un único R-Tree:

```sql
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464,-77.0428), HAVERSINE) < 5000;
```

También se admite un punto nombrado de sesión:

```sql
SET mi_ubicacion = POINT(-12.0464,-77.0428);
SELECT * FROM tiendas
ORDER BY distancia(ubicacion, mi_ubicacion, HAVERSINE)
LIMIT 10;
```

## Operaciones

### Range Search

1. Se proyecta el centro según la métrica.
2. Se construye un MBR candidato.
3. El R-Tree poda ramas por MBR.
4. Los candidatos de hoja se validan con la distancia real.

### k-NN

Se usa best-first search con una cola de prioridad ordenada por MINDIST. La distancia real se calcula al materializar candidatos de hoja.

### Polígono

Se poda por el MBR del polígono y se confirma con point-in-polygon mediante ray casting.

## Métricas

- `HAVERSINE`: metros sobre latitud/longitud.
- `EUCLIDEAN`: grados en el plano de coordenadas.

Ambas están cubiertas end-to-end en SQL y k-NN/range.

## Mapa

La interfaz usa **Leaflet 1.9.4 + OpenStreetMap**. Incluye:

- pan y zoom;
- click para fijar centro;
- círculo de rango;
- selección de k-NN;
- contorno de polígono;
- resaltado de resultados;
- selector Haversine/Euclidiana.

## Benchmark

Matriz requerida:

- N = 1K, 10K, 100K;
- 100 consultas por combinación;
- rango = 1, 5, 10 km;
- k = 10, 50, 100;
- técnicas = secuencial, R-Tree propio, PostgreSQL/PostGIS GiST.

### Resultados de referencia, rango 1 km

| N | Secuencial | R-Tree | GiST |
|---:|---:|---:|---:|
| 1K | 1.763 ms | 0.122 ms | 0.575 ms |
| 10K | 18.044 ms | 0.631 ms | 0.507 ms |
| 100K | 179.433 ms | 4.047 ms | 1.028 ms |

### Resultados de referencia, k-NN k=10

| N | Secuencial | R-Tree | GiST |
|---:|---:|---:|---:|
| 1K | 1.795 ms | 0.992 ms | 0.641 ms |
| 10K | 21.513 ms | 4.230 ms | 0.713 ms |
| 100K | 216.119 ms | 19.090 ms | 0.758 ms |

### Construcción

| N | R-Tree | GiST |
|---:|---:|---:|
| 1K | 5.580 ms | 114.559 ms |
| 10K | 73.875 ms | 238.387 ms |
| 100K | 1 024.034 ms | 2 659.405 ms |

## Espacio

La estimación histórica `nodes * 64` queda deprecada. El benchmark corregido usa tamaño profundo de la representación Python (`deep_size`). En una validación de 100K puntos se observaron ~94.18 MB del objeto Python. El valor GiST de ~26.47 MB proviene de `pg_relation_size` y es almacenamiento físico PostgreSQL; por tanto se reportan como métricas con metodología distinta, no como equivalentes byte-a-byte.

## PostGIS

Se utiliza `geometry(Point,4326)` con GiST 2D. Para rango se emplea `ST_DWithin`; para k-NN el operador `<->`. La documentación evita describir este índice como 3D.
