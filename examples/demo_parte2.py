"""Demo de la Parte 2 (datos espaciales) por consola.

Recorre el flujo completo de la demostración:

1. crear una tabla con columnas de latitud/longitud,
2. cargar un CSV de tiendas,
3. crear el índice **R-Tree**,
4. resolver las tres consultas espaciales del enunciado,
5. mostrar cómo cambia el plan de ejecución antes y después del índice.

Uso:
    python -m examples.demo_parte2
    python examples/demo_parte2.py --puntos 5000
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine import DemoEngine  # noqa: E402
from spatial.geo import generate_points, haversine  # noqa: E402

#: Centro de la demo (Lima).
CENTER = (-12.0464, -77.0428)


def _titulo(texto: str) -> None:
    print()
    print("=" * 74)
    print(texto)
    print("=" * 74)


def _mostrar(resultado, limite: int = 4) -> None:
    plan = resultado.execution_plan or {}
    print(
        f"  ok={resultado.success} filas={len(resultado.rows)} "
        f"ruta={plan.get('access_path')} idx={plan.get('used_indexes')} "
        f"tiempo={resultado.execution_time_ms:.3f} ms"
    )
    if resultado.error:
        print("  ERROR:", resultado.error)
    if plan.get("runtime_steps"):
        print(
            "  traza:",
            [
                (paso.get("operator"), round(paso.get("elapsed_ms", 0.0), 3))
                for paso in plan["runtime_steps"]
            ],
        )
    for fila in resultado.rows[:limite]:
        resumen = {
            clave: valor
            for clave, valor in fila.items()
            if clave in {"id", "nombre", "categoria", "_distance"}
        }
        if "_distance" in resumen and resumen["_distance"] is not None:
            resumen["_distance"] = f"{resumen['_distance']:.1f} m"
        print("   ", resumen)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo espacial de la Parte 2")
    parser.add_argument("--puntos", type=int, default=2000)
    parser.add_argument("--radio", type=float, default=2000.0)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directorio de datos (por defecto uno temporal)",
    )
    args = parser.parse_args()

    temporal = None
    if args.data_dir:
        base = Path(args.data_dir)
        base.mkdir(parents=True, exist_ok=True)
    else:
        # Se usa un directorio dentro del proyecto (y no %TEMP%) para que la demo
        # funcione en entornos donde el temporal del sistema no es escribible.
        base = Path(__file__).resolve().parents[1] / "demo_parte2_data"
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True, exist_ok=True)
        temporal = str(base)

    try:
        engine = DemoEngine(data_dir=base, seed=False)

        _titulo("1 · TABLA CON COLUMNAS ESPACIALES")
        _mostrar(
            engine.run(
                "CREATE TABLE tiendas ("
                "id INT PRIMARY KEY, nombre VARCHAR(40), categoria VARCHAR(10), "
                "lat FLOAT, lon FLOAT)"
            )
        )

        # El CSV se genera con focos de densidad para que los MBR se solapen.
        print(f"  generando {args.puntos:,} tiendas...")
        puntos = generate_points(
            args.puntos, center=CENTER, spread_km=25.0, seed=42
        )
        lineas = ["id,nombre,categoria,lat,lon"]
        for i, (lat, lon) in enumerate(puntos, start=1):
            lineas.append(
                f"{i},Tienda {i},{'A' if i % 2 else 'B'},{lat:.6f},{lon:.6f}"
            )

        _titulo("2 · CARGA DEL CSV")
        reporte = engine.import_csv("tiendas", "\n".join(lineas) + "\n")
        print(
            f"  filas leídas={reporte.rows_read} insertadas={reporte.inserted} "
            f"rechazadas={reporte.failed}"
        )

        _titulo("3 · SIN ÍNDICE ESPACIAL (el plan no puede usar el R-Tree)")
        _mostrar(
            engine.run(
                "EXPLAIN SELECT * FROM tiendas WHERE "
                f"distancia(lat, POINT({CENTER[0]}, {CENTER[1]})) < {args.radio}"
            )
        )

        _titulo("4 · CREATE INDEX ... USING RTREE")
        _mostrar(
            engine.run(
                "CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) "
                "USING RTREE"
            )
        )
        registrado = engine.catalog.spatial_index_for("tiendas", "lat")
        implementacion = registrado.implementation
        print(
            f"  índice {registrado.metadata.name}: "
            f"{len(implementacion)} puntos, altura {implementacion.tree.height}, "
            f"llenado {implementacion.stats()['fill_factor']:.1%}"
        )

        _titulo(f"5 · CONSULTA POR RANGO ({args.radio:,.0f} m)")
        inicio = time.perf_counter()
        resultado = engine.run(
            "SELECT id, nombre, lat, lon FROM tiendas WHERE "
            f"distancia(lat, POINT({CENTER[0]}, {CENTER[1]})) < {args.radio}"
        )
        _mostrar(resultado)
        del_indice = {fila["id"] for fila in resultado.rows}

        # Verificación contra fuerza bruta.
        de_fuerza = {
            i for i, punto in enumerate(puntos, start=1)
            if haversine(CENTER, punto) < args.radio
        }
        print(
            f"  verificación contra fuerza bruta: "
            f"{'COINCIDE' if del_indice == de_fuerza else 'DIFIERE'} "
            f"({len(del_indice)} vs {len(de_fuerza)})"
        )

        _titulo(f"6 · k-NN (los {args.k} más cercanos)")
        _mostrar(
            engine.run(
                "SELECT id, nombre, lat, lon FROM tiendas ORDER BY "
                f"distancia(lat, POINT({CENTER[0]}, {CENTER[1]})) LIMIT {args.k}"
            )
        )

        _titulo("7 · INTERSECCIÓN CON POLÍGONO")
        ancho = 0.04
        anillo = [
            (CENTER[0] - ancho, CENTER[1] - ancho),
            (CENTER[0] - ancho, CENTER[1] + ancho),
            (CENTER[0] + ancho, CENTER[1] + ancho),
            (CENTER[0] + ancho, CENTER[1] - ancho),
        ]
        vertices = ", ".join(f"{lat} {lon}" for lat, lon in anillo)
        _mostrar(
            engine.run(
                f"SELECT id, nombre FROM tiendas WHERE "
                f"dentro_de(lat, POLYGON(({vertices})))"
            )
        )

        _titulo("8 · EXPLAIN ANALYZE DE UNA CONSULTA ESPACIAL")
        resultado = engine.run(
            "EXPLAIN ANALYZE SELECT * FROM tiendas ORDER BY "
            f"distancia(lat, POINT({CENTER[0]}, {CENTER[1]})) LIMIT {args.k}"
        )
        if resultado.rows:
            for linea in resultado.rows[0]["plan"].splitlines():
                print("   ", linea)

        _titulo("9 · RENDIMIENTO FRENTE A LA BÚSQUEDA SECUENCIAL")
        consultas = 20
        inicio = time.perf_counter()
        for _ in range(consultas):
            engine.run(
                "SELECT id FROM tiendas ORDER BY "
                f"distancia(lat, POINT({CENTER[0]}, {CENTER[1]})) LIMIT {args.k}"
            )
        ms_rtree = (time.perf_counter() - inicio) * 1000 / consultas

        inicio = time.perf_counter()
        for _ in range(consultas):
            sorted((haversine(CENTER, punto) for punto in puntos))[: args.k]
        ms_secuencial = (time.perf_counter() - inicio) * 1000 / consultas

        print(f"  k-NN con R-Tree   : {ms_rtree:>8.3f} ms por consulta")
        print(f"  búsqueda secuencial: {ms_secuencial:>8.3f} ms por consulta")
        print(f"  -> el R-Tree es {ms_secuencial / ms_rtree:.1f}x más rápido")

        print()
        print(f"Directorio de datos: {base}")
        return 0
    finally:
        if temporal and os.environ.get("BD2_KEEP_DEMO") != "1":
            shutil.rmtree(temporal, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
