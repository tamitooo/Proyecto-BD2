# Dataset de formas dispersas: simulación reproducible de un tablero de figuras (v2)

**Objetivo:** evaluar la búsqueda por imágenes del motor BD2 usando un corpus controlado cuya respuesta correcta puede medirse. **No es un dataset de productos reales de Amazon/Flipkart:** issue #127 exige adicionalmente esos productos.

## Cambios respecto a la versión anterior

- No se dibujan cuadrados ni rectángulos como objetos. Las cinco familias son: **círculo, triángulo, pentágono, estrella y hexágono**.
- Cada imagen contiene **7–12 objetos** en lugares, tamaños, ángulos y colores aleatorios, con solapamientos naturales. No hay una forma centrada obligatoria ni una cuadrícula de posiciones.
- La etiqueta de clase es la **forma geométrica mayoritaria** (siempre más de la mitad de las formas). Existen distractores de otras familias: no es un problema trivial de clasificación de una forma aislada.
- En `etiquetas.csv`, `escena_json` registra todas las figuras dibujadas, color, ángulo, posición y radio; el conteo de la familia predominante se puede comprobar con los datos y no con el modelo.
- Todas las páginas RGB miden exactamente **160 × 160 píxeles**. Las imágenes de consulta no se indexan y usan semillas independientes.

## Generación (desde la raíz del repositorio)

```powershell
python -m pip install opencv-python-headless Pillow numpy matplotlib
python -m tools.generate_geometric_dataset --count 3000 --queries 90 --size 160 --seed 2026 --output data/geometric
python -m tools.generate_geometric_dataset --verify --output data/geometric
python -m benchmarks.benchmark_geometric_exact --dataset data/geometric --output benchmarks/results/geometric_exact
```

> El generador **no sobrescribe** un corpus existente. Usa un directorio nuevo o renombra el anterior. La opción `--verify` no regenera datos.

Se crean:

| Archivo | Uso |
|---|---|
| `imagenes/geom_000001.png` ... | Productos sintéticos indexables (3000) |
| `consultas/consulta_geom_0001.png` ... | Consultas independientes (90) |
| `productos.csv` | `id,nombre,categoria,precio,descripcion,imagen` (contrato de tienda original) |
| `productos_indexados.csv` | Misma fila con `embedding` JSON (32 floats) |
| `etiquetas.csv` | Clase, color, conteos y lista JSON de todos los objetos |
| `consultas.csv` | Etiqueta de cada consulta |
| `modelo/bow_image.npz` | Centroides e IDF compartidos para las consultas |
| `manifest.json` | Semilla, versión, clases, backend y duración |
| `preview.png` | Vista rápida de 18 páginas |

El validador revisa las claves y archivos, esquema y cantidad de filas, seguridad de nombres, tamaños de los PNG, dimensiones de embeddings, consistencia de clases y **mayoría documentada de formas**.

## Importación con IVF real

Las imágenes deben indexarse usando el **mismo vocabulario** con el que se consultan. No importes este modelo a un backend que ya indexó productos con otro modelo.

**Terminal 1** — un `BD2_DATA_DIR` exclusivamente geométrico:

```powershell
$env:BD2_DATA_DIR = (Join-Path (Get-Location) "backend/data/geometry_scattered")
python -m uvicorn backend.api:app --port 8000
```

**Terminal 2**, después de arrancar el backend:

```powershell
python -m tools.seed_geometric_dataset --dataset data/geometric --data-dir backend/data/geometry_scattered
python -m tools.verify_badi_release --mode geometric --dataset data/geometric --output benchmarks/results/geometric/scattered_sanity.json
python -m benchmarks.benchmark_geometric_retrieval --dataset data/geometric --output benchmarks/results/geometric
```

Consulta de ejemplo desde el panel SQL (`Motor`):

```sql
SELECT id, nombre, categoria, imagen, SIMILARITY_SCORE() AS score
FROM figuras
WHERE SIMILAR_TO('consulta_geom_0001.png', k=10)
USING IVF WITH METRIC=cosine;
```

Los resultados con `imagen` tienen miniaturas cuando se aplica `ResultsPanel.tsx` del patch.

## Resultados que sí se midieron en el corpus v2

Sobre 3000 productos y 90 consultas independientes, ejecutando **coseno exacto contra todos los embeddings BoVW**:

| Medida | Baseline offline v2 |
|---|---:|
| Precision@10 por figura mayoritaria | **0.6833** |
| Top-1 por figura | 0.7000 |
| Precision@10 por color de referencia | 0.1611 |
| Precision@10 por figura y color | 0.1200 |
| Azar equilibrado (5 figuras) | 0.2000 |

**Esto no es una medición de IVF/SQL:** no se debe comparar su latencia ni presentar este valor como precisión del índice aproximado. Corre el benchmark IVF real con el backend activo. La precisión ha disminuido respecto al corpus antiguo de una figura central porque ahora cada imagen tiene varias formas y oclusiones: es un problema visual más difícil y realista.

La generación completa con OpenCV en el entorno de elaboración tardó **12.49 segundos** (no es un compromiso de rendimiento para otro equipo). El importador y el modelo deben verificarse en la máquina donde se vaya a demostrar.

## Color

El SIFT del motor transforma primero el RGB a escala de grises: estudia gradientes, forma y contraste, **no el tono HSV directamente**. El color de la forma principal se conserva en las etiquetas para medir la limitación. Incorporar histogramas cromáticos sería una mejora aparte, sujeta a sus propios tests.
