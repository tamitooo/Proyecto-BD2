### Evaluación Precision@10 — cestas del mismo usuario y fecha

Catálogo evaluado: **30 productos**; **200 compras**; **196 casos** de evaluación; **5 pliegues por usuario** (semilla 2026).

| Fuente | P@10 | Recall@10 | Hit@10 | P@3 | NDCG@10 |
|---|---:|---:|---:|---:|---:|
| Co-compra | 0.0714 | 0.5485 | 0.6429 | 0.0867 | 0.2845 |
| Metadatos | 0.0051 | 0.0230 | 0.0510 | 0.0136 | 0.0207 |
| Descripcion | 0.0398 | 0.2513 | 0.3571 | 0.0136 | 0.1063 |
| Fusion: pesos iguales | 0.0520 | 0.3805 | 0.4796 | 0.0153 | 0.1566 |
| Fusion: solo co-compra | 0.0714 | 0.5485 | 0.6429 | 0.0867 | 0.2845 |
| Fusion: pesos seleccionados en entrenamiento | 0.0714 | 0.5485 | 0.6429 | 0.0867 | 0.2845 |

![Precision@10 por fuente](../../benchmarks/results/parte5/p5_precision_por_fuente.png)

**Máximo P@10 bajo esta relevancia:** 0.1449; **azar esperado:** 0.0500. Estos valores impiden interpretar P@10 como porcentaje de acierto general.

**Validación de pesos:** los pesos de fusion_validada se seleccionan en una validación interna por usuarios de ENTRENAMIENTO (no en test). El modelo final de la aplicación se debe reentrenar por separado.

**Protocolo:** relevante = otros productos distintos de la misma cesta (mismo usuario y fecha). La co-compra se entrena con usuarios distintos de los evaluados para evitar fuga de datos.

**Limitación:** no se incluyó búsqueda visual porque no se entregaron embeddings visuales del catálogo; no se debe reportar esta fuente como 0. Las otras fuentes son offline, no SQL/IVF real.
