# Comparacion de indices vectoriales: IVF contra HNSW (Parte 4)

Medido sobre vectores sinteticos de 32 dimensiones agrupados en ocho grupos,
100 consultas por tamano, k = 10 y distancia euclidiana. Los valores de la
tabla corresponden a 100 000 vectores.

| Indice | Ventaja | Desventaja | Evidencia medida |
|---|---|---|---|
| IVF | Construccion mas barata, la mitad de memoria y un recall que se mantiene estable al crecer. | La consulta se encarece con el tamano, porque revisa listas completas. | 670.6 s de construccion, 15.81 ms por consulta, recall de 0.907, 113.55 MB |
| HNSW | La consulta crece con el logaritmo del tamano, no con el tamano. Gana en latencia a partir de 100 000. | Construccion muy costosa, el doble de memoria y el recall cae si no se ajustan los parametros. | 1690.5 s de construccion, 10.48 ms por consulta, recall de 0.749, 228.12 MB |

## El cruce de velocidad

Con 10 000 vectores, IVF consulta en 2.32 ms y HNSW en 7.86 ms. Con 100 000,
IVF sube a 15.81 ms y HNSW a 10.48 ms. El cruce ocurre entre esos dos tamanos.
La razon es que IVF compara contra `n_probe` listas que crecen con el corpus,
mientras que HNSW recorre un grafo cuya profundidad crece con el logaritmo.

## El costo de la calidad

El recall de HNSW cae de 0.916 a 0.749 al pasar de 1 000 a 100 000 vectores,
mientras que IVF se mantiene entre 1.000 y 0.907. Con `M` y `ef_search` fijos,
el grafo pierde vecinos utiles cuando la coleccion crece. Subir `ef_search`
recupera recall a cambio de latencia.

## Cuando usar cada uno

- Hasta 10 000 vectores: IVF, que construye mas rapido y ocupa menos.
- Colecciones grandes con latencia critica: HNSW, aceptando ajustar `ef_search`.
- Cuando el recall es requisito duro: IVF con `n_probe` alto, o fuerza bruta si el corpus lo permite.
