# Precision@10 de la tienda (Parte 5, #141)

`precision_fuentes.csv`, `precision_fuentes.json` y `p5_precision_por_fuente.png` comparan cada
fuente de recomendación sola contra la fusión. Los genera `tools.aprender_pesos` con las mismas
consultas que la ficha de producto (BM25, IVF coseno, co-compra y metadatos por la API).

- Datos: 2531 productos de Amazon Berkeley Objects (`tools.preparar_abo`), 30 tiendas y
  10 000 compras de 2500 usuarios (`tools.generate_part5_data`, semilla 2026).
- Relevancia: para un producto X de una compra con 2 o más productos, los demás productos de esa
  misma compra (mismo usuario y fecha).
- Validación cruzada de 5 pliegues por usuarios; la co-compra nunca cuenta al usuario evaluado.
- "Máximo posible": una compra con menos de 10 productos no puede llenar el top 10.

Los dos primeros pasos ya están hechos: el resultado es `examples/tienda_abo/`.
Las salidas reales de la corrida (conteos, tiempos y resultados) están en `EVIDENCIA.md`.
Para reproducir todo (unos 40 minutos):

```
python -m tools.preparar_abo --raw data/abo_raw --salida data/tienda_abo --por-categoria 450
python -m tools.generate_part5_data --products data/tienda_abo/productos.csv --output examples/tienda_abo \
  --stores 30 --users 2500 --purchases 10000 --seed 2026 --images data/tienda_abo/imagenes
# con el backend corriendo sobre un BD2_DATA_DIR vacío:
python -m tools.seed_tienda --datos examples/tienda_abo --data-dir <BD2_DATA_DIR>
python -m tools.aprender_pesos
```

Los archivos `precision_results.csv`, `precision_summary.json`, `precision_queries.csv` y
`precision_comparison.png` son de una versión anterior (`benchmarks/benchmark_part5_precision.py`,
productos geométricos sintéticos y relevancia = última compra de cada usuario).

`fuera_de_linea/` tiene una evaluación aparte (`benchmarks/p5_precision_por_fuente.py`) con más
métricas (Recall@10, NDCG@10, Hit@10), corrida sobre la muestra de 30 productos sin pasar por el
motor.
