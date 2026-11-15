from benchmarks.benchmark_heap_vs_sequential import run


def _by(rows, storage, metric, n=None):
    return next(
        r for r in rows
        if r["storage"] == storage and r["metric"] == metric and (n is None or r["dataset_size"] == n)
    )


def test_reporta_heap_y_secuencial_con_sus_metricas():
    rows = run(sizes=(40,), search_queries=5, insert_queries=3, seed=1)
    for storage in ("heap", "sequential"):
        metrics = {r["metric"] for r in rows if r["storage"] == storage}
        assert metrics == {"insert", "search_pk", "disk_space", "reorganize"}


def test_heap_no_reorganiza_y_el_secuencial_si():
    rows = run(sizes=(40,), search_queries=5, insert_queries=3, seed=1)
    assert _by(rows, "heap", "reorganize")["supported"] is False
    reorg = _by(rows, "sequential", "reorganize")
    assert reorg["supported"] is True
    assert reorg["avg_us"] >= 0


def test_espacio_crece_con_el_tamano():
    rows = run(sizes=(20, 200), search_queries=3, insert_queries=2, seed=2)
    for storage in ("heap", "sequential"):
        assert _by(rows, storage, "disk_space", 200)["size_bytes"] > _by(rows, storage, "disk_space", 20)["size_bytes"]


def test_conteo_de_operaciones():
    rows = run(sizes=(50,), search_queries=7, insert_queries=4, seed=3)
    for storage in ("heap", "sequential"):
        assert _by(rows, storage, "search_pk")["operations"] == 7
        assert _by(rows, storage, "insert")["operations"] == 4
