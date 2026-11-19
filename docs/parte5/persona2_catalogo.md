# Parte 5 — Persona 2: búsqueda textual y catálogo

## Responsabilidades

La Persona 2 implementa:

- recomendación de productos por similitud textual de la descripción;
- búsqueda de productos mediante `MATCH`;
- filtros de categoría y precio;
- catálogo visual de productos.

## Recomendación por descripción

Dado un producto `X`, se obtiene su descripción y se utiliza como consulta sobre la columna `descripcion` de la tabla `productos`.

La búsqueda utiliza el índice textual del motor y ranking BM25:

```sql
SELECT id, SCORE() AS score
FROM productos
WHERE MATCH(descripcion, 'descripcion del producto X')
USING BM25
ORDER BY score DESC
LIMIT 11;
```

Se solicitan hasta 11 resultados porque el propio producto `X` puede aparecer entre los documentos más relevantes al utilizar su propia descripción como consulta.

Después de ejecutar la búsqueda, el producto origen se elimina explícitamente y se conservan como máximo las 10 mejores recomendaciones.

El formato utilizado por el sistema de recomendación es:

```text
{ producto_id, score }
```

donde:

- `producto_id` identifica el producto recomendado;
- `score` corresponde al score BM25;
- un score mayor representa una mayor relevancia textual;
- el producto `X` nunca debe aparecer dentro de sus propias recomendaciones.

La implementación de esta fuente se encuentra en:

```text
frontend/src/tienda/fuenteTexto.ts
```

y se registra como una fuente del recomendador en:

```text
frontend/src/tienda/fuentes.ts
```

De esta manera, los resultados de BM25 pueden participar posteriormente en la fusión de scores junto con las demás fuentes de recomendación.

## Búsqueda de productos

El catálogo permite realizar búsquedas textuales sobre la descripción de los productos utilizando `MATCH`.

Por ejemplo:

```sql
SELECT id, nombre, categoria, precio, imagen, SCORE() AS score
FROM productos
WHERE MATCH(descripcion, 'laptop gaming')
USING BM25
ORDER BY score DESC;
```

Cuando existe un término de búsqueda, los resultados se ordenan por relevancia BM25 de mayor a menor.

El frontend genera estas consultas mediante la función:

```text
construirConsultaProductos()
```

ubicada en:

```text
frontend/src/tienda/datos.ts
```

## Filtros por categoría y precio

La búsqueda textual puede combinarse con predicados relacionales adicionales.

Ejemplo:

```sql
SELECT id, nombre, categoria, precio, imagen, SCORE() AS score
FROM productos
WHERE MATCH(descripcion, 'laptop gaming')
  AND categoria = 'laptops'
  AND precio >= 2000
  AND precio <= 5000
USING BM25
ORDER BY score DESC;
```

Esto permite utilizar simultáneamente:

- texto de búsqueda;
- categoría;
- precio mínimo;
- precio máximo.

Los filtros también pueden utilizarse sin una búsqueda textual.

Por ejemplo:

```sql
SELECT id, nombre, categoria, precio, imagen
FROM productos
WHERE categoria = 'laptops'
  AND precio >= 2000
  AND precio <= 5000
ORDER BY id;
```

## Ordenamiento

El catálogo permite ordenar los productos utilizando tres criterios:

### Relevancia

Cuando existe texto de búsqueda:

```sql
ORDER BY score DESC
```

Esto utiliza el score generado por BM25.

### Precio ascendente

```sql
ORDER BY precio ASC
```

Permite mostrar primero los productos de menor precio.

### Precio descendente

```sql
ORDER BY precio DESC
```

Permite mostrar primero los productos de mayor precio.

## Seguridad al construir consultas

Los valores textuales utilizados en las consultas SQL se escapan antes de incorporarse a la sentencia.

Por ejemplo, una búsqueda que contenga:

```text
d'alta
```

se convierte en:

```sql
'd''alta'
```

evitando romper la sintaxis SQL generada.

Esta lógica se encuentra centralizada en `frontend/src/tienda/datos.ts`.

## Catálogo de productos

La vista `Tienda` incorpora un catálogo visual en forma de grid.

Cada producto muestra:

- imagen;
- nombre;
- categoría;
- precio.

El componente principal del catálogo se encuentra en:

```text
frontend/src/tienda/CatalogoProductos.tsx
```

mientras que la lógica general de la tienda se encuentra en:

```text
frontend/src/tienda/Tienda.tsx
```

Cada tarjeta del catálogo permite abrir el detalle del producto correspondiente.

La navegación utiliza el formato:

```text
#tienda/producto/<id>
```

Por ejemplo:

```text
#tienda/producto/12
```

## Controles del catálogo

La interfaz permite modificar dinámicamente:

- texto de búsqueda;
- categoría;
- precio mínimo;
- precio máximo;
- criterio de ordenamiento.

Además, incluye:

- contador de productos encontrados;
- indicador de búsqueda en progreso;
- botón para limpiar todos los filtros;
- mensaje cuando no existen productos que cumplan los filtros;
- acceso directo al detalle de cada producto.

Cuando no existen filtros activos, el catálogo muestra nuevamente todos los productos disponibles.

## Flujo de búsqueda

El flujo general de búsqueda es:

```text
Usuario
   ↓
Texto + categoría + precios + orden
   ↓
Tienda.tsx
   ↓
buscarProductos()
   ↓
construirConsultaProductos()
   ↓
SQL
   ↓
MATCH + BM25 + filtros relacionales
   ↓
QueryExecutor
   ↓
SPIMI / BM25
   ↓
Resultados
   ↓
Grid de productos
```

## Flujo de recomendación textual

La recomendación por descripción sigue el siguiente flujo:

```text
Producto X
   ↓
obtener descripción
   ↓
MATCH(descripcion, descripción de X)
   ↓
BM25
   ↓
ORDER BY score DESC
   ↓
eliminar producto X
   ↓
Top 10
   ↓
{ producto_id, score }
   ↓
fusión con otras fuentes
```

## Datos de prueba

El proyecto incluye un conjunto de datos de muestra para desarrollar y demostrar la Parte 5.

Puede cargarse mediante:

```powershell
python -m tools.seed_tienda
```

La muestra incluye:

- productos;
- imágenes;
- categorías;
- tiendas;
- stock;
- historial de compras.

Estos datos permiten probar el catálogo y las recomendaciones sin depender todavía del dataset completo de la entrega final.

## Pruebas

### Tests del motor textual

Se valida que `MATCH` pueda combinarse correctamente con filtros relacionales:

```powershell
python -m pytest tests/test_text_execution.py -q
```

Entre los casos cubiertos se encuentran:

- BM25;
- `MATCH` con categoría;
- `MATCH` con rango de precios;
- orden por relevancia;
- orden por precio.

### Tests de integración de Persona 2

La integración del catálogo y la recomendación textual se valida mediante:

```powershell
python -m pytest tests/test_tienda_persona2.py -q
```

Estos tests verifican:

- búsqueda textual con BM25;
- filtro simultáneo por categoría y precio;
- ordenamiento;
- exclusión del producto origen;
- formato `{ producto_id, score }`.

### Tests del frontend

Desde la carpeta `frontend`:

```powershell
npm test
```

Los tests cubren, entre otros aspectos, la construcción de las consultas SQL del catálogo.

También debe verificarse la compilación:

```powershell
npm run build
```

## Archivos principales

La implementación de Persona 2 se distribuye principalmente entre:

```text
frontend/src/tienda/Tienda.tsx
frontend/src/tienda/CatalogoProductos.tsx
frontend/src/tienda/datos.ts
frontend/src/tienda/fuenteTexto.ts
frontend/src/tienda/fuentes.ts
frontend/src/tienda/datos.test.ts
frontend/src/tienda/fuenteTexto.test.ts
tests/test_text_execution.py
tests/test_tienda_persona2.py
```

## Cumplimiento de requisitos

### e. Recomendación por descripción

Cumplido mediante:

- obtención de la descripción del producto X;
- búsqueda `MATCH`;
- ranking BM25;
- exclusión de X;
- salida `{producto_id, score}`;
- top 10 de recomendaciones.

### f. Búsqueda de productos

Cumplido mediante:

- búsqueda textual con `MATCH`;
- ranking BM25;
- filtro de categoría;
- precio mínimo;
- precio máximo;
- orden por relevancia;
- orden por precio.

### m. Catálogo de productos

Cumplido mediante:

- grid visual;
- imágenes;
- nombre;
- categoría;
- precio;
- búsqueda;
- filtros;
- ordenamiento;
- navegación al detalle del producto.

### p. Tests

Se incluyen pruebas unitarias y de integración correspondientes a las funcionalidades desarrolladas por Persona 2.

### q. README / informe

La presente documentación describe la implementación, arquitectura, consultas SQL y pruebas correspondientes a Persona 2.
