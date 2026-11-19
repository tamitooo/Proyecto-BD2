# Parte 5 — Fuente visual del recomendador (Persona 3: issues g y h)

Este documento cubre la parte de Persona 3:

| Issue | Qué entrega | Dónde |
|---|---|---|
| g | Vectores de imágenes: vocabulario BoVW, `EXTRACT_FEATURES` e índice IVF | `recommender/visual.py`, `tools/seed_tienda.py`, SQL |
| h | Recomendación visual desde X y búsqueda con imagen subida | `recommend_by_visual`, `search_by_image`, `frontend/src/tienda/visual.ts`, `BusquedaVisual.tsx` |
| p | Pruebas de g/h | `tests/test_recommender_visual.py` |
| q | README/informe | este documento |
| r | Video/presentación | guion al final |

## 1. Contrato compartido

Cada recomendación cumple el contrato del equipo:

```json
{"producto_id": 12, "score": 0.93, "fuente": "visual",
 "evidencia": {"modo": "producto", "metrica": "cosine", "score_motor": 0.91}}
```

- `score` alto = más recomendado.
- Nunca incluye el producto X.
- Orden `score DESC, producto_id ASC`.
- Para coseno se transforma a `(cos + 1) / 2`, así queda en `[0, 1]`.
- Persona 5 normaliza igualmente por consulta; el orden es lo que importa.

## 2. Datos y carga (issue g)

El cargador de Persona 5 ya hace la parte pesada:

```powershell
python -m tools.seed_tienda
```

Pasos relevantes:

1. copia el vocabulario `examples/tienda/modelo/bow_image.npz` y las imágenes a
   `<data_dir>/models` y `<data_dir>/media`;
2. crea `productos` con `embedding VARCHAR(2048)`;
3. inserta cada producto con `EXTRACT_FEATURES(imagen)`;
4. crea el R-Tree de tiendas y el IVF de productos.

La muestra tiene 30 productos con imagen y un vocabulario BoVW de 16 palabras.
Para el dataset completo de Persona 1 se reemplazan los CSV/imágenes y se
repite el mismo cargador.

### Índice IVF

```sql
CREATE INDEX idx_productos_embedding
ON productos (embedding)
USING IVF WITH METRIC=cosine;
```

`SIMILAR_TO` reutiliza el índice persistente si la métrica coincide; si no
existe, construye uno temporal. El plan de `EXPLAIN` lo reporta con
`persistent=True`, `n_lists` y `n_probe`.

## 3. Recomendación desde X (issue h)

`recommend_by_visual(engine, producto_id, k=10, metric="cosine")`:

1. lee `productos.embedding` de X;
2. llama `SIMILAR_TO([...], k+1) USING IVF WITH METRIC=cosine`;
3. descarta X;
4. devuelve como máximo `k` `Recommendation`.

Uso:

```python
from recommender import recommend_by_visual

for item in recommend_by_visual(engine, producto_id=1, k=10):
    print(item.as_dict())
```

No se usa una subconsulta en SQL porque el parser no la soporta; el embedding
se lee en una consulta y se pasa como literal a la segunda. Es el mismo patrón
que usan las fuentes de Persona 4.

## 4. Búsqueda subiendo una imagen (issue h)

`search_by_image(engine, imagen, k=10, media_root=..., model_root=...)`:

1. `ExtractFeatures.extract(imagen)` calcula el vector BoVW;
2. `SIMILAR_TO([...], k) USING IVF WITH METRIC=cosine`;
3. devuelve productos; no hay X que excluir.

En el frontend:

- `buscarPorImagen(file)` sube la imagen a `/api/media/extract`;
- el backend la guarda en `<data_dir>/media` y devuelve su nombre;
- la consulta usa `SIMILAR_TO('nombre', k=10)`;
- `BusquedaVisual.tsx` muestra el top-10.

## 5. Integración con el panel

- `frontend/src/tienda/visual.ts`: consultas SQL y llamada a
  `/api/media/extract`.
- `frontend/src/tienda/BusquedaVisual.tsx`: input de archivo y resultados.
- `frontend/src/tienda/fuentes.ts`: registra la fuente `visual` para la ficha
  de producto y la fusión de Persona 5.
- `Tienda.tsx`: incluye el panel de búsqueda por imagen.

La ficha de producto de Persona 5 mostrará la barra de aportes por fuente; la
fuente visual aparecerá como `Imagen similar`.

## 6. Cómo probar

### 6.1 Instalación mínima (sin OpenCV/librosa)

Usa el Python del venv, no el `pip` global:

```powershell
venv\Scripts\python.exe -m pip install -r requirements-persona3.txt
venv\Scripts\python.exe -m tools.verify_persona3_visual
```

Si `pip --version` muestra Python 3.14 y el venv usa 3.13, estás instalando en
el Python equivocado. Comprueba:

```powershell
venv\Scripts\python.exe --version
venv\Scripts\python.exe -m pip --version
```

### 6.2 Pruebas automáticas

```powershell
venv\Scripts\python.exe -m pytest tests/test_recommender_visual.py -q
venv\Scripts\python.exe -m pytest tests/test_recommender_parte5.py -q
```

Cubren:

- X nunca aparece;
- orden descendente por score;
- `k=0`, producto inexistente y producto sin embedding;
- score en `[0, 1]` para coseno;
- búsqueda por imagen con `EXTRACT_FEATURES`;
- error claro si falta el vocabulario;
- IVF creado con `CREATE INDEX`.

Para la demo:

```powershell
python -m tools.seed_tienda
# backend y frontend levantados
# pestaña Tienda -> elegir producto -> ficha -> "Imagen similar"
# o subir una imagen en "Buscar productos por imagen"
```

### 6.3 Verificación sin servidor

Si quieres comprobar g/h sin instalar OpenCV/librosa ni levantar el backend:

```powershell
python -m tools.verify_persona3_visual
```

El script:

1. copia los 30 productos de muestra a un `data_dir` temporal;
2. entrena un vocabulario BoVW denso;
3. inserta los productos con `EXTRACT_FEATURES`;
4. crea el IVF con `CREATE INDEX ... USING IVF`;
5. ejecuta `recommend_by_visual(1)`;
6. ejecuta `search_by_image(producto_001.png)`;
7. verifica que X no aparezca, el orden sea descendente y el IVF esté en el plan.

Salida esperada (resumida):

```text
1. vocabulario BoVW: 16 palabras, 30 imágenes
2. productos cargados con EXTRACT_FEATURES: 30
3. IVF creado con CREATE INDEX ... USING IVF
4. recommend_by_visual(1): 4, 5, 3, 2, 20
5. search_by_image(producto_001.png): 1, 4, 5, 3, 2
6. EXPLAIN: el IVF persistente aparece en el plan
OK
```

## 7. Dependencias

| Dependencia | Uso |
|---|---|
| Persona 1 | Imágenes y dataset de productos. La muestra de 30 ya está en `examples/tienda`; el dataset completo es de Persona 1. |
| Persona 5 | Fusión, ficha y contrato `{producto_id, score}`. |
| Persona 2 | Catálogo/selector del producto X. |
| Vocabulario BoVW | `bow_image.npz`; si se cambia, hay que regenerar los embeddings. |
| OpenCV/librosa | Solo si el vocabulario se entrenó con ese backend. El fallback denso funciona sin ellas. El modelo de muestra `examples/tienda/modelo/bow_image.npz` fue entrenado con **OpenCV**; si no está instalado, reentrena con `python -m tools.train_feature_model --images examples/tienda/imagenes` o instala OpenCV. |

## 8. Limitaciones

- La calidad visual depende de las imágenes: fondos blancos, fotos repetidas o
  productos de la misma categoría pueden dar resultados poco útiles.
- SIFT/BoVW no entiende semántica; dos productos de distinto tipo con la misma
  forma pueden parecerse.
- El dataset completo de 2k–5k imágenes puede tardar en extraerse; para la
  demo se puede usar una muestra de 500–1000.
- `SIMILAR_TO` sigue construyendo un índice temporal si no existe el IVF
  persistente; para la demo se crea con `CREATE INDEX`.
- Una imagen sin textura no produce descriptores SIFT; el error lo explica.

## 9. Guion de demo (r)

1. Abrir `Tienda`, elegir un producto (X).
2. En la ficha, mostrar `Imagen similar` y explicar que usa el embedding ya
   indexado en IVF.
3. Cambiar el peso de la fuente visual y mostrar cómo cambia el top-10.
4. Subir una imagen en “Buscar productos por imagen”; mostrar los productos
   parecidos y el score.
5. Cerrar con: “el vector se calculó con BoVW/TF-IDF, se guardó en la tabla y
   la búsqueda usa el índice IVF; X nunca se recomienda a sí mismo”.
