# IVF contra HNSW (Parte 4)

Dos tablas, misma metodologia (k = 10, 100 consultas, Recall@10 contra fuerza
bruta, memoria con `deep_size()`):

| Archivo | Fuente | Metricas | Tamanos |
|---|---|---|---|
| `ivf_hnsw_corpus_image.csv` | corpus multimedia, vectores SIFT de `data/multimedia/<n>/` | euclidiana y coseno | 1 000 / 10 000 / 100 000 |
| `ivf_hnsw_corpus_audio.csv` | corpus multimedia, vectores MFCC | euclidiana y coseno | 1 000 / 10 000 |
| `ivf_hnsw.csv` | vectores sinteticos agrupados | euclidiana y coseno | 1 000 / 10 000 / 100 000 (coseno solo hasta 10 000) |

La tabla del corpus es la que responde a la rubrica 2.4.4, que pide «datasets
de 1 000, 10 000 y 100 000 imagenes/audios». La sintetica se conserva como
referencia historica y como contraste: el balance IVF/HNSW cambia con la
geometria de los datos.

Analisis, lectura y cuando usar cada indice: `docs/informe/comparacion_vector.md`.

## Reproducir

```powershell
# corpus (requiere haber generado antes el dataset de la Parte 4)
python -m benchmarks.multimedia_corpus --sizes 1000 10000 100000 --reanudar

python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 1000 10000 100000 `
    --corpus data/multimedia --modalidad image --metricas euclidean cosine

python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 1000 10000 `
    --corpus data/multimedia --modalidad audio --metricas euclidean cosine

# sintetico (valores historicos)
python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 1000 10000 100000
```

## Graficas

`plots/vector_corpus_{construccion,consulta,recall,memoria}.png` salen del
corpus con las dos metricas; `plots/vector_{...}.png` siguen siendo las
sinteticas con euclidiana.

```powershell
python -m benchmarks.generate_vector_charts --csv ivf_hnsw_corpus_image.csv `
    --prefijo vector_corpus --metricas euclidean cosine
python -m benchmarks.generate_vector_charts   # sintetico, euclidiana
```

## Costo de la corrida

A 100 000 vectores de 32 dimensiones: HNSW tarda ~22 min en construirse por
metrica e IVF ~6 min; la corrida completa de imagen (tres tamanos, dos metricas)
son ~1 h 20 min en un nucleo. Las consultas de Recall@10 se calculan contra
fuerza bruta, que a 100 000 objetos domina parte de ese tiempo.
