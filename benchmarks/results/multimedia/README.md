# Dataset sintetico de imagenes y audio (Parte 4, issue #92)

Generado con `python -m benchmarks.multimedia_corpus --sizes 1000 10000 100000`.
Los archivos viven en `data/multimedia/<n>/`, que no se versiona: se regeneran con
la misma semilla (`2026`). Lo que si se versiona son los resumenes
`extraccion_1000.json`, `extraccion_10000.json` y `extraccion_100000.json`, un
JSON por tamano con volumen, tiempos y calidad del espacio vectorial.

Cada tamano tiene su propio directorio (`data/multimedia/1000`, `/10000`,
`/100000`) con `images/`, `audio/`, `vectors.jsonl`, `pipeline.npz` y
`extraccion.csv` (una fila por objeto con sus milisegundos).

## Volumen

| Tamano | Imagenes | Audios | Disco | Vectores exportados |
|---|---|---|---|---|
| 1 000 | 1 000 | 1 000 | 48.4 MB | 2 000 |
| 10 000 | 10 000 | 10 000 | 484.3 MB | 20 000 |
| 100 000 | 100 000 | 100 000 | 4 842.6 MB | 200 000 |

| Modalidad | Familias | Formato |
|---|---|---|
| Imagen | 8 | PNG de 160 x 160 en escala de grises |
| Audio | 6 | WAV mono, 22 050 Hz, 16 bits, 1 segundo |

Dimension del vector: 32 en ambas modalidades (histograma de palabras visuales o
auditivas, ponderado por TF-IDF). Cero vectores nulos en los tres tamanos.

## Tiempos medidos

Host de la corrida: Windows, Python 3.13, un nucleo por proceso. El
entrenamiento del modelo (vocabulario K-Means + IDF) usa una muestra de 2 000
objetos por modalidad; la extraccion recorre el corpus completo.

| Tamano | Entrenamiento | Extraccion | Imagen p50 / p95 | Audio p50 / p95 |
|---|---|---|---|---|
| 1 000 | 108.7 s | 16.9 s | 9.1 / 23.8 ms | 5.2 / 7.1 ms |
| 10 000 | 181.3 s | 262.4 s | 10.2 / 25.5 ms | 14.2 / 19.6 ms |
| 100 000 | 188.1 s | 3 589.6 s | 18.5 / 34.4 ms | 14.2 / 20.0 ms |

Generacion de archivos: 75.1 s para los 20 000 archivos del tamano 10 000. A
100 000 no se cronometro en esta corrida: los archivos se produjeron en una
pasada anterior y la corrida definitiva los reutilizo con `--reanudar`
(`archivos_escritos: 0`). Es la etapa dominada por E/S, no por CPU.

El crecimiento de la extraccion por objeto con el tamano (9.1 -> 18.5 ms en
imagen) es efecto de la cache de disco: a 100 000 objetos los PNG ya no caben en
la cache del sistema. El costo por objeto del audio no varia.

## Calidad del espacio vectorial

Cada modalidad se evalua contra su propio espacio: los codebooks visual y
auditivo son independientes, asi que un coseno entre una imagen y un audio no
tiene interpretacion y no se reporta. Se muestrean 20 000 pares para el coseno y
200 consultas para Precision@10; con 8 familias de imagen y 6 de audio, el azar
da 0.125 y 0.167 respectivamente.

| Tamano | Imagen: coseno misma / distinta | Imagen: P@10 | Audio: coseno misma / distinta | Audio: P@10 |
|---|---|---|---|---|
| 1 000 | 0.7846 / 0.1927 | 0.8615 | 0.4934 / 0.0286 | 0.953 |
| 10 000 | 0.7837 / 0.1847 | 0.9075 | 0.4912 / 0.0169 | 1.000 |
| 100 000 | 0.7831 / 0.1838 | 0.9265 | 0.5085 / 0.0182 | 1.000 |

Lectura: el coseno intra/inter familia es estable con el tamano (0.783 / 0.184),
o sea que el espacio vectorial no se degrada al crecer el corpus. Precision@10
sube con el tamano, pero **eso no es una mejora del metodo**: con mas objetos por
familia hay mas vecinos correctos disponibles y la tarea se vuelve mas facil por
construccion. No es comparable entre tamanos.

## Limitaciones que hay que declarar

- **Corpus sintetico.** La familia se usa como etiqueta de relevancia; la
  relevancia esta definida por construccion, no por juicio humano.
- **Audio saturado por duplicados.** Las seis familias de audio son casi
  separables (tono bajo, tono alto, barrido, ruido, cuadrada, dos tonos) y la
  cuantizacion colapsa senales distintas al mismo histograma: en el corpus de
  10 000 hay **60 vectores con similitud exactamente 1.000000** contra una misma
  consulta, y el top-50 tiene un solo valor de similitud distinto. Por eso P@10
  marca 1.000 y el Recall@10 de los indices mide desempates, no calidad
  (`docs/informe/comparacion_vector.md`, seccion Audio). Se arregla con un
  descriptor de mayor resolucion (mas palabras auditivas o MFCC por segmento).
- **Vocabulario e IDF por muestra.** Se entrenan con 2 000 objetos por
  modalidad, no con el corpus completo: `fit()` extrae descriptores dos veces
  por objeto y a 100 000 eso cuesta horas sin cambiar el resultado de forma
  apreciable. El costo declarado es que el IDF es una estimacion por muestra.
- **100 000 objetos son 4.8 GB en disco** y no se versionan. Un clon limpio solo
  trae los resumenes; el corpus se regenera con la semilla.

## Reproducir

```powershell
# los tres tamanos (reutiliza lo ya generado)
python -m benchmarks.multimedia_corpus --sizes 1000 10000 100000 --reanudar

# solo recalcular metricas de un corpus existente
python -m benchmarks.multimedia_corpus --sizes 100000 --solo-metricas

# galeria de aciertos y errores sobre el corpus de 1000
python -m benchmarks.multimedia_gallery --corpus data/multimedia/1000
```

La galeria usa una imagen de consulta por familia y muestra sus cinco vecinos
mas cercanos: 35 de 40 vecinos son de la familia correcta (0.875). La figura
queda en `plots/galeria_multimedia.png`.

El audio requiere `librosa` y `soundfile` (estan en `requirements.txt`). Si
faltan, los WAV se generan igual pero sin vector, y el resumen queda con
`audio_con_vector: false`.

## Archivos historicos

`extraccion.csv` y `extraccion.json` de este directorio son la primera corrida
(1 000 objetos, solo imagen, `librosa` no instalado). Se conservan como
evidencia; los numeros vigentes estan en `extraccion_<n>.json`.
