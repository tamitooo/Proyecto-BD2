# Extracción de características multimedia (Parte 4, sección 2.4.1)

## 1. El requisito

El enunciado pide una función `ExtractFeatures(objeto)` que convierta imágenes y
audio en vectores para buscar contenido similar. La pipeline no es “un vector
cualquiera”:

```text
Extracción de patrones locales
  imágenes -> SIFT
  audio    -> MFCC

Cuantización BoVW/BoAW
  K-Means o Tree Quantization sobre los descriptores
  -> K centroides = K palabras visuales/auditivas

Histograma + TF-IDF
  cada descriptor -> palabra más cercana
  frecuencia de cada palabra
  peso TF-IDF con el IDF del corpus
  -> vector de dimensión K
```

La pieza que más se olvida es que **el vocabulario y el IDF son compartidos**.
Se entrenan una vez sobre una muestra del corpus, se guardan y se usan igual al
indexar y al consultar. Si cada objeto entrenara su propio K-Means, los vectores
de dos imágenes no estarían en el mismo espacio y el coseno no significaría
nada.

## 2. Implementación en el repositorio

| Pieza | Archivo |
|---|---|
| SIFT denso | `vector/sift.py` |
| K-Means, BoVW, TF-IDF y modelo persistido | `vector/bow.py` |
| `ExtractFeatures` y resolución de archivos | `vector/extract_features.py` |
| Entrenamiento del vocabulario | `tools/train_feature_model.py` |
| Datos de demo | `tools/seed_media_demo.py` |
| Demo sin servidor | `examples/demo_media.py` |
| SQL | `EXTRACT_FEATURES('archivo')` y `SIMILAR_TO('archivo', k=N)` |
| Panel | `frontend/src/panels/MultimediaPanel.tsx` |

## 3. SIFT

### 3.1 Backend OpenCV opcional y fallback denso

`vector/sift.py` elige el backend en tiempo de ejecución:

- **OpenCV instalado** (`opencv-python-headless`): usa `cv2.SIFT_create()`, el
  SIFT estándar con detección de extremos DoG, asignación de orientación y
  descriptor de 128 dimensiones.
- **OpenCV no instalado**: usa el SIFT denso propio que se describe abajo.

El backend se guarda en el vocabulario (`descriptor_backend`). Si se entrena con
un backend y se consulta con otro, `ExtractFeatures` avisa y pide reentrenar:
los descriptores de OpenCV y los densos no comparten exactamente el mismo
espacio.

El SIFT denso propio funciona así:

1. **Pirámide de escalas** `1, 1/2, 1/4`: mantiene la invariancia de escala.
2. **Keypoints** en una rejilla cada 8 píxeles de cada nivel; se acota el número
   total para que el costo sea predecible.
3. **Orientación dominante**: histograma de 36 bins de gradientes en el parche
   16×16, ponderado por magnitud y ventana gaussiana.
4. **Parche rotado** según la orientación dominante; se muestrea con
   interpolación bilineal.
5. **Descriptor 4×4×8 = 128 dimensiones**: 4×4 celdas, 8 orientaciones por
   celda, ponderadas por magnitud y ventana gaussiana.
6. **Normalización SIFT**: L2, recorte a 0.2 y nueva normalización L2. El
   recorte reduce el efecto de gradientes muy dominantes (Lowe, 2004).

El fallback denso no hace la detección DoG, pero conserva el descriptor local,
la escala y la orientación de SIFT. La ventaja es que funciona sin dependencias
y produce un número estable de descriptores en imágenes pequeñas.

### 3.2 Límite importante

SIFT trabaja en escala de grises y describe **gradientes**. Una imagen de color
liso (por ejemplo, un rectángulo rojo sin textura) no tiene gradientes y produce
**cero descriptores**. En ese caso `ExtractFeatures` devuelve un error claro:

```text
no se detectaron descriptores IMAGE en 'foto.jpg';
usa una imagen con textura o un audio con señal
```

Para las demos se usan patrones (barras, cuadros, anillos) justamente para que
SIFT tenga textura. Una foto real normalmente sí tiene textura.

## 4. MFCC

Para audio se calcula MFCC por trama, que es el descriptor local:

1. WAV PCM; si el archivo es MP3/OGG/FLAC/M4A se convierte a WAV mono 16 kHz
   con `ffmpeg`. Se promedian canales si es estéreo.
2. Se quita la componente continua y se aplica pre-énfasis
   `y[n] = x[n] - 0.97 x[n-1]`.
3. Tramas de 25 ms con salto de 10 ms y ventana de Hamming.
4. FFT y potencia espectral.
5. Banco de 26 filtros triangulares en escala Mel:

```text
mel(f) = 2595 log10(1 + f / 700)
```

6. Logaritmo y DCT-II. Se descarta el coeficiente 0 (energía global) y se
   conservan 20 coeficientes de timbre.
7. Cada trama es un descriptor de 20 dimensiones; **no** se promedia todavía.
   La media/desviación se sustituye por la cuantización BoAW del paso
   siguiente.

La conversión de formatos comprimidos usa `ffmpeg` si está instalado y en el
PATH. Si no está, el error lo indica y sugiere convertir el archivo a WAV. Esta
es la forma más robusta de aceptar `.mp3` sin agregar un decodificador pesado
al proyecto.

## 5. Bag of Visual/Audio Words con K-Means

### 5.1 Entrenamiento

`vector/bow.py` implementa K-Means:

- inicialización **K-Means++** (Arthur y Vassilvitskii, 2007);
- asignación por distancia euclidiana al cuadrado, en bloques para no llenar la
  memoria;
- actualización de centroides (Lloyd);
- reinicialización de clusters vacíos;
- semilla fija para reproducibilidad.

A partir de los descriptores del corpus:

```text
D = {d_1, ..., d_n}          descriptores locales de todas las imágenes/audios
C = {c_1, ..., c_K}          K centroides aprendidos con K-Means
```

Cada descriptor `d` se asigna a la palabra:

```text
w(d) = argmin_j ||d - c_j||²
```

### 5.2 Histograma

Para un objeto con descriptores `d_1 ... d_m`:

```text
h[j] = (# descriptores asignados a la palabra j) / m
```

`h` tiene dimensión K, que es la dimensión del vector final. Los valores se
normalizan por el número de descriptores para que objetos con más keypoints no
dominen por cantidad.

### 5.3 Elección de K

- Demo sintética: `K = 16` visuales y `K = 8` auditivas (pocos archivos).
- Corpus real: se recomienda `K = 64` visuales y `K = 32` auditivas, o
  `K ≈ sqrt(n_descriptores)` acotado.
- K muy grande: histogramas dispersos y K-Means lento.
- K muy pequeño: se pierde capacidad discriminativa.

## 6. TF-IDF

Con `N` documentos del corpus y `df[j]` = número de documentos en los que
aparece la palabra `j`:

```text
idf[j] = log((1 + N) / (1 + df[j])) + 1
```

El `+1` suaviza el caso `df[j] = 0` y evita división por cero. El vector final
es:

```text
v[j] = h[j] * idf[j]
v = v / ||v||₂
```

Así, una palabra que aparece en casi todos los documentos pesa poco, y una
palabra rara pero presente en el objeto pesa más. La normalización L2 hace que
el coseno dependa del contenido y no de la cantidad de descriptores.

`df` se calcula con los histogramas de todos los documentos de entrenamiento,
no con la consulta. La consulta usa el mismo IDF guardado en el modelo.

## 7. Modelo persistido

`FeatureModel` guarda:

- `kind`: `image` o `audio`;
- `n_words`: K;
- `descriptor_dim`: 128 para SIFT, 20 para MFCC;
- `centroids`: matriz `(K, descriptor_dim)`;
- `idf`: vector `(K,)`;
- media/desviación usadas para estandarizar (solo audio);
- `n_documents`, versión y bandera de estandarización.

Se guarda con `numpy.savez_compressed` en:

```text
<data_dir>/models/bow_image.npz
<data_dir>/models/bow_audio.npz
```

El mismo archivo se usa en `EXTRACT_FEATURES` (indexación) y en
`SIMILAR_TO('archivo')` (consulta). Si se cambia el corpus, hay que reentrenar y
reindexar: un vocabulario entrenado con flores no describe bien autos.

## 8. Entrenamiento

### 8.1 Comando

```powershell
# usa backend/data/media (imágenes y WAV de la demo)
python -m tools.train_feature_model

# corpus propio
python -m tools.train_feature_model ^
  --images C:\datasets\fotos ^
  --audio C:\datasets\audios ^
  --image-words 64 --audio-words 32

# solo imágenes
python -m tools.train_feature_model --images backend/data/media --image-words 64
```

Parámetros importantes:

- `--max-files 500`: se entrena con una muestra, no con los 100k archivos.
- `--max-descriptors 20000`: tope de descriptores para K-Means.
- `--max-descriptors-per-file 200`: muestra por archivo; evita que una imagen
  con miles de keypoints domine el vocabulario.
- `--seed 7`: reproducibilidad.

Dependencias opcionales:

```powershell
pip install opencv-python-headless   # SIFT estándar (cv2.SIFT_create)
# ffmpeg en el PATH                 # MP3/OGG/FLAC/M4A -> WAV
```

El modelo guarda el backend SIFT usado (`opencv` o `dense`). Si instalas
OpenCV después de entrenar, vuelve a ejecutar `tools.train_feature_model`; de
lo contrario `ExtractFeatures` avisa que el vocabulario y la consulta usan
descriptores distintos.

El IDF se calcula con todos los documentos procesados (hasta `--max-files`).
Para un dataset muy grande, se puede subir `--max-files` o muestrear carpetas.

### 8.2 Flujo completo con un corpus nuevo

1. Copiar las imágenes/audios a una carpeta accesible.
2. Entrenar:
   ```powershell
   python -m tools.train_feature_model --images .\fotos --audio .\audios
   ```
3. Crear la tabla con una columna `VARCHAR` (K valores, no 128):
   ```sql
   CREATE TABLE fotos (
     id INT PRIMARY KEY,
     nombre VARCHAR(120),
     embedding VARCHAR(4096),
     categoria VARCHAR(32)
   );
   ```
4. Indexar cada archivo:
   ```sql
   INSERT INTO fotos
   VALUES (1, 'foto1.jpg', EXTRACT_FEATURES('foto1.jpg'), 'categoria');
   ```
5. Consultar con cualquier archivo del mismo tipo:
   ```sql
   SELECT id, nombre, categoria, SIMILARITY_SCORE() AS score
   FROM fotos
   WHERE SIMILAR_TO('consulta.jpg', k=5)
   USING HNSW WITH METRIC=cosine;
   ```

## 9. Integración SQL, API y panel

### 9.1 SQL

```sql
-- indexar
INSERT INTO fotos VALUES (1, 'foto.jpg', EXTRACT_FEATURES('foto.jpg'), 'rojo');
UPDATE fotos SET embedding = EXTRACT_FEATURES('otra.jpg') WHERE id = 1;

-- consultar
SELECT id, nombre, SIMILARITY_SCORE() AS score
FROM fotos
WHERE SIMILAR_TO('foto.jpg', k=5)
USING HNSW WITH METRIC=cosine;
```

El plan incluye:

```text
query_source = file
media_kind   = image | audio
media_file   = foto.jpg
feature_mode = bow
n_words      = K
dimension    = K
extract_ms   = ...
```

### 9.2 API y panel

- `POST /api/media/extract` recibe el archivo, lo guarda en
  `<data_dir>/media`, carga el vocabulario de `<data_dir>/models` y devuelve
  `{name, kind, dimension, vector, mode, n_words, elapsed_ms}`.
- El panel sube el archivo, muestra la dimensión K y genera
  `SIMILAR_TO('archivo', k=N)`.
- El panel no proyecta la columna `embedding` en el `SELECT` para que el score
  quede visible sin desplazarse.

## 10. Cómo probar

### 10.1 Pruebas automáticas

```powershell
python -m pytest tests/test_feature_extraction.py -q
python -m pytest tests/test_media_sql.py -q
python -m pytest tests/test_media_engine.py -q
```

Cubren:

| Prueba | Qué demuestra |
|---|---|
| SIFT 128 dims y determinista | descriptor local correcto |
| SIFT imagen lisa = 0 descriptores | comportamiento esperado sin textura |
| MFCC por trama | descriptor local de audio |
| histograma suma descriptores | cuantización BoVW |
| `idf` una entrada por palabra | TF-IDF |
| patrones similares vs distintos | el espacio BoVW separa contenido |
| 440 Hz vs 880 Hz | el espacio BoAW separa audio |
| `save/load` del modelo | persistencia |
| `SIMILAR_TO('foto.jpg')` | integración SQL |
| `EXTRACT_FEATURES` en INSERT/UPDATE | indexación |
| sin vocabulario | error claro |

### 10.2 Demo reproducible

```powershell
python -m examples.demo_media
```

Salida esperada (resumida):

```text
Vocabulario BoVW: 16 palabras visuales, 8 palabras auditivas

> ... WHERE SIMILAR_TO('consulta_rojo.png', k=3) USING HNSW WITH METRIC=cosine
   1 rojo.png      rojo   0.9979
   2 rojo_2.png    rojo   0.9461
   4 verde.png     verde  0.1301
  plan: HNSW_KNN | origen: file | tipo: image | dimensión: 16 | palabras: 16
  fuerza bruta: [(1, 0.9979), (2, 0.9461), (4, 0.1301)]
  coincide: True
```

### 10.3 Datos de demo para el panel

```powershell
python -m tools.seed_media_demo
```

Crea `fotos_demo` y `audios_demo` con el vocabulario ya entrenado. Archivos de
consulta en `backend/data/media/`:

```text
consulta_rojo.png
consulta_azul.png
consulta_440.wav
foto.jpg
```

## 11. Limitaciones y decisiones

- **SIFT: OpenCV opcional, fallback denso.** Si `opencv-python-headless` está
  instalado se usa `cv2.SIFT_create()` (DoG + keypoints). Si no, se usa el SIFT
  denso propio. El vocabulario guarda `descriptor_backend` y `ExtractFeatures`
  rechaza mezclar backends: si instalas OpenCV después de entrenar, reentrena.
  Para la rúbrica que exige SIFT exacto, instala OpenCV y vuelve a entrenar.
- **Imágenes sin textura.** Un color liso no genera descriptores SIFT. Es una
  propiedad del algoritmo, no un bug. Hay que usar imágenes con bordes/textura
  o complementar con otro descriptor (color) si el dominio lo requiere.
- **El vocabulario depende del corpus.** Un modelo entrenado con flores no
  representa bien autos. Reentrenar y reindexar al cambiar de dataset.
- **K y tamaño de la muestra.** K muy grande con pocos descriptores produce
  clusters vacíos o poco estables; el entrenador reduce K si hay menos
  descriptores que palabras.
- **Costo.** SIFT es más caro que un histograma de color; el `extract_ms` se
  reporta en el plan. La consulta sigue reconstruyendo HNSW/IVF en cada
  ejecución (punto 2 del feedback, pendiente).
- **Audio comprimido.** WAV PCM es nativo. MP3/OGG/FLAC/M4A se convierten a WAV
  con `ffmpeg`; si no está instalado, el error pide instalarlo o convertir el
  archivo. No se agregó un decodificador MP3 en Python para no sumar una
  dependencia pesada.
- **El IDF se calcula sobre la muestra de entrenamiento.** Para 100k archivos
  conviene aumentar `--max-files` o muestrear el corpus de forma estratificada.
- **La columna `VARCHAR` debe dimensionarse para K.** Con K=64 y 6 decimales,
  `VARCHAR(4096)` es más que suficiente; con K muy grande, subir el tamaño.

## 12. Preparación para la exposición

### 12.1 Diagnóstico

```powershell
python -m tools.check_media_deps
```

Antes de instalar nada, en este entorno sale:

```text
SIFT backend disponible: dense
  OpenCV: no instalado -> pip install opencv-python-headless
  ffmpeg: no encontrado -> winget install Gyan.FFmpeg
  modelo image: 16 palabras, descriptor 128-D, backend=dense
  modelo audio: 8 palabras, descriptor 20-D (MFCC)
  audio MP3/OGG/...: no hasta instalar ffmpeg
  SIFT OpenCV: no; se usa SIFT denso
```

### 12.2 Instalar lo opcional

```powershell
# SIFT estándar
pip install -r requirements-optional.txt

# ffmpeg (no es pip)
winget install Gyan.FFmpeg
# o: choco install ffmpeg
ffmpeg -version
```

Reiniciar el backend después de instalar `ffmpeg` para que tome el PATH.

### 12.3 Reentrenar si instalaste OpenCV

Los descriptores de OpenCV y los densos no son iguales. El modelo guarda
`descriptor_backend`; si no coincide con el backend actual, `ExtractFeatures`
rechaza la consulta. Hay que reentrenar y reindexar:

```powershell
# detener el backend
python -m tools.seed_media_demo
# volver a levantar backend/api.py
```

Con un corpus propio:

```powershell
python -m tools.train_feature_model --images <fotos> --audio <audios>
# y reindexar las tablas con EXTRACT_FEATURES
```

Con `ffmpeg` no hace falta reentrenar: el MP3 se convierte a WAV mono 16 kHz y
se aplica el mismo MFCC.

### 12.4 Probar MP3

```sql
SELECT id, nombre, SIMILARITY_SCORE() AS score
FROM audios_demo
WHERE SIMILAR_TO('audio_query.mp3', k=5)
USING IVF WITH METRIC=euclidean
ORDER BY score DESC;
```

Si `ffmpeg` falta, el error pide instalarlo o convertir a WAV. No hay fallback
silencioso a un decoder incompleto.

## 13. Referencias

- Lowe, D. G. (2004). *Distinctive image features from scale-invariant
  keypoints*. International Journal of Computer Vision, 60(2), 91-110.
- Sivic, J. y Zisserman, A. (2003). *Video Google: A text retrieval approach to
  object matching in videos*. ICCV.
- Csurka, G., Dance, C., Fan, L., Willamowski, J. y Bray, C. (2004). *Visual
  categorization with bags of keypoints*. ECCV Workshop.
- Arthur, D. y Vassilvitskii, S. (2007). *k-means++: The advantages of careful
  seeding*. SODA.
- Davis, S. y Mermelstein, P. (1980). *Comparison of parametric representations
  for monosyllabic word recognition in continuously spoken sentences*. IEEE
  Transactions on Acoustics, Speech, and Signal Processing, 28(4), 357-366.
- Manning, C. D., Raghavan, P. y Schütze, H. (2008). *Introduction to
  Information Retrieval*. Cambridge University Press (TF-IDF y coseno).
