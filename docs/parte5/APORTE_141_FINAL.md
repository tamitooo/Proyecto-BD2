# Issue #141 — Evaluación reproducible de las recomendaciones de la Parte 5

> **Nota (al fusionar):** el #127 ya está hecho: el dataset final son 2 531 productos reales de
> Amazon Berkeley Objects (`tools/preparar_abo.py`). La evaluación del informe usa ese dataset y
> las cuatro fuentes por la API del motor (`tools/aprender_pesos.py`, resultados en
> `benchmarks/results/parte5/`). Esta evaluación fuera de línea, con métricas extra, quedó en
> `benchmarks/results/parte5/fuera_de_linea/` y se corrió sobre la muestra de 30 productos.

## Requisitos confirmados

**Issue #141:** separar compras de evaluación, medir `Precision@10` de las fuentes individuales y de la fusión; entregar tabla y gráfico en `benchmarks/results` y en el informe. Se mantiene la interfaz con cuatro fuentes (texto/BM25, visual/SIFT+BoVW+IVF, co-compra, metadatos) descrita en el proyecto integrador. **No confundir** con Parte 4, que requiere experimentos de recuperación multimedia y comparación IVF vs HNSW con `Recall@10`, tiempo de construcción/consulta, uso de memoria y experimentos a escalas 1k, 10k y 100k.

## Protocolo de recomendación comercial

- Producto consulta X: artículo de una cesta `(usuario_id, fecha)` con al menos dos artículos distintos.
- Relevantes: los **otros** productos de esa misma cesta; duplicados de `(usuario, fecha, producto)` no aumentan relevancia.
- **Cinco pliegues por usuarios** (`seed=2026`): ningún usuario de test interviene en el cómputo de co-compra del fold de entrenamiento. Contenido estático deriva únicamente del catálogo.
- Fuentes: co-compra, metadatos, descripción (referencia lexical BM25 offline), visual opcional (coseno exacto sobre BoVW indexado). Sin embeddings comerciales, visual se indica **no evaluado**, nunca 0.
- La selección de pesos `fusion_validada` se hace **mediante validación interna sobre usuarios de entrenamiento**, nunca buscando la mejor opción sobre el test. Candidatos predefinidos: iguales, co-compra solamente, co-compra fuerte, co-compra+texto. Se informa por fold qué opción ganó.
- Métricas: `Precision@10`, `Recall@10`, `Hit Rate@10`, `P@3`, `NDCG@10`, `MRR@10`, cobertura del catálogo, máximo posible de `Precision@10` bajo la relevancia de cestas, y expectativa del ranking aleatorio. A igualdad de usuario/cesta, métricas promediadas por caso; todas las comparaciones usan exactamente los mismos casos.

## Resultados previos verificados sobre la muestra del equipo (30 productos)

*Estos números proceden de la ejecución previa del usuario con el primer benchmark. **El script nuevo debe regenerar** resultados antes de compararlos con los de la nueva fusión validada.*

| Fuente | P@10 anterior |
|---|---:|
| Co-compra | 0.071429 |
| Metadatos | 0.005102 |
| Descripción | 0.039796 |
| Fusión con pesos iguales | 0.052041 |
| Fusión que usa solo co-compra | 0.071429 |

Había 196 consultas de cesta y 284 oportunidades de artículos relevantes: máximo `P@10` = **0.144898** para esas consultas. La línea base esperada del azar (10 recomendaciones entre otros 29 productos) es aproximadamente **0.049965**. Por tanto, 0.071429/0.144898 = aproximadamente 49.30% del techo recuperable; **no equivale a 7.14% de exactitud de clasificación**. Muchos casos tienen solo un producto relevante, lo que limita a 0.10 su P@10 individual aun si el ranking es perfecto.

**Una advertencia:** los modelos de texto/visual identifican típicamente sustitutos (producto parecido), pero las etiquetas de la misma cesta premian complementos (laptop + mochila). La comparación es válida para ese objetivo de co-compra y debe describirse así. El dataset de 3,000 figuras geométricas **no cumple #127**, que exige productos auténticos de Amazon/Flipkart con imágenes.

## Archivos del entregable

- `benchmarks/p5_precision_por_fuente.py`: evaluación comercial offline; validación de pesos interna y sin fuga por usuario.
- `tests/test_p5_precision_por_fuente.py`, `tests/test_p5_metrics_extended.py`: pruebas de cestas, separación, métricas y reporte.
- `benchmarks/results/parte5/fuera_de_linea/p5_precision_por_fuente.csv`: tabla nueva del experimento, con columnas de métricas ampliadas.
- `benchmarks/results/parte5/fuera_de_linea/p5_precision_por_fuente.png`: figura lista para el informe.
- `benchmarks/results/parte5/fuera_de_linea/p5_precision_para_informe.md`: texto generado listo para pegar/insertar en el informe.
- `benchmarks/p4_media_retrieval.py` + `tests/test_p4_media_retrieval.py`: prueba separada de Parte 4 usando **las clases reales IVFIndex/HNSWIndex del motor**, con exact-cosine/Euclidean como referencia, medición de construcción, consulta y memoria.
- `benchmarks/results/parte4/`: informes creados al ejecutar los experimentos multimedia. Los audios sintéticos prueban MFCC/BoAW y el pipeline, pero **no demuestran identificación de canciones reales**.

## Cómo ejecutarlo

Desde la raíz del repositorio, con el entorno Python instalado:

```powershell
python -m pytest -q tests/test_p5_precision_por_fuente.py tests/test_p5_metrics_extended.py tests/test_p4_media_retrieval.py
python -m benchmarks.p5_precision_por_fuente --products examples/tienda/productos.csv --purchases examples/tienda/compras.csv --limit 0 --output benchmarks/results/parte5/fuera_de_linea
```

Para recuperar los experimentos de la Parte 4 con el dataset `BD2_Badi_Demo_Data` descomprimido:

```powershell
python -m benchmarks.p4_media_retrieval --mode image --indexed BD2_Badi_Demo_Data/data/geometric/productos_indexados.csv --labels BD2_Badi_Demo_Data/data/geometric/etiquetas.csv --query-csv BD2_Badi_Demo_Data/data/geometric/consultas.csv --query-dir BD2_Badi_Demo_Data/data/geometric/consultas --model-root BD2_Badi_Demo_Data/data/geometric/modelo --limit 300 --query-limit 10 --output benchmarks/results/parte4/imagen
python -m benchmarks.p4_media_retrieval --mode audio --corpus BD2_Badi_Demo_Data/data/audio_synthetic/audios.csv --queries BD2_Badi_Demo_Data/data/audio_synthetic/consultas.csv --audio-dir BD2_Badi_Demo_Data/data/audio_synthetic/audios --query-dir BD2_Badi_Demo_Data/data/audio_synthetic/consultas --limit 150 --query-limit 10 --output benchmarks/results/parte4/audio
```

Esos comandos son un subconjunto de comprobación para la presentación, **no** los tres tamaños completos del enunciado. Si falta material, documentarlo como no ejecutado, no presentar números estimados como medición. No afirmar que las mediciones in-process corresponden a planes SQL/IVF reales del API.

## Estado de entrega

Una vez ejecutado el launcher y confirmado el resultado, el informe queda con la tabla real de 30 productos, la figura y las limitaciones. #141 puede revisarse/aceptarse como **evaluación de la muestra comercial**; la evaluación final de cuatro fuentes con catálogo Amazon/Flipkart depende de #127. El benchmark multimedia satisface una parte de la experimentación de Parte 4, pero no sustituye sus escalas, la galería de errores/aciertos ni la prueba de audio con música real.
