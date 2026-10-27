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

---

## Issue #55 — Ranking top-k con BM25

Implementado en `BM25Ranker.search(...)` dentro de `text/bm25.py`.

### Contrato

```python
results = ranker.search(
    ["base", "dato", "vectorial"],
    k=10,
)
# [(doc_id, score), ...]
```

### Comportamiento

- Los candidatos salen de la unión de posting lists de los términos consultados.
- No se hace un scan completo de todos los documentos para cada query.
- Se calcula BM25 únicamente sobre candidatos.
- Se retorna como máximo `k` resultados.
- El orden es score descendente.
- Los empates se resuelven de forma determinista por `doc_id`.
- Consulta vacía, términos inexistentes o `k <= 0` retornan `[]`.
- `k > número de candidatos` retorna todos los candidatos válidos.

Para soportar este issue, `BM25Statistics` expone también:

- `documents_for_term(term)`
- `candidate_documents(terms)`

Las posting lists se mantienen incrementalmente al agregar o eliminar documentos.

### Pruebas

```bash
python -m pytest tests/test_bm25_statistics.py tests/test_bm25.py -q
```

Resultado específico acumulado de Persona C: `22 passed`.

Suite completa del proyecto después de #55: `53 passed`.

## Estado acumulado Persona C — Parte 3

- [x] #53 Frecuencias y longitudes de documentos para BM25
- [x] #54 Score BM25 con `k1` y `b`
- [x] #55 Ranking top-k con BM25
- [x] Tests unitarios de BM25 correspondientes a #72

La integración SQL `MATCH(... ) USING BM25`, `SCORE()`, `ORDER BY` y `LIMIT` queda para Persona D.
