# Dataset sintetico de imagenes y audio (Parte 4)

Generado con `python -m benchmarks.multimedia_corpus --images 1000 --audios 1000`.
Los archivos viven en `data/multimedia/`, que no se versiona: se regeneran con la
misma semilla.

## Volumen

| Modalidad | Objetos | Familias | Formato |
|---|---|---|---|
| Imagen | 1 000 | 8 | PNG de 160 x 160 en escala de grises |
| Audio | 1 000 | 6 | WAV mono, 22 050 Hz, 1 segundo |

Peso en disco: 46.9 MB. Vectores exportados: `vectors.json`, 573 KB, dimension 32.

## Tiempos medidos

| Etapa | Tiempo |
|---|---|
| Entrenamiento del pipeline (vocabulario, K-Means, IDF) | 105.1 s |
| Extraccion de 1 000 vectores de imagen | 16.1 s, 16.1 ms por objeto |

## Calidad del espacio vectorial

Medida sobre las 1 000 imagenes con vector. Como cada imagen pertenece a una
familia generada, la familia funciona como etiqueta de relevancia.

| Metrica | Valor |
|---|---|
| Similitud coseno media, misma familia | 0.774 |
| Similitud coseno media, familia distinta | 0.183 |
| Precision@10 por familia, fuerza bruta | 0.891 |
| Vectores todo cero | 0 de 1 000 |

## Audio

Los 1 000 archivos WAV existen y son validos, pero no tienen vector todavia:
la extraccion MFCC depende de `librosa`, que no esta instalado en este entorno.
Los tests de MFCC se saltan por la misma razon. El pipeline esta implementado y
probado; falta la dependencia para correrlo.

## Reproducir

```powershell
python -m benchmarks.multimedia_corpus --images 1000 --audios 1000
```
