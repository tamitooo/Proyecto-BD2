# Borrador de las secciones de Partes 3 y 4 del informe

Instrucciones: cada bloque trae los hechos y un parrafo con huecos. Llena los
huecos con una o dos oraciones tuyas. No hace falta que quede bien escrito;
con que el argumento sea tuyo alcanza. Cuando termines, avisame y reviso
numero por numero contra los CSV.

---

## 1. Corpus y metodologia

Hechos:

- Corpus sintetico en tres tamanos: 1 000, 10 000 y 100 000 documentos.
- 36 consultas: 12 de una palabra, 12 de tres, 12 de cinco a siete.
- 10 documentos respuesta por consulta, definidos antes de generar el texto.
- Vocabulario comun con frecuencia tipo Zipf y terminos de consulta inyectados al 0.02 por ciento.
- Semilla fija: dos corridas producen el mismo archivo.
- Tokenizacion: minusculas y separacion por espacios, sin stemming ni stopwords.

Parrafo:

> Para comparar las tecnicas de busqueda textual se genero un corpus sintetico
> de tres tamanos porque ______. La relevancia se define antes de escribir el
> texto, de modo que ______. La semilla fija permite ______. Conviene aclarar
> que este corpus no es lenguaje natural, por lo que ______.

---

## 2. Resultados de busqueda textual

Hechos:

- Construccion con 100 000 documentos: 3.78 s el motor, 7.97 s el indice GIN.
- Consulta promedio: 0.25 ms TF-IDF, 0.66 ms BM25, 1.42 ms GIN.
- Memoria: 404.58 MB el motor, 5.58 MB el indice GIN en disco.
- Precision@10: 1.000 BM25 y GIN, 0.958 TF-IDF.

Parrafo:

> El motor propio construye su estructura en 3.78 s frente a 7.97 s de GIN,
> pero ______. La consulta del motor resulta mas rapida en parte porque
> ______, y no tanto porque ______. BM25 y GIN empatan en precision, mientras
> que TF-IDF baja a 0.958 porque ______.

---

## 3. Resultados de indices vectoriales

Hechos:

- Construccion con 100 000 vectores: 670.6 s IVF, 1690.5 s HNSW.
- Consulta: 15.81 ms IVF, 10.48 ms HNSW.
- Recall@10: 0.907 IVF, 0.749 HNSW.
- Memoria: 113.55 MB IVF, 228.12 MB HNSW.

Parrafo:

> IVF construye en 670.6 s y HNSW en 1690.5 s, lo que indica ______. La
> ventaja de HNSW en consulta aparece recien entre 10 000 y 100 000 vectores
> porque ______. El recall de HNSW cae a 0.749 con el tamano, y eso se explica
> por ______.

---

## 4. Conclusiones

Hechos: las tablas de `docs/comparacion_texto.md` y `docs/comparacion_vector.md`.

Parrafo:

> Para busqueda textual en este proyecto conviene ______ porque ______. Para
> indices vectoriales la eleccion depende de ______, y el criterio practico
> seria ______. La comparacion contra PostgreSQL sirve para ______, y no para
> ______.

---

## 5. Limitaciones

Hechos: corpus sintetico, vectores sinteticos, medicion en una sola maquina.

Parrafo:

> El corpus sintetico impide afirmar ______. La medicion de memoria corresponde
> a ______ y no a ______. Por ultimo, la comparacion contra PostgreSQL no es
> del todo justa porque ______.
