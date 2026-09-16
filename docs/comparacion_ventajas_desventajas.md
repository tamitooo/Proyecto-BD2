# Tabla comparativa de ventajas y desventajas (Parte 1)

Documento de apoyo para la sección **2.1.6 Comparación Experimental de
Técnicas** del enunciado ("tabla resumen con ventajas/desventajas de cada
técnica").

Los números que se citan provienen de los benchmarks reproducibles del
repositorio:

```bash
python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000
python -m benchmarks.generate_charts      # -> benchmark_results/plots/*.png
```

> **Nota sobre los tiempos absolutos.** Las mediciones se tomaron en un
> host con intercepción de E/S (cada `open/read/write` pasa por una capa de
> aislamiento). La propia corrida mide una calibración base: **≈ 0.46 ms por
> escritura** y **≈ 2.6 ms por lectura** de un registro de 43 bytes. En un
> equipo sin esa capa los valores absolutos bajan uno o dos órdenes de
> magnitud. Por eso la comparación se apoya en **diferencias relativas**,
> en la **tendencia con N** y en el **análisis de complejidad**, no en el
> valor absoluto. Ver `docs/conclusiones_experimentales.md`.

---

## 1. Gestión de archivos: Heap File vs Archivo Secuencial Paginado

| Criterio | Heap File | Archivo Secuencial Paginado |
|---|---|---|
| Organización en disco | Páginas de 4096 B; registros en orden de llegada | `.main` ordenado por clave primaria + `.aux` de desbordamiento |
| Inserción | Se escribe en el primer slot libre de la *free-list*; si no hay, se agrega una página al final | Se escribe al final de `.aux` (append) y se reorganiza cuando el desbordamiento supera el 30 % |
| Búsqueda por clave primaria | **Full scan** O(N): no existe índice de clave primaria | **Búsqueda binaria** O(log N) en `.main` + barrido de `.aux` |
| Búsqueda por rango | Full scan O(N) | Full scan ordenado o rango sobre `.main` (O(N) en la implementación actual, sin índice) |
| Borrado | *Tombstone* + alta de la página en la *free-list* | *Tombstone* (*lazy delete*) + conteo de desperdicio |
| Recuperación de espacio | **En línea**: cualquier inserción posterior reutiliza el slot | **Diferida**: exige reorganizar (compactar) `.main` |
| Reorganización | No existe (no hace falta) | Explícita/automática al superar el 30 % de desperdicio o de `.aux` |
| Costo de la reorganización | 0 | O(N) sobre todo `.main` (medido: 5.9 ms con 1 000 y 36.5 ms con 10 000 registros) |
| Espacio en disco | Múltiplos de página: se desperdicia el resto de la última página (1 935 B con 1 000 registros; 1 505 B con 100 000) | Exacto tras reorganizar (`N × 43 B`); entre reorganizaciones acumula tombstones (16 082 B con 10 000 registros) |
| Costo por operación (amortizado) | Inserción/borrado O(1) amortizado; búsqueda O(N) | Inserción O(1) amortizado con reorganizaciones periódicas; búsqueda O(log N) |
| Limitación principal | Sin acceso eficiente por clave: cualquier consulta selectiva lee todo el archivo | Sensible a la frecuencia de reorganización; los RID cambian al reorganizar (invalida índices) |
| **Ventajas** | • Inserción/borrado simples y muy baratos<br>• Reutilización de espacio sin compactar<br>• Estructura ideal para *scans* completos y para cargas masivas | • Búsqueda por clave primaria en O(log N)<br>• Mantiene el orden físico (aprovechable para `ORDER BY` y rangos)<br>• Espacio sin desperdicio después de reorganizar |
| **Desventajas** | • Búsqueda por clave O(N) (medido: 317 ms promedio con 100 000 registros, frente a 0.45 ms del secuencial)<br>• Espacio en múltiplos de página | • Borrado costoso (medido: 12.6–15.6 ms, incluye la reorganización automática)<br>• Reorganizaciones frecuentes durante la carga (17 con 1 000 registros, 26 con 10 000)<br>• Invalida los RID ya indexados |
| **Cuándo usarla** | Tablas con muchas altas/bajas y consultas poco selectivas; cuando se indexa por fuera (B+ no agrupado o hash) | Tablas que se consultan por clave primaria o por rango y cambian poco entre reorganizaciones |

### Evidencia medida (heap vs secuencial)

| Métrica | Heap File | Archivo Secuencial |
|---|---|---|
| Inserción 1 000 / 10 000 (µs por registro) | 15 393 / 14 826 | 15 232 / 16 375 |
| Búsqueda por PK acertada 1 000 / 10 000 / 100 000 (µs) | 3 438 / 36 597 / 317 507 | 322 / 246 / 451 |
| Búsqueda por PK fallida 1 000 / 10 000 / 100 000 (µs) | 4 076 / 38 597 / 326 892 | 577 / 365 / 629 |
| Borrado 1 000 / 10 000 (µs) | 1 950 / 2 094 | 15 640 / 12 630 |
| Reorganización 1 000 / 10 000 (ms) | no aplica | 5.9 / 36.5 |
| Espacio 1 000 / 10 000 / 100 000 (bytes) | 44 935 / 433 010 / 4 301 505 | 43 000 / 430 000 / 4 300 000 |
| Reutilización de espacio tras borrar | **300/300** y **3000/3000** slots liberados reutilizados | vía reorganización |

Gráficas: `benchmark_results/plots/storage_insert.png`,
`storage_search.png`, `storage_space.png`, `storage_mutation.png`,
`storage_dashboard.png`.

---

## 2. Indexación: B+ agrupado vs B+ no agrupado vs Hash extendible

| Criterio | B+ agrupado | B+ no agrupado | Hash extendible |
|---|---|---|---|
| Contenido de las hojas | Registro completo | Solo el RID | Pares (clave, RID) en buckets |
| Igualdad exacta | Muy buena (camino al árbol) | Muy buena + *fetch* del registro por RID | **Óptima**: O(1) promedio, sin recorrer árbol |
| Búsqueda por rango | **Sí**, recorriendo hojas enlazadas | Sí, pero con *fetch* aleatorio por cada RID | **No soportada** (solo igualdad) |
| `ORDER BY` sobre la clave | **Sí**: evita el External Sort | Sí, entrega RIDs en orden de clave | No |
| Construcción | Más costosa: copia el registro completo en cada hoja | Intermedia: solo claves + RID | La más barata |
| Espacio adicional | El más alto (duplica los registros) | Bajo (clave + RID) | Bajo (clave + RID + directorio) |
| Inserciones/borrados frecuentes | Costo de rebalanceo + copia de registros | Costo de rebalanceo (más liviano) | Muy bueno mientras el directorio no crezca; los *splits* duplican el directorio |
| Degradación | Ninguna grave; altura logarítmica | Ninguna grave | Posible sesgo si la función hash es mala o hay muchísimas claves |
| **Ventajas** | • Acelera igualdad, rango y orden<br>• Un solo acceso devuelve el dato (sin *fetch* extra) | • Acelera igualdad y rango<br>• Menor espacio y construcción que el agrupado<br>• Sirve para varios índices por tabla | • Igualdad exacta más rápida y con menor costo de construcción<br>• Crecimiento dinámico sin rebalanceo de árbol |
| **Desventajas** | • Mayor espacio y mayor costo de construcción<br>• Duplica datos: mantener consistencia al actualizar | • Cada coincidencia exige un *fetch* adicional por RID | • No sirve para rangos ni para `ORDER BY`<br>• El directorio puede duplicarse en picos de inserción |
| **Cuándo usarla** | Tabla almacenada físicamente ordenada por esa clave (clave primaria o *clustering key*) | Índices secundarios sobre columnas usadas en igualdad/rango | Columnas usadas casi solo en igualdad exacta, con muchas lecturas |

### Evidencia medida (índices)

Ver la tabla de resultados en `docs/conclusiones_experimentales.md`
(sección de índices) y las gráficas
`benchmark_results/plots/index_build_time.png`, `index_exact_lookup.png`,
`index_range_search.png`, `index_ordered_scan.png`, `index_size.png` e
`index_mutations.png`.

**Hallazgo principal:** el hash gana en igualdad exacta y en costo de
construcción; el B+ no agrupado es el mejor equilibrio para igualdad+rango;
el B+ agrupado es el único que resuelve `ORDER BY` sin ordenar, pero paga
el precio en espacio y tiempo de construcción.

---

## 3. Algoritmos externos para `ORDER BY`, `GROUP BY` y `JOIN`

| Operación | Alternativa | Ventaja | Desventaja | Cuándo conviene |
|---|---|---|---|---|
| `ORDER BY` | **External Sort** k-way merge | Funciona siempre, sin importar los índices disponibles; memoria acotada (`memory_limit_records`) | Costo O(N log N) y escritura/lectura de archivos temporales | Cuando no hay índice B+ sobre la columna de orden (o el orden es `DESC`) |
| `ORDER BY` | **Recorrido del B+** | Costo O(N), sin ordenar | Requiere índice B+ sobre la columna y orden ascendente | Cuando existe el índice (el planner evita el sort) |
| `GROUP BY` | **External Hashing** (Grace) | O(N) promedio, particiona en disco y soporta agregados `count/sum/avg/min/max` | No entrega resultado ordenado; sensible a sesgo de la función hash | Agrupaciones sobre datasets que no caben en memoria |
| `JOIN` | **Grace Hash Join** | O(N+M) promedio para equi-joins, con memoria acotada | Solo para igualdad; requiere reparticionar si una partición no cabe | Equi-joins entre tablas medianas/grandes |
| `JOIN` | **Nested Loop** | Sirve para cualquier condición (`<`, `>`, `!=`) | O(N×M): inviable en tablas grandes | Uniones no equi o tablas muy pequeñas |

Estas decisiones están codificadas como reglas en `query/query_planner.py`
y se ejecutan en `query/executor.py`; el plan elegido se puede ver con
`QueryExecutor.explain_sql(...)` o en la demo
`examples/demo_parte1.py`.
