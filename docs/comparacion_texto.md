# Comparacion de tecnicas de busqueda textual (Parte 3)

Medido sobre el corpus sintetico en 1 000, 10 000 y 100 000 documentos, con 36
consultas por tamano y k = 10. Los valores de la tabla corresponden a 100 000.

| Tecnica | Ventaja | Desventaja | Evidencia medida |
|---|---|---|---|
| TF-IDF con coseno | Simple de explicar y de implementar. Normaliza por la norma del documento, asi que no premia a los textos largos por si solos. | Castiga documentos con vocabulario variado. Es la unica que pierde precision en consultas de una palabra. | 0.25 ms por consulta, P@10 de 0.958, 4.28 s de preparacion de normas |
| BM25 | Satura la frecuencia del termino y corrige por el largo del documento. Mejor precision en este corpus. | Depende de dos parametros (k1 y b) que hay que justificar y que cambian el resultado. | 0.66 ms por consulta, P@10 de 1.000 |
| GIN de PostgreSQL | El indice vive en disco y no consume memoria de la aplicacion. Es un sistema maduro, con años de uso en produccion. | Cuesta construirlo, necesita un servidor aparte y no es portable a otro motor. | 7.97 s de construccion, 1.42 ms por consulta, 5.58 MB de indice |

## Donde se nota la diferencia

El espacio es la diferencia mas grande: el motor propio ocupa 404.58 MB de
memoria para 100 000 documentos, mientras que el indice GIN ocupa 5.58 MB en
disco sobre una tabla de 44.4 MB. La causa es que nuestras estadisticas guardan
un diccionario por documento y un mapa de terminos a documentos en objetos de
Python, todo en RAM.

La precision no separa a BM25 de GIN: ambos llegan a 1.000. Separa a TF-IDF,
que baja a 0.958 porque su normalizacion castiga a los documentos con
vocabulario amplio.

## Cuando usar cada una

- Prototipo, coleccion pequeña o necesidad de explicar el ranking en una pizarra: TF-IDF.
- Documentos de largo variable, donde la longitud no debe premiar ni castigar de mas: BM25.
- Produccion, muchos usuarios y datos que no caben en memoria: GIN.
