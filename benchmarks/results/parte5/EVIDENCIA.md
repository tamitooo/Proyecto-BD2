# Evidencia de ejecución del dataset final (Parte 5)

Corrida del 2026-11-20 con Python 3.14.4 y OpenCV 5.0.0. Resultado: `examples/tienda_abo/`.

## 1. De dónde salen los productos

[Amazon Berkeley Objects (ABO)](https://amazon-berkeley-objects.s3.amazonaws.com/index.html):
catálogo público de Amazon con fichas reales (nombre, viñetas, tipo de producto) y fotos, con
licencia CC BY 4.0. Se descarga de su bucket público de S3, sin cuenta.

| Paso | Cantidad |
|---|---|
| Fichas en la metadata de ABO (16 archivos `listings_*.json.gz`, 84 MB) | 147 702 |
| De las 8 categorías elegidas (tipos CHAIR, TABLE, SOFA, PILLOW, RUG, LAMP, LIGHT_FIXTURE, SHOES, FINERING, FINENECKLACEBRACELETANKLET, FINEEARRING) | 23 434 |
| Con nombre y viñetas en español | 4 791 |
| Elegidas: sin muestras de tela, reacondicionados ni variantes; hasta 450 por categoría | 2 576 |
| Descartadas al procesar la foto (sin imagen, foto lisa o menos de 8 descriptores SIFT) | 45 |
| **Productos finales** | **2 531** |

Fotos: solo las elegidas, en la versión de 256 px (`images/small/`, 22 MB), no el paquete
completo de 3 GB.

```
python -m tools.preparar_abo --raw data/abo_raw --salida data/tienda_abo --por-categoria 450
{
  "productos": 2531,
  "por_categoria": {"alfombras": 191, "calzado": 436, "cojines": 121, "joyas": 432,
                    "lamparas": 436, "mesas": 277, "sillas": 450, "sofas": 188},
  "descartados": 45,
  "vocabulario": "64 palabras (opencv)"
}
```

Cada producto se puede rastrear: `examples/tienda_abo/origen.csv` guarda su `abo_item_id` (el
ASIN de Amazon) y su `abo_image_id`. Por ejemplo, el producto 1 es el ASIN `B07B4SDTFT`.

## 2. Lo que se generó (ABO no lo trae)

Precios (rango por categoría, semilla 2026), tiendas, stock y compras:

```
python -m tools.generate_part5_data --products data/tienda_abo/productos.csv --output examples/tienda_abo \
  --images data/tienda_abo/imagenes --stores 30 --users 2500 --purchases 10000 --seed 2026
```

`manifest.json`: 2 531 productos, 30 tiendas, 6 432 filas de stock, 10 000 compras de 2 500
usuarios en 5 354 canastas. El 44 % de los pares comprados juntos se repite en otra canasta y el
86 % de los productos tiene al menos una venta.

## 3. Carga en el motor (por la API)

```
python -m tools.seed_tienda --datos examples/tienda_abo --data-dir <BD2_DATA_DIR>
tiendas: 30 filas
stock: 6432 filas
compras: 10000 filas
productos: 2531 insertados, 0 ya estaban
idx_tiendas_ubicacion: creado
idx_productos_embedding: creado
tienda lista
```

Tardó 9 min 25 s (16:21:52 a 16:31:17), sobre todo por `EXTRACT_FEATURES` de cada foto.

## 4. Comprobaciones sobre el motor cargado

- Búsqueda por imagen (`SIMILAR_TO([...], k=11) USING IVF WITH METRIC=cosine`, 150 productos al
  azar, semilla 2026): el 46.7 % del top 10 es de la misma categoría; al azar sería 14.5 %.
  Mediana de 9.7 ms por consulta.
- `MATCH(nombre, 'Ravenna Home Jessica') USING BM25` devuelve primero la mesa auxiliar (id 1680).

## 5. Aprendizaje de pesos (17:53 a 18:35)

```
python -m tools.aprender_pesos
pliegue 1: iguales 0.0536  aprendidos 0.0777
pliegue 2: iguales 0.0543  aprendidos 0.0820
pliegue 3: iguales 0.0556  aprendidos 0.0769
pliegue 4: iguales 0.0548  aprendidos 0.0818
pliegue 5: iguales 0.0566  aprendidos 0.0820
Precision@10 media (2500 usuarios, 8537 casos): iguales 0.0550 -> aprendidos 0.0801
  Imagen similar               0.0007
  Descripción similar          0.0005
  Comprados juntos             0.0801
  Misma categoría y precio     0.0010
  máximo posible               0.1266
pesos finales: {'visual': 0.0, 'texto': 0.0, 'cocompra': 1.0, 'metadatos': 0.0}
```

Los detalles por pliegue están en `precision_fuentes.json`.
