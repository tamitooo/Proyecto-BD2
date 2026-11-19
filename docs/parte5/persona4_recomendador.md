# Parte 5 — Fuentes del recomendador (Persona 4: issues i, j, k)

Este documento cubre **solo** las tres fuentes que le corresponden a la
Persona 4. La fusión de puntajes (issue l), el endpoint (d) y la página de
detalle (n) son de la Persona 5; la evaluación (o) y el dataset (a-c) de la
Persona 1.

| Issue | Qué entrega | Dónde |
|---|---|---|
| i | Co-compra "quienes compraron X también compraron Y" | `recommender/copurchase.py` |
| j | Metadatos: misma categoría, precio similar | `recommender/metadata.py` |
| k | Tiendas cercanas con stock (R-Tree) | `recommender/stores.py` |
| p | Pruebas de los tres | `tests/test_recommender_parte5.py` |

## 1. Contrato compartido

El motor **no infiere el esquema desde un CSV** y exige una clave primaria de
una sola columna (`storage/record.py:35-39`). El DDL de `recommender/schema.py`
es el contrato; úsalo tal cual:

```sql
CREATE TABLE productos (id INT, nombre VARCHAR(96), categoria VARCHAR(32), precio FLOAT,
                        descripcion VARCHAR(1024), imagen VARCHAR(160), embedding VARCHAR(2048));
CREATE TABLE tiendas   (id INT, nombre VARCHAR(64), lat FLOAT, lon FLOAT, distrito VARCHAR(32));
CREATE TABLE stock     (id INT, tienda_id INT, producto_id INT, cantidad INT);
CREATE TABLE compras   (id INT, usuario_id INT, producto_id INT, fecha VARCHAR(10), cantidad INT);
```

`productos` respeta el orden de `tools/seed_tienda.py` (`id, nombre,
categoria, precio, descripcion, imagen, embedding`): ese cargador usa
`INSERT ... VALUES` sin lista de columnas, así que invertir categoría y precio
intercambia los datos en silencio.

Reglas de datos que las fuentes asumen:

1. **`compras` puede repetir `(usuario_id, producto_id)`.** La muestra real
   tiene 13 pares repetidos. Como el motor no tiene `COUNT(DISTINCT)`
   (`query/sql_parser.py:474`), `i` agrupa por `(usuario_id, producto_id)`
   para que cada comprador cuente una vez; aun así, el generador debería
   emitir un par por persona.
2. **`fecha` es `VARCHAR(10)` (`YYYY-MM-DD`)**, como en
   `examples/tienda/compras.csv`; el motor solo tiene `INT`, `FLOAT` y
   `VARCHAR(n)` (`storage/record.py:11-27`).
3. **`stock` cubre la mayoría de los productos** y usa `id` surrogate.
4. **`categoria` con al menos 10 productos por valor**: con categorías de un
   producto, `j` no tiene nada que ordenar.

Formato de salida de cada fuente (el que consume la fusión):

```json
{"producto_id": 2, "score": 0.5, "fuente": "co_compra",
 "evidencia": {"co": 3, "compradores_usados": 6, "compradores_totales": 6}}
```

`score` es mayor-is-better, está en `(0, 1]`, nunca incluye el producto de
consulta, y el orden es `score DESC, producto_id ASC` (desempate determinista).

## 2. Issue i — co-compra

### Por qué no es un JOIN

El plan original decía "JOIN de compras + GROUP BY". Con el motor actual no se
puede:

- el parser **no admite alias** (`JOIN compras c1` → *Unsupported text after
  FROM*), así que no hay autounión de `compras`
  (`query/sql_parser.py:279-293`);
- el `WHERE` se aplica **antes** del join
  (`query/query_executor.py:119-131`), así que `WHERE c1.producto_id = X` no
  distingue lados;
- `GROUP BY` se valida contra la tabla base, no contra el join
  (`query/query_executor.py:133-138`, `:235`);
- no hay `IN (...)` ni subconsultas (`query/sql_parser.py:474`).

La fuente se resuelve con tres consultas y la agregación en Python:

```sql
-- 1) compradores de X
SELECT usuario_id FROM compras WHERE producto_id = 1;

-- 2) sus pares (comprador, producto), para contar personas y no compras
SELECT usuario_id, producto_id, COUNT(*) AS compras FROM compras
WHERE usuario_id = 1 OR usuario_id = 2 OR usuario_id = 3
GROUP BY usuario_id, producto_id;

-- 3) historial del usuario actual, para excluir lo que ya compró
SELECT producto_id FROM compras WHERE usuario_id = 1;
```

Puntaje: `co / compradores_usados`, es decir, la fracción de compradores de X
que también compraron Y. `co` cuenta personas (pares únicos), no filas: la
muestra real repite 13 pares y el puntaje no se infla. En el fixture:
`i(1) = [(2, 0.5), (3, 0.5), (4, 0.333)]`.

### Límites

- La lista `OR` crece con los compradores de X. `max_buyers=300` por defecto;
  al recortar, el puntaje queda sesgado hacia los compradores considerados y
  la evidencia lo declara (`compradores_usados` vs `compradores_totales`).
- La consulta 2 no lleva `ORDER BY` ni `LIMIT`: el orden y el corte se hacen
  en Python para que el desempate sea determinista.
- Si X no tiene compras, devuelve `[]` (cold start: la fusión decide el
  fallback).

**Trade-off pendiente:** con más de ~100 000 compras conviene materializar
`pares(producto_a, producto_b, co)` en la carga y responder con un `SELECT`
por igualdad. Cuesta almacenamiento y complejidad del cargador; hoy no hace
falta.

## 3. Issue j — metadatos (categoría + precio)

Una consulta y el puntaje en Python:

```sql
SELECT id, precio FROM productos
WHERE categoria = 'Laptops' AND id <> 1;
```

```
score = 1 / (1 + |precio - precio_X| / max(precio_X, 1))
```

Un "misma categoría" binario produce empates masivos; con esta fórmula el
orden dentro de la categoría es por cercanía de precio y el puntaje es
continuo, que es lo que la fusión necesita. En la muestra:
`j(1) = [(6, 0.980), (2, 0.962), (7, 0.831), (3, 0.806), (4, 0.781), (5, 0.595)]`.

La categoría viaja dentro del SQL: `recommender/sql.py:literal()` duplica las
comillas simples y hay una prueba con la categoría `O'Brien`.

## 4. Issue k — tiendas cercanas con stock

Dos consultas y una intersección en Python:

```sql
-- 1) tiendas en el radio (usa el R-Tree si existe; si no, filtro lineal)
SELECT id, nombre, lat, lon, distrito FROM tiendas
WHERE distancia(lat, POINT(-12.0464, -77.0428), HAVERSINE) < 3000.0;

-- 2) stock del producto
SELECT tienda_id, cantidad FROM stock WHERE producto_id = 1 AND cantidad > 0;
```

La intersección se hace en Python porque el motor no puede filtrar por una
columna del lado derecho del join. Con 20-50 tiendas el costo es despreciable.

Devuelve `NearbyStore` ordenado por distancia, con `distancia_m`,
`cantidad` y `distrito`. La vista está en:

- **API:** `GET /api/recommend/stores/{producto_id}?lat=&lon=&radius_m=15000`
  (`backend/api.py`), que devuelve `{producto_id, centro, radio_m, tiendas}`.
- **UI:** `frontend/src/tienda/TiendasCercanas.tsx`, dentro de la ficha. Deja
  elegir el punto de referencia (Centro de Lima, Miraflores, San Isidro, Surco,
  La Molina, Los Olivos), el radio (por defecto 15 km) y pinta el usuario y las
  tiendas en Leaflet (`window.L`, cargado por CDN en `index.html`).

El radio por defecto es 15 km porque las tiendas reales de
`examples/tienda/tiendas.csv` están a 5.7–12.4 km del centro de Lima; con 3 km
la lista sale vacía para casi cualquier producto.

`availability_score()` queda disponible si la fusión decide usar
disponibilidad como señal, pero **no** rankea productos: premia densidad
comercial, no preferencia.

**Cuidado con `OR` + distancia:** `id = 1 OR id = 3 AND distancia(...) < 5000`
no aplica el radio a la primera rama, y el parser no acepta paréntesis
(`query/sql_parser.py:424`). Por eso esta fuente no arma listas `OR`.

## 5. Cómo ejecutarlo

```powershell
# Muestra determinista en el data_dir del API (20 productos, 5 tiendas, 20 compras)
python -m tools.seed_parte5_sample
python -m tools.seed_parte5_sample --data-dir backend/data --replace

# Pruebas de i, j, k
python -m pytest tests/test_recommender_parte5.py -q
```

La muestra de `recommender/fixture.py` **no es el dataset del proyecto**: es
un fixture con estructura conocida para probar sin esperar la carga completa.
El dataset real lo genera la Persona 1.

## 6. Decisiones que quedan para el grupo

1. **`k` en la fusión o no.** El acuerdo dice que fusionan `e, h, i, j`; `k` es
   contexto. Si entra, su peso por defecto debería ser 0 y justificarse.
2. **Candidatos por fuente.** Cada fuente devuelve `k=10` por defecto; para
   fusionar conviene pedir 50 por fuente y cortar a 10 después. El contrato ya
   lo permite (`k` es parámetro).
3. **Normalización.** `i` y `j` devuelven `(0, 1]`; BM25 no está acotado y el
   coseno sí. Min-max por consulta o RRF: decisión de la Persona 5 (issue l).
4. **Cold start.** `i` devuelve `[]` si el producto no tiene compras; definir
   si la fusión cae a `j` o a popularidad.

## 7. Limitaciones declaradas (para el informe)

- La co-compra se calcula sobre la muestra de compradores considerados
  (`max_buyers`), no sobre todos, cuando el producto es muy popular.
- El puntaje de metadatos mide cercanía de precio dentro de la categoría; no
  mide calidad ni disponibilidad.
- La disponibilidad se evalúa contra un punto fijo (el usuario o el centro de
  la demo), no contra la ubicación real de cada visitante.
- El motor no ejecuta la agregación de la co-compra en un solo JOIN: la
  aplicación compone tres consultas. Es una decisión de diseño para no tocar
  el parser en la semana de entrega, y está declarada aquí.
