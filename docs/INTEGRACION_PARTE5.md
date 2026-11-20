# Proyecto BD2 — Integración controlada de la Parte 5 (19/11/2026)

Este conjunto de cambios agrega generación determinista, importación por lotes, evaluación sin fuga de datos, pruebas y una visualización multimedia en resultados SQL. **No reemplaza** los módulos de recomendación existentes del equipo ni modifica el árbol principal del proyecto sin revisión.

## Estado comprobable de los issues asignados

| Issue | Entregable en este parche | Límite de verificación |
| --- | --- | --- |
| #127 | Generador geométrico 3 000 imágenes (160×160), 90 consultas independientes, CSV de seis columnas, BoVW e integridad | El issue exige **productos reales de Amazon/Flipkart**: el conjunto sintético es una alternativa experimental, no su cumplimiento total |
| #128 | `generate_part5_data.py`: 30 locales ficticios en Lima, stock positivo para todos los productos y referencias íntegras | El cargador crea R-Tree, pero debe ejecutarse con el motor del repositorio |
| #129 | Compras por afinidad de categorías (laptop/mochila, celular/audífonos, etc.), semilla fija, sin productos inventados ni claves externas inválidas | Confirmar la co-compra en SQL contra el sistema final |
| #141 | Split temporal leave-last-one-out por usuario, P@10/Recall@10/HitRate@10 de fuentes y fusión, CSV/PNG/JSON | Comparación offline (BM25 de referencia/coseno exacto), no latencia ni ordenamiento del IVF de producción |
| #125 | `generate_audio_dataset.py`: audios WAV PCM sintéticos, cinco clases, consultas independientes, SHA256 y pruebas | No se ha verificado el índice MFCC del motor en el checkout completo |
| #126 | Resultados SQL con thumbnails PNG/JPEG/etc. y controles WAV/MP3/etc., URL segura `/api/media/{name}` | Verificar compilación y navegador dentro de la app completa |
| #142 | Pruebas de datos, aislamiento del split, seguridad, generación de audio, fusión y carga idempotente | Integración completa/API y tests de frontend deben correrse tras aplicar el parche |
| #143 | Este documento, documento geométrico y métricas reproducibles | Fusionar en el README e informe general del equipo |
| #144 | Guion y secuencia de demostración de 5–10 min, estructura de presentación de 15 min | El video de pantalla real necesita grabar la aplicación ejecutándose |

## Paso 1 — Aplicar sin perder cambios ajenos

Clonar la rama `main` actual y crear una rama nueva:

```powershell
git checkout main
git pull --ff-only
git switch -c feat/badi-parte5-datasets-evaluacion
```

Descomprimir `BD2_Badi_Implementation_Patch.zip` en otra carpeta y ejecutar el instalador incluido:

```powershell
python .\BD2_Badi_Patch\apply_bd2_patch.py --repo . --dry-run
python .\BD2_Badi_Patch\apply_bd2_patch.py --repo .
git status --short
```

El instalador no sobrescribe archivos nuevos que ya existan con otro contenido. En `App.tsx` solamente agrega el `import` del CSS, preservando la vista `Tienda` integrada por el equipo. `ResultsPanel.tsx` se reemplaza únicamente si coincide con la versión de `main` revisada; en caso contrario se cancela para hacer un merge manual.

## Variante real de #127 (si ya dispone de imágenes y exportación válida)

Una exportación original de Amazon o Flipkart **no se incluye** porque no se dispone de ella ni se han confirmado sus derechos de redistribución. El adaptador `tools/prepare_real_products.py` permite importar de forma segura un CSV y archivos de imagen ya obtenidos legalmente:

```powershell
python -m tools.prepare_real_products --source Flipkart --input data/origen/flipkart.csv --images data/origen/imagenes --output data/real_products --min-count 2000 --max-count 5000 --currency INR
```

El adaptador reconoce encabezados comunes, no descarga imágenes remotas, conserva la correlación con `original_id`, registra SHA-256 y procedencia, rechaza archivos corruptos y normaliza imágenes RGB a 160×160 **sin recortar** (bordes blancos). Conserva el precio numérico de la divisa original; para mostrar precios en soles se debe definir o aplicar una conversión documentada, no asumirla. Después debe entrenarse un vocabulario BoVW sobre las imágenes reales y generar embeddings con el motor del repo antes de usar el importador rápido.

## Paso 2 — Generar y validar las imágenes (sin conexión a Internet)

```powershell
python -m tools.generate_geometric_dataset --count 3000 --queries 90 --size 160 --seed 2026 --output data/geometric
python -m tools.generate_geometric_dataset --output data/geometric --verify
```

Genera `data/geometric/productos.csv`, `productos_indexados.csv`, `imagenes/`, `consultas/`, `etiquetas.csv`, `modelo/bow_image.npz`, `manifest.json` y `preview.png`. No sobrescribe archivos existentes. Los 3 000 productos son dibujos geométricos, no productos de comercio electrónico reales.

## Paso 3 — Generar 30 tiendas y compras válidas sobre esos mismos productos

```powershell
python -m tools.generate_part5_data --products data/geometric/productos.csv --output data/part5_synthetic --stores 30 --users 700 --purchases 4000 --seed 2026
python -m tools.generate_part5_data --verify data/part5_synthetic --images data/part5_synthetic/imagenes
```

El generador conserva **literalmente** las columnas `id,nombre,categoria,precio,descripcion,imagen` e incorpora las otras tres tablas `tiendas.csv`, `stock.csv`, `compras.csv`. Copia además imágenes, vocabulario y embeddings precalculados cuando existen. Los comercios son ficticios y las coordenadas se generan en torno a centros de distritos de Lima; no son direcciones de tiendas reales.

La verificación examina claves primarias y externas, stock positivo, cobertura total de productos, IDs de usuario, fechas ISO, duplicados, precios, nombres de imágenes, coordenadas, conteos y correspondencia con el manifiesto.

## Paso 4 — Importación rápida por API y creación del índice R-Tree + IVF

La carpeta de datos debe estar separada de la tienda anterior para evitar incompatibilidades entre vocabularios SIFT/BoVW.

Terminal A (PowerShell):

```powershell
$env:BD2_DATA_DIR = "$PWD\backend\data\parte5_pruebas"
python -m uvicorn backend.api:app --port 8000
```

Terminal B:

```powershell
python -m tools.seed_part5_fast --dataset data/part5_synthetic --data-dir backend/data/parte5_pruebas
```

Importa los CSV por lotes usando los endpoints existentes y reutiliza `productos_indexados.csv` para **no hacer 3 000 llamadas individuales a `EXTRACT_FEATURES`**. Crea `idx_productos_embedding` (IVF/coseno) e `idx_tiendas_ubicacion` (R-Tree), protege el modelo y medios previos e impide mezclar datasets con igual número de filas pero distinto contenido. El cargador admite repetir la misma importación sin duplicados.

Pruebas SQL orientativas:

```sql
SELECT id, categoria, imagen, SIMILARITY_SCORE() AS score FROM productos
WHERE SIMILAR_TO('consulta_geom_0001.png', k=10) USING IVF WITH METRIC=cosine;

SELECT id, nombre FROM tiendas
WHERE distancia(ubicacion, POINT(-12.12, -77.03), HAVERSINE) < 3000;
```

La consulta geométrica requiere que el archivo de consulta se encuentre en `<BD2_DATA_DIR>/media`. `seed_part5_fast.py` copia imágenes indexadas, no consultas: subir la consulta mediante el panel multimedia o copiar `data/geometric/consultas/consulta_geom_0001.png` al directorio de medios de la base de pruebas antes de ejecutar el SQL.

## Paso 5 — Evaluación de la tienda con historial oculto

```powershell
python -m benchmarks.benchmark_part5_precision --products data/part5_synthetic/productos.csv --purchases data/part5_synthetic/compras.csv --indexed data/part5_synthetic/productos_indexados.csv --output benchmarks/results/parte5
```

**Definición de verdad de terreno:** para cada usuario con al menos dos compras se retiene su compra cronológicamente última; el resto es entrenamiento. El producto ancla corresponde a su última compra observada en entrenamiento. Productos retenidos por usuarios que compartieron ese ancla se consideran relevantes. Se evita evaluar con compras ocultas en la fuente de co-compra.

`Precision@10 = (número de recomendaciones relevantes dentro del top 10) / 10`. También se reportan cobertura de consultas, recall@10 y hit rate@10. Se evita inflar P@10 cuando hay menos de 10 candidatos. El gráfico, tabla CSV y JSON se generan a partir de puntuaciones calculadas, **nunca se fijan de antemano**.

El benchmark usa una implementación offline de referencia: co-compra por conjuntos de usuarios, metadatos por precio/categoría, BM25 léxico y coseno exacto de embeddings, más min-max y pesos similares a `frontend/src/tienda/fusion.ts`. **No equivale a una corrida del optimizador SQL ni evalúa precisión aproximada de IVF**. Para cerrar por completo #141 debe compararse con la implementación final de los recomendadores de los demás integrantes.

En 3 000 productos con únicamente 4 000 compras, los anclajes son dispersos y P@10 de co-compra puede ser cero: interpretar ese número como escasez de señal y no como evidencia de un algoritmo defectuoso. Aumentar las compras y usuarios de forma controlada antes de concluir sobre la calidad de cada fuente.

## Paso 6 — Audio sintético y prueba del frontend

```powershell
python -m tools.generate_audio_dataset --count 1000 --queries 100 --output data/audio_synthetic
python -m tools.generate_audio_dataset --verify data/audio_synthetic
```

Produce grabaciones mono de 16 kHz / 16-bit PCM WAV con cinco familias (tono, doble tono, barrido, pulsos y ruido filtrado) y etiquetas independientes. Para entrenar el MFCC con las utilidades del repo, con un `BD2_DATA_DIR` **aislado**:

```powershell
python -m tools.train_feature_model --images --audio data/audio_synthetic/audios --audio-words 32 --data-dir backend/data/audio_pruebas
```

`--images` sin argumentos evita reentrenar vocabularios de imagen en esa corrida.

Frontend: abrir el panel `Motor` y ejecutar una consulta que incluya las columnas `imagen` (PNG/JPEG) o `archivo`/`nombre` (WAV/MP3). `ResultsPanel` sirve exclusivamente archivos con nombres seguros desde `/api/media/{name}`. Si el resultado no proyecta ninguna columna de archivo, no puede mostrar una miniatura; incluirla explícitamente en `SELECT`.

## Paso 7 — Pruebas antes de publicar el PR

```powershell
python -m pytest tests/test_part5_generated_data.py tests/test_audio_synthetic_dataset.py tests/test_seed_part5_fast.py tests/test_prepare_real_products.py tests/test_apply_bd2_patch.py tests/test_geometric_dataset.py -q
python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

No se deben marcar issues como completados si las pruebas de integración en la versión final de `main` fallan o no se ejecutan. No enviar un PR con los corpus de miles de imágenes: son regenerables con una semilla y ocupan espacio innecesario en Git.

## Diagnóstico de color

El SIFT de las imágenes usa conversión a escala de grises: el descriptor contiene contornos, gradientes y diferencias de luminancia, pero **no contiene tono HSV/RGB directamente**. En este corpus v2 (90 consultas), el **baseline coseno exacto offline** registró P@10 por **forma = 0.6833** y por **color = 0.1611**. Estos valores NO son resultados de IVF/SQL. Esas cifras miden un corpus sintético rotulado, no productos reales. Incorporar histogramas de color a futuro sería una extensión opcional y debería medirse por separado.

## Requisitos pendientes para cerrar completamente los issues

1. #127: incorporar 2 000–5 000 productos e imágenes reales de Amazon/Flipkart con licencias o permisos compatibles, preservando la procedencia. No renombrar datos geométricos como si fueran productos reales.
2. #141: ejecutar el benchmark end-to-end contra los recomendadores SQL/IVF finales, incluyendo la fusión real, y añadir sus resultados genuinos al informe.
3. #126/#142: confirmar visualmente miniaturas y audio en un navegador y ejecutar los tests del proyecto entero después de integrar el parche.
4. #143/#144: fusionar secciones del informe de todos los integrantes y grabar el video con el frontend y backend ejecutándose. Un guion no equivale a un video presentado.

## Distribución nueva de figuras (v2)

Cada página de 160×160 contiene 7–12 formas arrojadas en posiciones independientes, a veces superpuestas, con tamaños y giros aleatorios. Se eliminaron todos los cuadrados. Los campos `etiquetas.csv` guardan el conjunto de objetos en `escena_json`, y la clase es la **figura mayoritaria**, siempre más numerosa que los distractores. Cada consulta usa otra semilla. El CSV de seis columnas de productos mantiene compatibilidad. El script `benchmarks.benchmark_geometric_exact` genera una referencia **brute-force** que debe distinguirse del benchmark `benchmarks.benchmark_geometric_retrieval` contra el motor/IVF real.
