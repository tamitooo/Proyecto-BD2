# BD2 — Issues #127 y #129: entrega de datos reales y afinidades de compras

## Estado honesto y criterios

**#127:** la solución usa `EmbeddingStudio/amazon-products-with-images` (muestra pública de fichas de productos de Amazon, ~24 mil registros, con imágenes embebidas). El launcher produce **2000 productos reales con imagen local**, `productos.csv`, `productos_indexados.csv`, `modelo/bow_image.npz` entrenado con SIFT + K-Means/BoVW/TF-IDF y metadatos de procedencia. La aceptación completa requiere que el runner termine con éxito y que la base importe todas las filas. **No existe dataset real completado solo por descargar este ZIP.**

**#129:** el historial es **sintético, pero basado en afinidades comerciales explícitas** (ejemplos: laptop/mochila, celular/audífonos, toys/games, home/kitchen). Cada producto se vincula con otros de una categoría complementaria o con productos de su misma categoría cuando no hay pareja válida. Cestas con dos productos, usuarios independientes y fecha compartida; IDs y claves foráneas verificadas. No presentarlo como compras reales de usuarios de Amazon.

## Doble clic

1. Descargar el ZIP y **extraerlo completamente** (no abrir el CMD desde dentro del ZIP).
2. Para prueba inmediata de #129: `START_FAST_129_DEMO.cmd`. Genera `data/issue127129_sample` con la muestra de 30 productos (no cumple #127).
3. Para datos reales: `START_FULL_127_129.cmd`. Necesita Internet, Python del venv y SIFT/OpenCV instalados. Instala `datasets` si hace falta. Descarga imágenes embebidas, prepara el corpus, entrena un único vocabulario BoVW, genera compras y stock, inicia una API aislada en el puerto **8017**, importa CSV y crea IVF + R-Tree, prueba co-compras y apaga esa API.
4. La salida es **reanudable** en caso de interrupción: vuelve a hacer doble clic. No mezcla el dataset con la base principal.

Para compartir el código y el CSV de ejemplo inmediatamente, ejecuta `PUSH_CODE_127_129.cmd`. Eso crea una rama independiente desde `origin/main`, corre las pruebas y hace push **sin subir imágenes**. La rama sola NO es prueba de haber completado #127; ejecuta el Full para conseguir datos reales.

Los archivos grandes quedan en `Proyecto-BD2-clean/data/issue127129_amazon/` y el motor aislado en `Proyecto-BD2-clean/data/issue127129_engine/`. **No agregar las imágenes ni archivos voluminosos al repositorio Git público.**

### Evidencia para el equipo

- `data/issue127129_amazon/productos.csv`: catálogo real de Amazon (6 columnas, 2000 filas).
- `data/issue127129_amazon/imagenes/`: fotografías locales de esos productos, redimensionadas sin dibujos artificiales.
- `data/issue127129_amazon/productos_indexados.csv` y `modelo/bow_image.npz`: descriptores SIFT, vocabulario y vectores persistentes.
- `data/issue127129_amazon/compras.csv`: cestas sintéticas con categorías afines.
- `data/issue127129_amazon/tiendas.csv`, `stock.csv`: 30 tiendas en Lima y stock de cada producto.
- `data/issue127129_amazon/issue127129_online_report.json`: **prueba en API real** de recuentos, índices y recomendaciones.
- `data/issue127129_amazon/issue129_copurchase_examples.csv`: ejemplos de recomendaciones producto X → producto Y para informe y exposición.

### Cómo arrancar la demo con la base ya importada

```powershell
cd "$HOME\Documents\projects\Proyecto-BD2-clean"
$env:BD2_DATA_DIR = "$HOME\Documents\projects\Proyecto-BD2-clean\data\issue127129_engine"
& "$HOME\Documents\projects\Proyecto-BD2\.venv\Scripts\python.exe" -m uvicorn backend.api:app --port 8000
```
En otra consola: `cd frontend; npm run dev`. Visualizar catálogo en `http://localhost:5173/#tienda`.

### Verificación sin API

```powershell
& "$HOME\Documents\projects\Proyecto-BD2\.venv\Scripts\python.exe" -m tools.verify_127_129 --dataset data/issue127129_amazon
```

### Licencia y procedencia

El dataset de terceros indica **Apache-2.0 en su ficha de Hugging Face**, pero eso no constituye una garantía sobre derechos de imágenes originales de Amazon. Para demo académica local, conservar la atribución al publicador y no redistribuir las imágenes sin revisar derechos/licencias. Las compras y tiendas se generan sintéticamente y NO son transacciones reales.

### Problemas conocidos y limitaciones

- Si el acceso a Hugging Face falla o el dataset no ofrece suficientes imágenes válidas, el script falla explícitamente y puede reanudarse; no inventa fotos ni productos.
- La construcción de 2k descriptores SIFT y la importación con IVF requieren tiempo y espacio en disco; no interrumpir la generación una vez iniciada si la exposición está próxima.
- La co-compra evalúa asociaciones simuladas. Medir Precision@10 con un split por usuarios para el dataset final y dejar claro que no son ventas observadas.
- Las validaciones de producción se confirman **solo** cuando `issue127129_online_report.json` muestra `live_import_passed: true`.
