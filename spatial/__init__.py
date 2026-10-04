"""Módulo espacial de la Parte 2: R-Tree, distancias y geometría.

* ``spatial/geo.py`` — distancias (Euclidiana y Haversine), MBR de círculos,
  polígonos (punto-en-polígono, área, perímetro) y generación de datasets.
* ``spatial/index.py`` — envoltorio del R-Tree que entiende latitud/longitud y
  las dos métricas, para el catálogo y el ejecutor.

El índice R-Tree en sí vive en ``indexes/rtree.py``, junto a los demás índices
del proyecto.
"""
