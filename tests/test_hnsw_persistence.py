from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from query.vector_queries import VectorExecutor
from vector.hnsw import HNSWIndex
from vector.metrics import get_search_metric


def _index(metric="euclidean"):
    index = HNSWIndex(
        M=4,
        ef_construction=20,
        ef_search=10,
        random_seed=7,
        metric=get_search_metric(metric),
        metric_name=metric,
    )
    for i, vector in enumerate(((0, 0), (1, 0), (0, 1), (2, 2), (5, 5))):
        index.insert(i, vector)
    return index


def test_hnsw_roundtrip_preserva_grafo_y_resultados(tmp_path):
    path = tmp_path / "index.idx"
    original = _index()
    original.source_signature = "dataset-v1"
    expected = original.search_similar((0.2, 0.1), k=3)

    original.save(path)
    restored = HNSWIndex.load(path)

    assert restored.validate()
    assert restored.source_signature == "dataset-v1"
    assert restored.entry_point == original.entry_point
    assert restored.max_level == original.max_level
    assert restored.nodes == original.nodes
    assert restored.search_similar((0.2, 0.1), k=3) == expected


def test_load_no_reinserta_vectores(tmp_path):
    path = tmp_path / "index.idx"
    _index().save(path)

    with patch.object(HNSWIndex, "insert", side_effect=AssertionError("NO REBUILD")):
        restored = HNSWIndex.load(path)

    assert len(restored) == 5
    assert restored.validate()


def test_vector_executor_reutiliza_hnsw_persistido(tmp_path):
    executor = VectorExecutor(SimpleNamespace(data_dir=tmp_path))
    vectors = [(0, (0.0, 0.0)), (1, (1.0, 0.0)), (2, (0.0, 1.0))]

    first, reused, path = executor._load_or_build_hnsw(
        "imagenes", "embedding", "euclidean", vectors
    )
    assert reused is False
    assert Path(path).exists()
    assert len(first) == 3

    with patch.object(HNSWIndex, "insert", side_effect=AssertionError("NO REBUILD")):
        second, reused, same_path = executor._load_or_build_hnsw(
            "imagenes", "embedding", "euclidean", vectors
        )

    assert reused is True
    assert same_path == path
    assert second.search_similar((0.1, 0.0), k=2) == first.search_similar((0.1, 0.0), k=2)


def test_vector_executor_reconstruye_si_cambian_vectores(tmp_path):
    executor = VectorExecutor(SimpleNamespace(data_dir=tmp_path))
    original = [(0, (0.0, 0.0)), (1, (1.0, 0.0))]
    changed = [(0, (9.0, 9.0)), (1, (1.0, 0.0))]

    _, reused, _ = executor._load_or_build_hnsw(
        "imagenes", "embedding", "euclidean", original
    )
    assert reused is False

    rebuilt, reused, _ = executor._load_or_build_hnsw(
        "imagenes", "embedding", "euclidean", changed
    )
    assert reused is False
    assert rebuilt.source_signature == executor._vectors_signature(changed)
