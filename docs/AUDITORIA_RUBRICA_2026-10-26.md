# Auditoría integral — Proyecto BD2 · Partes 1 y 2

Fecha de revisión: 2026-10-26.

## 1. Qué observó la rúbrica

### Parte 1 · Almacenamiento e indexación
El feedback indica que B+ Tree y Hash Extendible eran algorítmicamente correctos, pero vivían completamente en memoria y no realizaban operaciones de archivo. Esa observación es válida para el estado auditado del repositorio: el catálogo persistía la **definición** del índice, pero al reabrir una tabla llamaba a `rebuild_index()` y volvía a recorrer la tabla base.

### Parte 2 · R-Tree
El feedback señala que `serialize()/deserialize()` servían para benchmarks, pero no para persistir/recargar el índice real. También era correcto: el manifiesto conservaba las columnas del R-Tree, pero al reiniciar el catálogo reconstruía la estructura desde la tabla.

## 2. Corrección aplicada en este paquete

- Cada índice tiene un archivo propio dentro de `<data_dir>/indexes/`.
- B+ agrupado, B+ no agrupado, Hash Extendible y R-Tree sincronizan su estado a disco.
- La escritura es atómica: se escribe a `.tmp`, se hace `fsync` y luego `os.replace`.
- Al reiniciar, `Catalog.restore_table()` intenta cargar el archivo del índice; solo reconstruye desde la tabla si el archivo no existe.
- `DROP INDEX` elimina también el archivo físico del índice.
- `DROP TABLE` elimina los archivos físicos de todos sus índices.
- El panel de archivos expone los `.idx` y su tamaño para que la persistencia pueda demostrarse visualmente.
- Se añadió una prueba que **bloquea `HeapFile.scan()` durante el restore**. Si el catálogo intenta reconstruir desde la tabla, la prueba falla.

## 3. Checklist contra el enunciado

### 2.1 Parte 1 · Base relacional

| Requisito | Estado | Evidencia |
|---|---:|---|
| Heap File paginado en disco | ✅ | `storage/heap_file.py` |
| Reutilización de espacios libres | ✅ | free-list del Heap |
| Archivo Secuencial Paginado | ✅ | `storage/sequential_file.py` |
| Inserción manteniendo orden lógico | ✅ | `.main` + `.aux` |
| Eliminación lazy | ✅ | tombstones en Secuencial |
| Reorganización alrededor de 30% | ✅ | `reorganizar()` |
| B+ agrupado | ✅ | `indexes/clustered_bplus.py` |
| B+ no agrupado | ✅ | `indexes/unclustered_bplus.py` |
| Hash dinámico / Extendible Hashing | ✅ | `indexes/extendible_hash.py` |
| **Persistencia física de B+ y Hash** | ✅ corregido | archivos `.idx`; `tests/test_index_persistence.py` |
| External Sort / k-way merge | ✅ | `operators/external_sort.py` |
| External Hashing para GROUP BY | ✅ | `operators/external_hashing.py` |
| External Hashing para equi-JOIN | ✅ | Grace Hash Join |
| SELECT / WHERE | ✅ | parser + executor |
| ORDER BY / GROUP BY | ✅ | planner + operadores externos |
| INSERT / DELETE | ✅ | executor |
| BEGIN / END TRANSACTION | ✅ | transacciones SQL |
| Locks / concurrencia | ✅ | PS/PX + strict 2PL didáctico |
| Demo con threads y race condition | ✅ | `transactions/demo_concurrencia.py` |
| Panel de archivos | ✅ | frontend |
| Panel de consultas | ✅ | frontend |
| Panel de resultados | ✅ | frontend |
| Panel de plan de ejecución | ✅ | frontend |
| Heap vs Secuencial 1K/10K/100K | ✅ | benchmarks + resultados |
| B+ clustered vs unclustered vs Hash | ✅ | benchmark de índices |
| Igualdad, rango y ordenamiento | ✅ | benchmark de índices |
| Build time, consulta, espacio y mutaciones | ✅ | benchmark de índices |
| Gráficas + ventajas/desventajas + conclusiones | ✅ | `benchmark_results/`, docs |

### 2.2 Parte 2 · Base espacial

| Requisito | Estado | Evidencia |
|---|---:|---|
| R-Tree propio 2D | ✅ | `indexes/rtree.py` |
| Split cuadrático | ✅ | PickSeeds / PickNext |
| Range search | ✅ | R-Tree + verificación exacta |
| k-NN | ✅ | best-first + MINDIST |
| Intersección con polígonos | ✅ | MBR + ray casting |
| Euclidiana | ✅ | `spatial/geo.py`, `SpatialIndex` |
| Haversine | ✅ | `spatial/geo.py`, `SpatialIndex` |
| **Persistencia física del R-Tree** | ✅ corregido | archivo `.idx`, restore sin scan |
| Mapa interactivo | ✅ | Leaflet + OpenStreetMap |
| Resultados resaltados | ✅ | rango, k-NN y polígono |
| SQL `distancia(ubicacion, POINT(...))` | ✅ | parser espacial |
| SQL `ORDER BY distancia(ubicacion, mi_ubicacion)` | ✅ | variables de sesión |
| Secuencial vs R-Tree vs GiST | ✅ | benchmark espacial |
| Radios 1/5/10 km | ✅ | benchmark espacial |
| k = 10/50/100 | ✅ | benchmark espacial |
| N = 1K/10K/100K | ✅ | benchmark espacial |
| Promedio de 100 consultas | ✅ | benchmark espacial |
| Build time / query / memoria-espacio | ✅ | benchmark + plots |

## 4. Entregables

| Entregable | Estado |
|---|---:|
| Código fuente | ✅ |
| README con arquitectura/organización/instalación | ✅ |
| Informe incremental | ✅ |
| Presentación | ✅ disponible en la entrega del equipo |
| Video demo 5–10 min | ⚠️ depende de la entrega del equipo, no del código |

## 5. Riesgos que todavía conviene declarar

1. La persistencia del índice usa snapshots binarios atómicos del índice completo. **Ya no se reconstruye desde la tabla**, pero no es todavía un B+ paginado con buffer manager página-a-página como PostgreSQL.
2. No hay WAL ni recuperación crash-safe de una transacción incompleta.
3. Los índices se mantienen también en RAM durante la ejecución por simplicidad académica; el archivo `.idx` es la copia persistente durable.
4. El mapa necesita Internet para descargar tiles de OpenStreetMap; las consultas espaciales no dependen de los tiles.
5. PostGIS es baseline experimental, no dependencia del motor propio.

## 6. Pruebas de defensa recomendadas

```bash
python -m pytest -q
python -m examples.demo_persistencia_indices
python -m transactions.demo_concurrencia
```

La demo de persistencia debe mostrar archivos `.idx` y luego imprimir `Reinicio sin scan: OK`.
