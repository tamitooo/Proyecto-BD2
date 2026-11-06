# Secciones de Partes 3 y 4 del informe

Redactado a partir de las respuestas del autor de la parte. Los numeros salen
de `benchmarks/results/text` y `benchmarks/results/vector`. Corregir lo que no
suene propio y avisar para ajustar el resto del documento.

---

## Corpus y metodologia

Para comparar las tecnicas de busqueda textual se genero un corpus sintetico en
tres tamanos: 1 000, 10 000 y 100 000 documentos. La decision tiene tres
motivos. El primero es la reproducibilidad: con una semilla fija, dos corridas
producen el mismo archivo y cualquier cifra del informe se puede volver a
calcular. El segundo es que no hay descargas externas ni dependencia de la red,
asi que el experimento corre igual en cualquier maquina. El tercero, y el que
mas pesa para medir relevancia, es que la respuesta correcta se conoce de
antemano: cada consulta tiene diez documentos escritos para contener sus
terminos, de modo que Precision@10 y Recall@10 se calculan contra una etiqueta
cierta y no contra una estimacion.

El banco tiene 36 consultas repartidas en tres grupos iguales: una palabra, tres
palabras y cinco a siete palabras. Los documentos comunes usan un vocabulario
con frecuencia tipo Zipf y contienen terminos de consulta con probabilidad muy
baja, para que existan falsos positivos. Los documentos que responden a una
consulta repiten sus terminos entre dos y cuatro veces, de modo que el ranking
tenga una senal y no dependa del azar.

## Resultados de busqueda textual

Con 100 000 documentos, el motor construye sus estadisticas en 3.78 s, mientras
que el indice GIN de PostgreSQL tarda 7.97 s en construirse sobre una carga de
1.57 s. En consulta, el motor es mas rapido: 0.66 ms BM25 y 0.25 ms TF-IDF
frente a 1.42 ms de GIN. Esa ventaja no proviene del algoritmo sino del
contexto: el motor consulta una estructura en memoria dentro del mismo proceso,
mientras que GIN paga parseo de SQL, planificacion, viaje por socket y lectura
de disco.

La diferencia grande aparece en el espacio. El motor ocupa 404.58 MB de memoria
para el corpus de 100 000 documentos, y el indice GIN ocupa 5.58 MB en disco
sobre una tabla de 44.4 MB. La causa es que las estadisticas guardan un
diccionario de frecuencias por documento, un mapa de terminos a documentos y el
largo de cada documento en objetos de Python.

En precision, BM25 y GIN empatan en 1.000 porque el corpus es separable: los
documentos respuesta repiten los terminos y ningun otro documento los contiene
todos. TF-IDF baja a 0.958 porque normaliza por la norma del vector del
documento, y eso castiga a los textos con vocabulario amplio aunque contengan el
termino buscado.

## Resultados de indices vectoriales

Con 100 000 vectores de 32 dimensiones, IVF construye en 670.6 s y ocupa 113.55
MB, mientras que HNSW tarda 1690.5 s y ocupa 228.12 MB. La construccion de HNSW
cuesta dos veces y media mas porque cada insercion recorre el grafo para
encontrar vecinos, mientras que IVF solo asigna el vector a una lista.

En consulta la ventaja se invierte con el tamano. Con 10 000 vectores IVF
responde en 2.32 ms y HNSW en 7.86 ms. Con 100 000, IVF sube a 15.81 ms y HNSW
a 10.48 ms. IVF revisa `n_probe` listas que crecen con el corpus; HNSW navega un
grafo cuya profundidad crece con el logaritmo.

El recall se separa en el mismo sentido. IVF pasa de 1.000 a 0.907 y HNSW de
0.916 a 0.749. Con `M` y `ef_search` fijos, la busqueda voraz recorre menos
caminos a medida que la coleccion se hace mas densa, y queda atrapada en
optimos locales sin llegar a los vecinos exactos. Subir `ef_search` recupera
recall a cambio de latencia.

## Conclusiones

Para busqueda textual en este proyecto, TF-IDF sirve cuando el vocabulario es
homogeneo y se necesita explicar el ranking con pocas piezas. BM25 conviene
cuando los documentos tienen largos distintos, porque satura la repeticion y
corrige por longitud. GIN es la opcion cuando el corpus no cabe en memoria y el
sistema tiene que atender a varios usuarios a la vez.

Para indices vectoriales, IVF gana en construccion, memoria y recall estable
hasta 10 000 vectores. HNSW gana en latencia cuando el corpus crece, siempre que
se ajusten `M` y `ef_search`. Si el recall es un requisito duro, la alternativa
es IVF con `n_probe` alto o la fuerza bruta.

La comparacion contra PostgreSQL sirve para ubicar al motor propio frente a un
sistema maduro. No sirve para declarar superioridad: se comparan estructuras en
memoria con un motor que ademas sostiene persistencia, control transaccional y
concurrencia.

## Limitaciones

El corpus es sintetico, asi que no se puede afirmar que el motor se comporte
igual sobre lenguaje natural, con errores de escritura, sinonimos o documentos
de largos muy distintos. Los vectores tambien son sinteticos y estan separados
en grupos, una geometria mas facil que la de descriptores SIFT o MFCC reales.

La medicion de memoria corresponde a la estructura de datos del motor y no al
proceso completo de Python. Del lado de PostgreSQL, el tamano del indice es el
reportado por el sistema de archivos, sin contar cache ni memoria compartida.

Por ultimo, todas las mediciones se hicieron en una sola maquina, con los
procesos en caliente y sin concurrencia. Los tiempos absolutos no son
extrapolables a otro hardware, aunque las tendencias entre tamanos si.
