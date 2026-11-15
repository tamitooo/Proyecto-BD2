from benchmarks.benchmark_indexes import run


def _rows(**kw):
    return run(sizes=kw.get("sizes", (60,)), queries=5, mutations=3, seed=7)


def _by(rows, index_type, metric):
    return next(r for r in rows if r["index_type"] == index_type and r["metric"] == metric)


def test_reporta_las_tres_tecnicas_y_la_linea_base():
    rows = _rows()
    assert {r["index_type"] for r in rows} == {
        "linear_scan", "bplus_clustered", "bplus_unclustered", "extendible_hash"
    }


def test_metricas_por_tecnica():
    rows = _rows()
    for kind in ("bplus_clustered", "bplus_unclustered", "extendible_hash"):
        metrics = {r["metric"] for r in rows if r["index_type"] == kind}
        assert metrics == {"build", "exact_lookup", "range_search", "ordered_scan", "insert_mutation"}


def test_hash_no_soporta_rango_ni_orden():
    rows = _rows()
    assert _by(rows, "extendible_hash", "range_search")["supported"] is False
    assert _by(rows, "extendible_hash", "ordered_scan")["supported"] is False
    assert _by(rows, "bplus_clustered", "range_search")["supported"] is True


def test_todas_las_busquedas_encuentran_registros():
    rows = _rows()
    for kind in ("linear_scan", "bplus_clustered", "bplus_unclustered", "extendible_hash"):
        assert _by(rows, kind, "exact_lookup")["result_items"] > 0
    for kind in ("linear_scan", "bplus_clustered", "bplus_unclustered"):
        assert _by(rows, kind, "range_search")["result_items"] > 0


def test_scan_ordenado_recorre_todo_y_los_tiempos_son_validos():
    rows = _rows(sizes=(30, 90))
    for n in (30, 90):
        for kind in ("bplus_clustered", "bplus_unclustered"):
            assert next(
                r for r in rows
                if r["dataset_size"] == n and r["index_type"] == kind and r["metric"] == "ordered_scan"
            )["result_items"] == n
    assert all(r["avg_us"] is None or r["avg_us"] >= 0 for r in rows)
    assert all(r["size_bytes"] >= 0 for r in rows)
