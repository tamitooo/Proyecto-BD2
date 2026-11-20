# Guion de demostración y presentación — Proyecto BD2

**Producto documental, no video grabado.** Fecha de preparación: 19/11/2026. La presentación debe combinar el trabajo real de los cinco integrantes. Cualquier resultado no reproducido en el equipo del expositor debe citarse como prueba previa o demostración planeada.

## Demostración de pantalla: objetivo 7 minutos (rango 5–10)

| Tiempo aprox. | Acción de pantalla | Evidencia a presentar |
|---|---|---|
| 0:00–0:35 | Apertura del frontend `Motor`/`Tienda` y explicación de arquitectura | React → FastAPI → motor propio |
| 0:35–1:25 | Parte 1: consulta con `WHERE`, `JOIN`, `ORDER BY`, índices y `EXPLAIN` | Tabla y plan de acceso; no inventar métricas |
| 1:25–2:10 | Parte 2: abrir mapa, k-NN/rango con ubicación | Mapa Leaflet; R-Tree y distancias |
| 2:10–2:55 | Parte 3: texto `MATCH`/BM25, resultados relevantes | Resultado SQL y puntajes |
| 2:55–4:00 | Parte 4: subir PNG y WAV, ejecutar `SIMILAR_TO`, ver thumbnails/reproducción | SIFT, MFCC, BoVW/TF-IDF, IVF/HNSW |
| 4:00–5:30 | Parte 5: buscar producto, detalle, recomendaciones y stock cercano | Catálogo, co-compra, metadatos, visual y fusión |
| 5:30–6:30 | Mostrar CSV de compras/tiendas y evaluación P@10 | Ficheros y métricas *efectivamente medidas* |
| 6:30–7:00 | Limitaciones y cierre | Dataset real faltante / evaluación del motor pendiente |

Verificar **antes** de grabar: los CSV cargaron; el índice `idx_productos_embedding` y `idx_tiendas_ubicacion` aparece en la API; todos los archivos de medios devuelven 200; el panel SQL proyecta columna `imagen`/`archivo`; la consulta de ubicación usa un centro válido. Si falla una funcionalidad, **no presentar una captura anterior como evidencia de ejecución nueva**.

## Presentación oral: 15 minutos + 5 minutos de preguntas

1. **Portada — 0:35:** objetivo del minigestor multimodal, alcance de Partes 1–5.
2. **Arquitectura — 1:10:** React/Vite → FastAPI → QueryExecutor, catálogo/índices.
3. **Partes 1 y 2 — 1:20:** heap/secuencial, B+ y hash, R-Tree espacial.
4. **Partes 3 y 4 — 1:20:** BM25, SIFT/MFCC, BoVW/TF-IDF, HNSW/IVF.
5. **Tienda (Parte 5) — 1:20:** búsqueda, detalles, metadatos, co-compra, visual, stock.
6. **Dataset geométrico — 1:15:** 3 000 imágenes, 90 consultas, tamaños 160×160, etiquetas separadas.
7. **Resultados visuales — 1:20:** P@10 figura 0.6833 y color 0.1611 en un **baseline coseno exacto offline** de figuras dispersas; NO atribuir estos valores a IVF/SQL sin volver a medir. Comparar con SQL real y declarar limitación SIFT en grises.
8. **CSV, tiendas y compras — 1:15:** 30 tiendas ficticias, 7 603 filas de stock y 4 000 compras en corpus de prueba.
9. **Evaluación de compra sin fuga — 1:30:** leave-last-one-out; P@10 = aciertos/10; alta dispersión de compras.
10. **Pruebas y robustez — 1:10:** determinismo, claves, idempotencia, protección de vocabularios.
11. **Limitaciones — 1:00:** pendiente Amazon/Flipkart, evaluación contra SQL final, ejecución integral en nuevo checkout.
12. **Conclusiones — 0:45:** evidencia reproducible y plan de integración con responsables de cada módulo.

## Preguntas esperables (preparar 5 minutos)

**¿Por qué la precisión visual por color es baja?** El SIFT del backend convierte RGB a gris; mide gradientes y luminancia, no el tono explícito. Una mejora futura sería concatenar o fusionar histogramas de color, evaluándolos separadamente.

**¿Son productos de Amazon/Flipkart?** No. El corpus geométrico es un benchmark sintético reproducible. El issue #127 pide además un dataset externo real que debe descargarse con procedencia y verificar derechos de uso.

**¿Cómo evitan fuga de datos?** El test oculta la compra cronológicamente última de cada usuario; únicamente las compras anteriores alimentan la fuente de co-compra. Se usa la compra oculta solo para decidir relevancia.

**¿Por qué P@10 de co-compra puede ser bajo?** 3 000 productos y 4 000 compras producen un historial disperso. Muchos productos tienen muy pocos compradores. Debe compararse contra el baseline, aumentar densidad de interacciones y medir más de un corte temporal.

**¿Qué garantiza que R-Tree/IVF se use?** Revisar los índices registrados y el plan `EXPLAIN`, no deducirlo solo de que el SQL respondió. Los tests de integración del motor deben comprobar persistencia y reutilización.

**¿La creación de 3 000 imágenes equivale al tiempo de importación?** No. La generación se midió por separado; la importación debe cronometrarse en el mismo equipo, con la base y el API definitivos. Las cifras de una corrida previa no constituyen SLA para todos los equipos.
