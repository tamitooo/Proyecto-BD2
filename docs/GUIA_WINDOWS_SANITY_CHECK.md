# BD2 — Guía paso a paso para Windows: instalar, importar, ejecutar y certificar

**Repo:** https://github.com/tamitooo/Proyecto-BD2

**Este parche es un overlay, no un repositorio completo ni un PR publicado.** No borra `main`, no sobrescribe los componentes de los demás integrantes sin comparar sus SHA, y no contiene la adquisición de datos reales exigida por #127. No marques un issue como completado sin test de aceptación.

## 0. Requisitos

- Windows con PowerShell, Git, **Python 3.12**, **Node.js** compatible con el proyecto y opcionalmente Docker Desktop. Recomendado OpenCV para corpus grandes.
- Archivo `BD2_Badi_Implementation_Patch_v2.zip` (contiene `BD2_Badi_Patch/`) y, para los datos generados, `BD2_Badi_Demo_Data_Scattered_3000.zip`.
- No trabajar directamente sobre `main` ni mezclar vocabularios BoVW entre bases distintas.

## 1. Clonar y crear rama

```powershell
git clone https://github.com/tamitooo/Proyecto-BD2.git
cd Proyecto-BD2
git switch main
git pull --ff-only origin main
git switch -c feat/badi-scattered-dataset-tests
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install opencv-python-headless
```

## 2. Aplicar cambios sin sobrescribir a compañeros

Extraer `BD2_Badi_Implementation_Patch_v2.zip` **FUERA** del repositorio, por ejemplo en `C:\BD2_Descargas`. Cambiar la ruta según donde lo hayas extraído.

```powershell
.\.venv\Scripts\python.exe C:\BD2_Descargas\BD2_Badi_Patch\apply_bd2_patch.py --repo . --dry-run
.\.venv\Scripts\python.exe C:\BD2_Descargas\BD2_Badi_Patch\apply_bd2_patch.py --repo .
git status --short
```

Si el verificador indica `refusing to overwrite` o que `ResultsPanel.tsx changed`, **no fuerces la instalación**: alguien modificó un archivo; integra manualmente ese componente comparando el archivo con `frontend/src/panels/ResultsPanel.tsx` del parche. La prevalidación evita cambios parciales ante un conflicto.

## 3. Extraer datasets (dos bases distintas)

```powershell
Expand-Archive -Path C:\BD2_Descargas\BD2_Badi_Demo_Data_Scattered_3000.zip -DestinationPath . -Force
```

Los datos quedarán en:

- `BD2_Badi_Demo_Data/data/geometric` — 3000 páginas con formas dispersas + 90 consultas.
- `BD2_Badi_Demo_Data/data/part5_synthetic` — mismos productos + 30 tiendas ficticias, stock y compras.
- `BD2_Badi_Demo_Data/data/audio_synthetic` — WAV de prueba, 1000 audios y 100 consultas.

Comprobar integridad sin ejecutar servidor:

```powershell
.\.venv\Scripts\python.exe -m tools.generate_geometric_dataset --verify --output BD2_Badi_Demo_Data/data/geometric
.\.venv\Scripts\python.exe -m tools.generate_part5_data --verify BD2_Badi_Demo_Data/data/part5_synthetic
.\.venv\Scripts\python.exe -m tools.generate_audio_dataset --verify BD2_Badi_Demo_Data/data/audio_synthetic
```

## 4. Arrancar backend y frontend (2 terminales)

**Terminal A**: desde la raíz de `Proyecto-BD2`. Primero prueba la TIENDA, con su propia carpeta de datos limpia:

```powershell
$env:BD2_DATA_DIR = (Join-Path (Get-Location) "backend/data/badi_store_test")
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --port 8000
```

**Terminal B**, misma raíz, otro PowerShell:

```powershell
cd frontend
npm ci
npm run dev
```

Abre **http://localhost:5173** (pestañas `Motor` y `Tienda`) y **http://127.0.0.1:8000/docs** para Swagger. Si PowerShell bloquea la activación del venv, ejecuta el `python.exe` directamente como en estos comandos; no es necesario activar scripts.

## 5. Cargar tienda sintética completa y verificar

**Terminal C**, desde la raíz del repositorio (no dentro de `frontend`):

```powershell
.\.venv\Scripts\python.exe -m tools.seed_part5_fast --dataset BD2_Badi_Demo_Data/data/part5_synthetic --data-dir backend/data/badi_store_test
.\.venv\Scripts\python.exe -m tools.verify_badi_release --mode store --dataset BD2_Badi_Demo_Data/data/part5_synthetic --output benchmarks/results/parte5/store_sanity.json
```

**Debe pasar:** tablas `productos`, `tiendas`, `stock`, `compras`; 3000 productos; 30 tiendas; sin productos sin stock; IVF `idx_productos_embedding`, R-Tree `idx_tiendas_ubicacion`; búsqueda visual SQL funcional; `GET /api/media/...` sirve miniaturas. Abre `#tienda`, usa búsqueda, ficha, fusión de fuentes y tiendas cercanas. Luego corre:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.benchmark_part5_precision --products BD2_Badi_Demo_Data/data/part5_synthetic/productos.csv --purchases BD2_Badi_Demo_Data/data/part5_synthetic/compras.csv --indexed BD2_Badi_Demo_Data/data/part5_synthetic/productos_indexados.csv --output benchmarks/results/parte5
```

**Advertencia:** el benchmark anterior es OFFLINE, no la evaluación SQL/IVF/fusión de producción necesaria para cerrar #141. Los registros son figuras, no mercancía real (también faltante para #127). No reportar los scores como evaluación real de e-commerce.

## 6. Probar la búsqueda geométrica aislada

Detén **Terminal A** con `Ctrl+C`. Desde su misma raíz, cambia `BD2_DATA_DIR` por una carpeta **diferente**, y vuelve a levantar el backend:

```powershell
$env:BD2_DATA_DIR = (Join-Path (Get-Location) "backend/data/badi_geometry_test")
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --port 8000
```

En **Terminal C**, raíz del repo:

```powershell
.\.venv\Scripts\python.exe -m tools.seed_geometric_dataset --dataset BD2_Badi_Demo_Data/data/geometric --data-dir backend/data/badi_geometry_test
.\.venv\Scripts\python.exe -m tools.verify_badi_release --mode geometric --dataset BD2_Badi_Demo_Data/data/geometric --output benchmarks/results/geometric/ivf_sanity.json
.\.venv\Scripts\python.exe -m benchmarks.benchmark_geometric_retrieval --dataset BD2_Badi_Demo_Data/data/geometric --output benchmarks/results/geometric
.\.venv\Scripts\python.exe -m benchmarks.benchmark_geometric_exact --dataset BD2_Badi_Demo_Data/data/geometric --output benchmarks/results/geometric_exact
```

En `Motor` prueba:

```sql
SELECT id, nombre, categoria, imagen, SIMILARITY_SCORE() AS score
FROM figuras
WHERE SIMILAR_TO('consulta_geom_0001.png', k=10) USING IVF WITH METRIC=cosine;
```

**Control manual:** cada fila debe mostrar imagen PNG junto a la puntuación; abrir una miniatura debe llamar a `/api/media/geom_XXXXXX.png` y devolver HTTP 200. Si eliges `SELECT id, score` sin columna `imagen`, no aparecerá miniatura (comportamiento esperado). El panel `Tienda` es propio del modo `store`; en modo `geometry` sólo existe `figuras`.

## 7. Audio sin mezclarse con vocabulario de imágenes

El dataset WAV sintético se genera/valida con:

```powershell
.\.venv\Scripts\python.exe -m tools.generate_audio_dataset --verify BD2_Badi_Demo_Data/data/audio_synthetic
```

Los archivos 16kHz/16-bit PCM pueden entrenarse con `tools.train_feature_model` usando una carpeta de datos propia (consulta `docs/INTEGRACION_PARTE5.md`). La interfaz `ResultsPanel` reproduce una columna `archivo_audio`/`archivo`/`nombre` si contiene un `.wav` accesible en `BD2_DATA_DIR/media`. **La generación de audios y el reproductor no implican por sí solos que un índice de audio esté entrenado o que `SIMILAR_TO(audio)` pase.** Para esa evidencia, entrenar vocabulario, crear tabla e índice y ejecutar una consulta audio real.

## 8. Tests y build antes de pedir revisión

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
cd ..
```

La presencia de archivos no significa que la prueba esté aprobada. Copia las salidas del terminal y conserva los JSON en `benchmarks/results`; no inventes cifras. Los tests de la suite de integración requieren el checkout completo del proyecto.

## 9. Arranque rápido con Docker (SOLO la muestra incluida en main)

```powershell
docker compose up --build
```

El `docker-compose.yml` del equipo monta un **volumen Docker** `/data` y ejecuta automáticamente el cargador `tools.seed_tienda` de **30 productos**. Los cargadores `seed_part5_fast` ejecutados en Windows **NO escriben en ese volumen**; no mezclar esos pasos. Para datos de 3000, usar primero la opción nativa del paso 4 y mantener `BD2_DATA_DIR` separado. `docker compose down -v` borra el volumen: **no usarlo si quieres conservar datos**.

## 10. Entrega y cierre formal de issues

1. Revisar `git diff --check`, `git status`, `git diff --stat`.
2. Ejecutar el suite completo, generar JSON de auditoría y capturas de navegador.
3. `git add tools tests benchmarks docs frontend/src && git commit -m "feat(bd2): randomized geometry, part5 fixtures and media previews (#127 #128 #129 #125 #126 #141 #142)"`.
4. `git push -u origin feat/badi-scattered-dataset-tests` y abrir PR a `main` para revisión del equipo.
5. Cerrar un issue **sólo después** de cumplir su criterio. No incluir `Closes #127`, `Closes #141`, `Closes #143`, `Closes #144` automáticamente: aún requieren datos reales, integración del evaluador, informe unificado y video.

**No se ha creado el PR por ti ni se ha ejecutado el build completo del repo en este entorno.**
