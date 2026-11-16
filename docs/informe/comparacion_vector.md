# Comparacion de indices vectoriales: IVF contra HNSW (Parte 4)

Dos corridas, misma metodologia: k = 10, 100 consultas por tamano, Recall@10
contra fuerza bruta y memoria con `deep_size()`.

- **Corpus multimedia** (la de la rubrica 2.4.4): vectores SIFT/MFCC del dataset
  de `data/multimedia/<n>/`, 32 dimensiones, `fuente=corpus-image`.
- **Sintetica** (referencia historica): ocho grupos gaussianos de 32
  dimensiones, `fuente=sintetico`.

Reproducir:

```powershell
python -m benchmarks.multimedia_corpus --sizes 1000 10000 100000 --reanudar
python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 1000 10000 100000 --corpus data/multimedia --modalidad image --metricas euclidean cosine
python -m benchmarks.generate_vector_charts --csv ivf_hnsw_corpus_image.csv --prefijo vector_corpus --metricas euclidean cosine
```

## Corpus multimedia: imagenes

| n | Indice | Metrica | Construccion | Consulta | Recall@10 | Memoria |
|---|---|---|---|---|---|---|
| 1 000 | IVF | euclidiana | 0.17 s | 0.57 ms | 0.996 | 1.15 MB |
| 1 000 | HNSW | euclidiana | 4.84 s | 5.02 ms | 0.982 | 2.26 MB |
| 1 000 | IVF | coseno | 0.56 s | 3.32 ms | 0.997 | 1.15 MB |
| 1 000 | HNSW | coseno | 7.15 s | 4.74 ms | 0.982 | 2.26 MB |
| 10 000 | IVF | euclidiana | 13.38 s | 2.52 ms | 0.994 | 11.19 MB |
| 10 000 | HNSW | euclidiana | 97.29 s | 5.81 ms | 0.970 | 22.42 MB |
| 10 000 | IVF | coseno | 14.91 s | 18.26 ms | 0.998 | 11.19 MB |
| 10 000 | HNSW | coseno | 89.27 s | 6.31 ms | 0.970 | 22.42 MB |
| 100 000 | IVF | euclidiana | 343.88 s | 27.42 ms | 0.998 | 113.75 MB |
| 100 000 | HNSW | euclidiana | 1 323.01 s | 7.53 ms | 0.946 | 225.10 MB |
| 100 000 | IVF | coseno | 392.41 s | 154.77 ms | 0.999 | 113.77 MB |
| 100 000 | HNSW | coseno | 1 413.02 s | 9.14 ms | 0.946 | 225.10 MB |

### Construccion y memoria

IVF construye entre 3.8 y 29 veces mas rapido y ocupa **exactamente la mitad**
(2.26 / 22.42 / 225.10 MB frente a 1.15 / 11.19 / 113.75 MB). La ventaja de
construccion se estrecha con el tamano: 29x a 1 000, 7.3x a 10 000 y 3.8x a
100 000, porque el costo de IVF tambien es lineal en n (su `n_lists` crece con
la raiz del corpus) y lo que se amortiza es solo el factor constante del grafo.

### Recall

IVF no baja de 0.994 en ninguna de las seis celdas y llega a 0.999 con coseno a
100 000. HNSW se queda en 0.946-0.982 con `M=16`, `ef_construction=100` y
`ef_search=50` fijos, y **pierde recall al crecer** (0.982 a 1 000, 0.970 a
10 000, 0.946 a 100 000). La causa es asimetrica: en IVF `n_probe` crece con el
corpus (6, 10 y 18 listas), asi que revisa mas candidatos; en HNSW `ef_search`
esta fijo, y un grafo mas grande con los mismos parametros deja vecinos utiles
fuera de la lista de candidatos. El recall de HNSW sale identico con las dos
metricas, y por eso en `plots/vector_corpus_recall.png` sus dos series se
superponen.

### Latencia

La consulta de IVF crece con el tamano (0.57 ms a 27.42 ms en euclidiana, un
factor de 48 al multiplicar por 100 los objetos), porque revisa `n_probe` listas
cuyas longitudes crecen con el corpus. La de HNSW crece con el logaritmo
(5.02 ms a 7.53 ms, factor 1.5). El cruce en euclidiana ocurre entre 10 000 y
100 000; en coseno, entre 1 000 y 10 000.

El salto del coseno en IVF (18.26 ms a 10 000 y 154.77 ms a 100 000, frente a
2.52 y 27.42 en euclidiana) **es de implementacion, no asintotico**: el producto
punto recorre listas de Python con mas trabajo por par que la distancia
euclidiana, que descarta antes. Con numpy en el bucle interno la brecha se
cerraria sin cambiar la forma de la curva. Se declara como costo del prototipo.

## Contraste con la corrida sintetica

| n = 100 000, euclidiana | Sintetica | Corpus |
|---|---|---|
| IVF: recall | 0.907 | 0.998 |
| HNSW: recall | 0.749 | 0.946 |
| IVF: consulta | 15.81 ms | 27.42 ms |
| HNSW: consulta | 10.48 ms | 7.53 ms |

La conclusion sobre latencia se reproduce (HNSW gana a 100 000), pero la de
recall **no**: en el corpus ambos indices retienen mucho mas recall, y HNSW no
se despeña a 0.749. La razon es como se generan los dos conjuntos: la corrida
sintetica usa ocho grupos gaussianos con desvio 0.15 en 32 dimensiones, o sea
grupos que se solapan mucho en todas las direcciones; los vectores del corpus
son histogramas TF-IDF concentrados en pocas de las 32 palabras visuales, asi
que las listas del IVF quedan mas puras y el grafo de HNSW encuentra vecinos
mas rapido. **Conclusion metodologica: el balance IVF/HNSW depende del dataset,
y la tabla que vale para el informe es la del corpus, no la sintetica.**

## Audio

| n | Indice | Metrica | Construccion | Consulta | Recall@10 | Memoria |
|---|---|---|---|---|---|---|
| 1 000 | IVF | euclidiana | 0.24 s | 0.40 ms | 1.000 | 1.15 MB |
| 1 000 | HNSW | euclidiana | 5.08 s | 2.20 ms | 0.791 | 2.26 MB |
| 1 000 | IVF | coseno | 0.54 s | 3.38 ms | 1.000 | 1.15 MB |
| 1 000 | HNSW | coseno | 5.42 s | 2.21 ms | 0.791 | 2.26 MB |
| 10 000 | IVF | euclidiana | 9.81 s | 1.77 ms | 1.000 | 11.18 MB |
| 10 000 | HNSW | euclidiana | 62.38 s | 1.88 ms | 0.280 | 22.23 MB |
| 10 000 | IVF | coseno | 12.75 s | 28.29 ms | 1.000 | 11.18 MB |
| 10 000 | HNSW | coseno | 64.68 s | 2.50 ms | 0.280 | 22.23 MB |

**Estas cifras de recall no miden calidad del indice.** Medido sobre el corpus
de 10 000 audios: contra una consulta hay **60 vectores con similitud
exactamente 1.000000** y el top-50 tiene **un solo valor de similitud
distinto**. Son duplicados: la cuantizacion BoVW colapsa senales distintas al
mismo histograma de 32 palabras, asi que el «top-10 verdadero» no es unico.

- IVF recorre `n_probe` listas en el mismo orden que la fuerza bruta, devuelve
  el mismo subconjunto arbitrario y por eso marca 1.000.
- HNSW rompe los empates de otra forma, devuelve otros 10 de los 60 empatados y
  marca 0.280.

Con imagen el mismo chequeo da 1 empate y 50 valores distintos en el top-50, o
sea que la geometria si esta bien definida y el recall es interpretable. A
100 000 el audio no se corrio por la misma razon: la metrica se satura antes de
decir algo. Arreglarlo pide un descriptor de audio con mas resolucion (mas
palabras auditivas, o MFCC por segmento en vez de por clip completo); queda como
limitacion declarada del corpus, no del indice.

## Tabla comparativa con recomendaciones

Todo lo que sigue sale de la tabla de imagenes de arriba, no de literatura
general.

| | IVF | HNSW |
|---|---|---|
| **Ventajas medidas** | Construccion 3.8-29x mas rapida; mitad de memoria (113.75 MB contra 225.10 MB a 100 000); recall 0.994-0.999 en las seis celdas, sin degradarse con el tamano | Consulta casi constante: 5.02 -> 7.53 ms al multiplicar por 100 los objetos, contra 0.57 -> 27.42 ms de IVF; gana en latencia desde 100 000 (7.53 contra 27.42 ms) |
| **Desventajas medidas** | La consulta crece con el corpus: 48x al pasar de 1 000 a 100 000 objetos | Construccion 3.8-29x mas cara; el doble de memoria; pierde recall al crecer con `ef_search` fijo (0.982 -> 0.970 -> 0.946) |
| **Recomendacion** | **Por defecto**, y obligatorio cuando el recall es requisito duro o la memoria esta acotada. Ajustar `n_probe` al corpus | Solo si la latencia a 100 000+ es el cuello de botella y se acepta 0.946 de recall; subir `ef_search` para recuperarlo, pagando latencia |
| **Cuando no usarlo** | Cuando la consulta debe estar por debajo de ~10 ms con 100 000 objetos y recall 0.95 basta | Hasta 10 000 objetos: IVF gana en construccion, memoria y latencia (euclidiana). Con audio: el recall de HNSW no es interpretable (ver seccion Audio) |
| **Alternativa** | - | Fuerza bruta por debajo de 1 000 objetos: sin construccion y recall exacto |
