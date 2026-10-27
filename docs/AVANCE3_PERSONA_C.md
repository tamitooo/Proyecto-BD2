# Avance 3 — Persona C

## Issue #53 — Estadísticas para BM25

Implementado en `text/statistics.py`.

### Contrato

El módulo **no tokeniza** ni aplica stopwords/stemming. Recibe tokens ya normalizados por el pipeline de Persona A para que SPIMI y BM25 trabajen sobre exactamente la misma representación.

Expone:

- `term_frequency(term, doc_id)` → `tf(t,d)`
- `document_frequency(term)` → `df(t)`
- `document_length(doc_id)` → `|d|`
- `document_count` → `N`
- `average_document_length` → `avgdl`
- `add_document(doc_id, tokens)`
- `remove_document(doc_id)`
- `from_documents(...)`

### Pruebas

```bash
python -m pytest tests/test_bm25_statistics.py -q
```

Casos cubiertos:

- TF y DF
- longitudes y `avgdl`
- términos inexistentes
- documento vacío
- IDs duplicados
- eliminación y actualización de estadísticas
- limpieza total

### Estado

- Tests específicos: `6 passed`
- Suite completa después del cambio: `37 passed`

## Siguiente issue

#54 — Implementar score BM25 con parámetros `k1` y `b` reutilizando estas estadísticas.

---

## Issue #54 — Score BM25 con parámetros `k1` y `b`

Implementado en `text/bm25.py` mediante `BM25Ranker`.

### Fórmula

Para cada término `t` de la consulta y documento `d`:

```text
IDF(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(t,d) = IDF(t) *
             tf(t,d) * (k1 + 1)
             -----------------------------------------------
             tf(t,d) + k1 * (1 - b + b * |d| / avgdl)
```

El score total es la suma de los aportes de los términos de la consulta.

### Contrato

```python
from text import BM25Ranker, BM25Statistics

ranker = BM25Ranker(stats, k1=1.2, b=0.75)
ranker.idf("base")
ranker.term_score("base", doc_id=1)
ranker.score(doc_id=1, query_terms=["base", "dato"])
```

- `k1` debe ser `> 0`.
- `b` debe estar en `[0, 1]`.
- No realiza tokenización: consume los términos normalizados por Persona A.
- No selecciona candidatos ni devuelve top-k: eso corresponde al issue #55.

### Pruebas

```bash
python -m pytest tests/test_bm25.py -q
```

Se verifica IDF, fórmula manual, consultas multi-término, saturación de TF,
normalización por longitud, parámetros, términos ausentes y casos borde.
