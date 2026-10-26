# Changelog · Corrección de rúbrica

## Persistencia de índices

- Nuevo `indexes/persistence.py` con escritura binaria atómica (`tmp` + `fsync` + `os.replace`).
- `ClusteredBPlusIndex`: `file_path`, `attach_file`, `persist`, `load`, borrado de archivo.
- `UnclusteredBPlusIndex`: misma persistencia.
- `ExtendibleHash`: persistencia del directorio, buckets, profundidades y entradas.
- `RTree`: `serialize`, `deserialize`, `serialized_size_bytes`.
- `SpatialIndex`: persistencia de puntos y de los árboles Euclidiano/Haversine.
- `Catalog`: ruta física por índice, carga al reiniciar sin rebuild cuando existe `.idx`, limpieza al DROP.
- `backend/engine.py`: muestra los archivos de índice y su tamaño en el panel de archivos.

## Verificación

- Baseline del paquete: 27 tests.
- Después de la corrección: 31 tests.
- Nuevas pruebas: `tests/test_index_persistence.py`.
- Test clave: restaura el catálogo con `HeapFile.scan()` bloqueado; confirma que los índices vienen del archivo persistente.

## Demo

```bash
python -m examples.demo_persistencia_indices
```
