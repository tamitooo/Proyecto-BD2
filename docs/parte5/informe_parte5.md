# Informe — Parte 5: tienda con recomendaciones

## 1. Alcance

La Parte 5 usa el motor como base de una tienda en línea. Desde la pestaña
**Tienda** del frontend se puede buscar productos, abrir la ficha de uno (X) y
ver los 10 productos que se le recomiendan, junto con las tiendas cercanas que
tienen stock de X.

Las recomendaciones salen de cuatro fuentes, cada una apoyada en una parte
distinta del motor:

| Fuente | Qué mide | Parte del motor |
|---|---|---|
| Descripción similar | Texto de la descripción | Índice invertido y BM25 (`MATCH`) |
| Imagen similar | Parecido visual de la foto | BoVW con `EXTRACT_FEATURES` e índice IVF (`SIMILAR_TO`) |
| Comprados juntos | Quienes compraron X también compraron Y | Consultas relacionales sobre `compras` |
| Misma categoría y precio | Categoría igual y precio cercano | Consultas relacionales sobre `productos` |

Una fusión de scores las junta en un único top 10. Además, las tiendas
cercanas usan el R-Tree de la Parte 2.

El detalle de cada fuente está en el documento de quien la hizo:

- Búsqueda, catálogo y descripción similar: [persona2_catalogo.md](persona2_catalogo.md)
- Imagen similar y búsqueda por foto: [persona3_visual.md](persona3_visual.md)
- Co-compra, metadatos y tiendas cercanas: [persona4_recomendador.md](persona4_recomendador.md)

Aquí se resume cada fuente y se explica lo que las une: la carga de datos, el
contrato común, la fusión, la ficha de producto y la evaluación.

## 2. Arquitectura

```text
Navegador (React)
  Tienda.tsx ── catálogo, filtros, búsqueda por imagen
      │
      └─ FichaProducto.tsx  (#tienda/producto/<id>)
            │
            ├─ fuenteTexto.ts ─────── POST /api/query   MATCH ... USING BM25
            ├─ visual.ts ──────────── POST /api/query   SIMILAR_TO ... USING IVF
            ├─ fuentesBackend.ts ──── GET /api/recommend/copurchase/<id>
            │                         GET /api/recommend/metadata/<id>
            ├─ fusion.ts ──────────── normaliza, pondera y corta a 10
            └─ TiendasCercanas.tsx ── GET /api/recommend/stores/<id>   (R-Tree)

Backend (FastAPI, backend/api.py)
  /api/query ───────────── QueryExecutor del motor
  /api/recommend/* ─────── recommender/ (co-compra, metadatos, tiendas)
```

Las cuatro fuentes se consultan en paralelo. La fusión se hace en el navegador,
así que al mover el peso de una fuente el top 10 se recalcula sin volver a
consultar al motor.

Co-compra y metadatos se exponen como endpoints y no como SQL desde el
navegador, porque el parser no admite alias, subconsultas ni `IN (...)`. Su
lógica combina varias consultas con una agregación en Python
(`recommender/copurchase.py`, `recommender/metadata.py`). Así el frontend usa
exactamente las mismas funciones que prueban los tests.

## 3. Datos y carga

El esquema está en `recommender/schema.py`:

```sql
CREATE TABLE productos (id INT, nombre VARCHAR(96), categoria VARCHAR(32), precio FLOAT,
                        descripcion VARCHAR(1024), imagen VARCHAR(160), embedding VARCHAR(2048));
CREATE TABLE tiendas   (id INT, nombre VARCHAR(64), lat FLOAT, lon FLOAT, distrito VARCHAR(32));
CREATE TABLE stock     (id INT, tienda_id INT, producto_id INT, cantidad INT);
CREATE TABLE compras   (id INT, usuario_id INT, producto_id INT, fecha VARCHAR(10), cantidad INT);
```

`python -m tools.seed_tienda` carga un dataset por la API del backend:

1. copia las imágenes y el vocabulario BoVW a la carpeta de datos del backend;
2. crea las cuatro tablas;
3. inserta cada producto calculando su vector con `EXTRACT_FEATURES(imagen, 'image')`;
4. crea `idx_tiendas_ubicacion` (R-Tree) e `idx_productos_embedding` (IVF coseno).

Se puede correr varias veces, porque solo inserta lo que falta. Con
`--datos <carpeta>` carga otro dataset con la misma estructura. Con Docker:
`docker compose run --rm seed python -m tools.seed_tienda --api http://backend:8000 --reemplazar-modelo`.

Mientras llega el dataset final, el equipo trabajó con la muestra de
`examples/tienda/`: 30 productos en 6 categorías, con una imagen cada uno, 5
tiendas en Lima, 91 filas de stock y 200 compras de 38 usuarios. La genera
`examples/tienda/generar_muestra.py` con semilla fija.

## 4. Contrato de las fuentes

Toda fuente recibe el id de X y devuelve una lista `{producto_id, score}`
(`frontend/src/tienda/tipos.ts`):

- un score más alto significa más recomendado; si una consulta da distancias,
  se invierten antes de devolverlas;
- la escala la elige cada fuente, porque la fusión normaliza;
- la fusión quita a X aunque la fuente lo devuelva.

Las fuentes del backend añaden `fuente` y `evidencia` (por ejemplo, cuántos
compradores se usaron), que el frontend ignora.

Para agregar una fuente se escribe una función con ese contrato y se registra
en `frontend/src/tienda/fuentes.ts`. La ficha la muestra con su propio
control de peso y sin más cambios.

## 5. Fuentes

### 5.1 Descripción similar (Persona 2)

Usa la descripción de X como consulta BM25 sobre la columna `descripcion`.
Pide 11 resultados porque X suele salir primero:

```sql
SELECT id, SCORE() AS score FROM productos
WHERE MATCH(descripcion, '<descripción de X>') USING BM25
ORDER BY score DESC LIMIT 11;
```

El mismo `MATCH` sirve para el buscador del catálogo, combinado con filtros de
categoría, precio mínimo y máximo, y con orden por relevancia o precio.

### 5.2 Imagen similar (Persona 3)

Lee el embedding BoVW de X y busca los vecinos en el IVF con métrica coseno.
El score se lleva a [0, 1] con `(cos + 1) / 2`:

```sql
SELECT id, SIMILARITY_SCORE() AS score FROM productos
WHERE SIMILAR_TO([<vector de X>], k=11) USING IVF WITH METRIC=cosine
ORDER BY score DESC;
```

El vector se pasa como literal, porque el parser no admite subconsultas.
También se puede subir una foto: `/api/media/extract` la guarda y
`SIMILAR_TO('<archivo>', k=10)` devuelve los productos parecidos.

### 5.3 Comprados juntos (Persona 4)

El score de Y es la fracción de compradores de X que también compraron Y. Se
cuentan personas, no filas, para que una compra repetida no infle el score:

```text
score(Y) = compradores de X que compraron Y / compradores de X
```

Se resuelve con tres consultas (compradores de X, sus compras agrupadas por
usuario y producto, e historial del usuario) y la división en Python, porque
el motor no admite autouniones con alias. Si X no tiene compras, devuelve una
lista vacía.

### 5.4 Misma categoría y precio (Persona 4)

Toma los productos de la misma categoría y los puntúa por cercanía de precio:

```text
score(Y) = 1 / (1 + |precio_Y - precio_X| / max(precio_X, 1))
```

Con un "misma categoría sí o no" habría empates masivos. Esta fórmula da un
orden continuo dentro de la categoría.

### 5.5 Tiendas cercanas (Persona 4)

No entra en la fusión, porque no recomienda productos: dice dónde comprar X.
Cruza las tiendas que están dentro del radio (R-Tree con Haversine) con las
que tienen stock de X, y las pinta en un mapa Leaflet. El punto de referencia y
el radio se eligen en la ficha (15 km por defecto).

## 6. Fusión de scores

`frontend/src/tienda/fusion.ts` junta las fuentes en un solo top 10:

1. **Quitar a X** de cada lista.
2. **Normalizar cada fuente a [0, 1] con min-max**, porque BM25 no está
   acotado y las demás sí. Si un producto sale dos veces en una fuente, se
   queda su mejor score; se descartan los scores `NaN` o infinitos. Si todos
   los scores de una fuente son iguales, valen 1.
3. **Ponderar**: cada fuente aporta `score_normalizado * peso / suma de pesos
   activos`. Una fuente con peso 0 o negativo no participa y no cuenta en la
   suma. Así, el score fusionado queda en [0, 1] para cualquier combinación de
   pesos.
4. **Sumar por producto** y guardar el aporte de cada fuente, que la ficha
   muestra como una barra de colores.
5. **Ordenar** por score fusionado. En un empate gana el producto que viene de
   más fuentes, y después el id menor, para que el orden sea siempre el mismo.
6. **Cortar a 10**.

X se quita antes de normalizar porque, si siguiera en la lista, su score fijaría el
máximo y aplastaría los demás. Por ejemplo, en BM25 la propia descripción de
X saca el score más alto con diferencia.

Si una fuente falla, la ficha avisa de cuál falló ("Sin resultados de: ...") y
sigue con las demás. Una fuente vacía simplemente no aporta. Esto cumple el
criterio de cierre de la fusión: si una fuente falla o viene vacía, igual hay
recomendaciones.

Se eligió min-max frente a RRF (reciprocal rank fusion) porque conserva cuánto
mejor es un producto que otro dentro de una fuente, y no solo su posición. Con
RRF, una diferencia de precio de 1 % y una de 50 % pesarían igual si ocupan
posiciones vecinas.

## 7. Ficha de producto

`#tienda/producto/<id>` (`FichaProducto.tsx`) muestra:

- la imagen, el nombre, la categoría, el precio y la descripción de X;
- un control de peso por fuente, entre 0 y 3, que reordena al instante;
- los botones **Usar pesos aprendidos** y **Pesos iguales**, con la
  Precision@10 de cada opción;
- las 10 recomendaciones, cada una con su score y su barra de aportes por fuente;
- las tiendas cercanas con stock y el mapa.

Por defecto todas las fuentes pesan 1. Desde otra vista se enlaza a una ficha
con `enlaceProducto(id)` de `frontend/src/tienda/rutas.ts`.

## 8. Pesos aprendidos y evaluación

### 8.1 Método

`python -m tools.aprender_pesos` aprende los pesos con el historial de compras:

- **Relevancia.** Un caso es un producto X de una compra con 2 o más productos
  (mismo usuario y misma fecha). Los demás productos de esa compra son los
  relevantes para X.
- **Métrica.** Precision@10: cuántos de los 10 recomendados son relevantes,
  dividido entre 10, y promediado sobre los casos.
- **Búsqueda.** Pesos de 0 a 3 en pasos de 0.5 para cada una de las 4 fuentes,
  sin contar la combinación de todo ceros: 2400 combinaciones. Cada combinación
  se evalúa con la misma fusión de `fusion.ts`, portada a Python. Un test
  comprueba que las dos versiones dan el mismo resultado con los mismos casos.
  Si dos combinaciones empatan, gana la más cercana a pesos iguales.
- **Validación.** Validación cruzada de 5 pliegues por usuarios (semilla 2026).
  Los pesos se aprenden con los usuarios de 4 pliegues y se miden con los del
  quinto. Se separa por usuario, y no por compra, para que ningún usuario esté
  a la vez en entrenamiento y en prueba.
- **Sin fuga de datos.** Para medir un caso, la co-compra se calcula solo con
  los usuarios de entrenamiento y sin el usuario evaluado. Si no, la cesta que
  se quiere adivinar estaría dentro de los datos de la fuente.

Antes se probó otra relevancia: "todo lo que compró el usuario". Con ella, los
pesos aprendidos rendían igual o peor que los iguales, porque los usuarios de la
muestra hacen compras sin relación entre sí. Con "misma compra" la señal es
clara.

### 8.2 Resultados (muestra: 38 usuarios, 196 casos)

Precision@10 media de los 5 pliegues:

| Configuración | Precision@10 |
|---|---|
| Solo Misma categoría y precio | 0.0054 |
| Solo Descripción similar | 0.0393 |
| Solo Imagen similar | 0.0481 |
| Fusión con pesos iguales | 0.0560 |
| Solo Comprados juntos | 0.0692 |
| **Fusión con pesos aprendidos** | **0.0692** |
| Máximo posible | 0.1449 |

| Pliegue | Pesos iguales | Pesos aprendidos |
|---|---|---|
| 1 | 0.0720 | 0.0860 |
| 2 | 0.0563 | 0.0625 |
| 3 | 0.0449 | 0.0755 |
| 4 | 0.0419 | 0.0516 |
| 5 | 0.0647 | 0.0706 |

El máximo posible no es 1. Cada caso tiene en promedio 1.45 productos
relevantes, así que aunque los acierte todos, la mayoría de los 10 puestos no
pueden ser relevantes.

Los pesos aprendidos mejoran a los iguales en los 5 pliegues, un 24 % en
promedio. En los 5 pliegues se aprendió lo mismo: Comprados juntos con peso 1 y
las demás con peso 0. Con todos los datos, los pesos finales son también esos
(`frontend/src/tienda/pesosAprendidos.ts`).

### 8.3 Interpretación

Que gane solo la co-compra no significa que las otras fuentes estén mal. Esta
evaluación mide si el sistema adivina **qué más se compra junto con X**, y eso
premia lo complementario, no lo parecido. Para una laptop, lo que se compra en
la misma compra es una mochila o unos audífonos, no otra laptop. Las fuentes de
texto, imagen y metadatos recomiendan productos parecidos a X, que la gente
compra en lugar de X y no junto con él. Por eso metadatos, que solo devuelve la
misma categoría, queda casi en 0.

En la ficha se ve claro: para una laptop, con pesos iguales salen otras laptops
y, con los aprendidos, mochilas y audífonos. Por eso la ficha mantiene pesos
iguales por defecto y deja los aprendidos como opción. Cuál conviene depende de
si se quiere mostrar "productos parecidos" o "completa tu compra".

### 8.4 Limitaciones

- La muestra es pequeña (30 productos, 196 casos) y está generada con reglas
  de qué se compra con qué. Los números sirven para validar el método, no como
  resultado final. Con el dataset real basta con volver a correr
  `python -m tools.aprender_pesos`.
- La rejilla solo prueba pesos de 0 a 3 en pasos de 0.5. Como la fusión divide
  entre la suma de pesos, solo importan las proporciones, y la rejilla cubre
  las proporciones razonables.
- Precision@10 no mira la posición dentro del top 10. Un acierto en el puesto
  1 vale lo mismo que uno en el puesto 10.

## 9. Pruebas

| Qué se prueba | Dónde |
|---|---|
| Normalización, exclusión de X, pesos, desempates, fuentes que fallan, pesos aprendidos | `frontend/src/tienda/fusion.test.ts` |
| Fuentes por API (co-compra y metadatos) | `frontend/src/tienda/fuentesBackend.test.ts` |
| Rutas de la ficha | `frontend/src/tienda/rutas.test.ts` |
| Consultas del catálogo | `frontend/src/tienda/datos.test.ts` |
| Endpoints de co-compra y metadatos | `tests/test_recommend_api.py` |
| Aprendizaje de pesos: misma fusión que `fusion.ts`, sin fuga, de punta a punta con la muestra | `tests/test_aprender_pesos.py` |
| Carga de la tienda | `tests/test_seed_tienda.py` |
| Texto y catálogo | `tests/test_text_execution.py`, `tests/test_tienda_persona2.py` |
| Imagen | `tests/test_recommender_visual.py` |
| Co-compra, metadatos y tiendas | `tests/test_recommender_parte5.py` |

```powershell
python -m pytest -q
cd frontend
npm test
```

## 10. Pendiente

- Dataset final (2000 a 5000 productos, 20 a 50 tiendas, historial de compras)
  y su evaluación con la tabla y el gráfico en `benchmarks/results` (Persona 1).
  La carga y el aprendizaje de pesos ya funcionan con cualquier dataset que
  tenga las mismas columnas que la muestra.
