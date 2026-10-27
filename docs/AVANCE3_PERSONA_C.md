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
