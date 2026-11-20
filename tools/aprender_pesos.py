"""Aprende los pesos de la fusión de la tienda con el historial de compras (#138).

Si en una misma compra (mismo usuario y fecha) alguien llevó X e Y, Y es una
buena recomendación para X. Con esa idea se busca la combinación de pesos que
maximiza Precision@10:

1. Cada fuente se consulta una sola vez por producto, como lo hace la ficha.
   La co-compra se calcula aquí, sin el usuario evaluado, para no medir con el
   mismo dato que se recomienda.
2. Se prueban todos los pesos de la rejilla con la misma fusión de fusion.ts.
3. Validación cruzada por usuarios (k pliegues, semilla fija): se aprende con
   unos usuarios y se mide con otros, y se compara contra pesos iguales.
4. Los pesos finales se aprenden con todos los usuarios.

El resultado se escribe en frontend/src/tienda/pesosAprendidos.ts; la ficha lo
ofrece con el botón "Usar pesos aprendidos".

    python -m tools.aprender_pesos [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from tools.seed_tienda import Api, SeedError, esperar_api

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "frontend" / "src" / "tienda" / "pesosAprendidos.ts"
FUENTES = ("visual", "texto", "cocompra", "metadatos")
REJILLA = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
TOP_K = 10

Scores = List[Tuple[int, float]]
FuentesDe = Callable[["Caso"], Mapping[str, Scores]]


# --- Fusión: misma lógica que frontend/src/tienda/fusion.ts -----------------

def normalizar(lista: Iterable[Tuple[int, float]]) -> Scores:
    mejores: Dict[int, float] = {}
    for producto, score in lista:
        if score != score or score in (float("inf"), float("-inf")):
            continue
        if producto not in mejores or score > mejores[producto]:
            mejores[producto] = score
    if not mejores:
        return []
    minimo = min(mejores.values())
    rango = max(mejores.values()) - minimo
    return [(p, (s - minimo) / rango if rango > 0 else 1.0) for p, s in mejores.items()]


def fusionar(producto_id: int, por_fuente: Mapping[str, Scores], pesos: Mapping[str, float],
             k: int = TOP_K) -> List[int]:
    activas = [f for f in por_fuente if pesos.get(f, 1) > 0]
    total = sum(pesos.get(f, 1) for f in activas)
    score: Dict[int, float] = {}
    aportes: Dict[int, int] = {}
    for fuente in activas:
        peso = pesos.get(fuente, 1) / total
        sin_x = [(p, s) for p, s in por_fuente[fuente] if p != producto_id]
        for p, s in normalizar(sin_x):
            score[p] = score.get(p, 0.0) + s * peso
            aportes[p] = aportes.get(p, 0) + 1
    return sorted(score, key=lambda p: (-score[p], -aportes[p], p))[:k]


# --- Casos y evaluación ------------------------------------------------------

@dataclass(frozen=True)
class Caso:
    usuario: int
    producto: int
    relevantes: frozenset


def casos_de(cestas: Mapping[Tuple[int, str], Set[int]], usuarios: Iterable[int]) -> List[Caso]:
    """Un caso por producto de cada compra con 2 o más productos: lo demás de esa compra es relevante."""
    elegidos = set(usuarios)
    return [
        Caso(usuario, x, frozenset(productos - {x}))
        for (usuario, _), productos in sorted(cestas.items())
        if usuario in elegidos and len(productos) >= 2
        for x in sorted(productos)
    ]


def pliegues(usuarios: Iterable[int], k: int, semilla: int) -> List[List[int]]:
    mezclados = sorted(set(usuarios))
    random.Random(semilla).shuffle(mezclados)
    return [sorted(mezclados[i::k]) for i in range(k)]


def cocompra(producto_id: int, compras: Mapping[int, Set[int]], usuarios: Iterable[int],
             excluir: int | None = None, k: int = TOP_K) -> Scores:
    """Misma fórmula que recommender/copurchase.py: compradores de X que compraron Y / compradores de X."""
    compradores = [u for u in usuarios if u != excluir and producto_id in compras.get(u, set())]
    if not compradores:
        return []
    conteo: Dict[int, int] = {}
    for u in compradores:
        for p in compras[u]:
            if p != producto_id:
                conteo[p] = conteo.get(p, 0) + 1
    ordenados = sorted(conteo.items(), key=lambda item: (-item[1], item[0]))
    return [(p, c / len(compradores)) for p, c in ordenados[:k]]


def precision(casos: Sequence[Caso], fuentes_de: FuentesDe, pesos: Mapping[str, float]) -> float:
    if not casos:
        return 0.0
    aciertos = sum(len(c.relevantes.intersection(fusionar(c.producto, fuentes_de(c), pesos))) for c in casos)
    return aciertos / (TOP_K * len(casos))


def buscar_pesos(casos: Sequence[Caso], fuentes_de: FuentesDe,
                 fuentes: Sequence[str] = FUENTES, rejilla: Sequence[float] = REJILLA) -> Dict[str, float]:
    """Mayor Precision@10; a igualdad, lo más cercano a pesos iguales."""
    calculadas = {c: fuentes_de(c) for c in casos}
    mejor_clave, mejor = None, None
    for combinacion in itertools.product(rejilla, repeat=len(fuentes)):
        if not any(combinacion):
            continue
        pesos = dict(zip(fuentes, combinacion))
        clave = (precision(casos, calculadas.__getitem__, pesos), -sum(abs(w - 1) for w in combinacion))
        if mejor_clave is None or clave > mejor_clave:
            mejor_clave, mejor = clave, pesos
    return mejor


def evaluar(fijas: Mapping[int, Mapping[str, Scores]], compras: Mapping[int, Set[int]],
            cestas: Mapping[Tuple[int, str], Set[int]], *, k_pliegues: int = 5, semilla: int = 2026,
            rejilla: Sequence[float] = REJILLA) -> dict:
    usuarios = sorted(compras)
    iguales = {f: 1.0 for f in FUENTES}

    def fuentes_con(usuarios_cocompra: Sequence[int]) -> FuentesDe:
        # El usuario del caso nunca cuenta para su propia co-compra.
        return lambda c: {**fijas.get(c.producto, {}),
                          "cocompra": cocompra(c.producto, compras, usuarios_cocompra, excluir=c.usuario)}

    resultados = []
    for prueba in pliegues(usuarios, k_pliegues, semilla):
        entrenamiento = [u for u in usuarios if u not in set(prueba)]
        fuentes_de = fuentes_con(entrenamiento)
        casos_prueba = casos_de(cestas, prueba)
        pesos = buscar_pesos(casos_de(cestas, entrenamiento), fuentes_de, rejilla=rejilla)
        resultados.append({
            "usuarios": len(prueba),
            "casos": len(casos_prueba),
            "iguales": round(precision(casos_prueba, fuentes_de, iguales), 4),
            "aprendidos": round(precision(casos_prueba, fuentes_de, pesos), 4),
            "pesos": pesos,
        })

    todos = casos_de(cestas, usuarios)
    if not todos:
        raise SeedError("no hay compras con 2 o más productos para aprender")
    media = lambda clave: round(sum(r[clave] for r in resultados) / len(resultados), 4)
    return {
        "pesos": buscar_pesos(todos, fuentes_con(usuarios), rejilla=rejilla),
        "semilla": semilla,
        "usuarios": len(usuarios),
        "casos": len(todos),
        "precision_iguales": media("iguales"),
        "precision_aprendidos": media("aprendidos"),
        "pliegues": resultados,
    }


# --- Datos por la API (las mismas consultas que la ficha) --------------------

def _scores(filas: Iterable[dict], producto_id: int) -> Scores:
    return [(int(f["id"]), float(f["score"])) for f in filas if int(f["id"]) != producto_id][:TOP_K]


def fuente_texto(api: Api, producto_id: int, descripcion: str) -> Scores:
    if not descripcion.strip():
        return []
    texto = descripcion.strip().replace("'", "''")
    return _scores(api.sql(f"SELECT id, SCORE() AS score FROM productos WHERE MATCH(descripcion, '{texto}') "
                           f"USING BM25 ORDER BY score DESC LIMIT {TOP_K + 1}")["rows"], producto_id)


def fuente_visual(api: Api, producto_id: int, embedding: str) -> Scores:
    try:
        vector = [float(v) for v in json.loads(embedding)]
    except (TypeError, ValueError):
        return []
    if not vector:
        return []
    return _scores(api.sql(f"SELECT id, SIMILARITY_SCORE() AS score FROM productos "
                           f"WHERE SIMILAR_TO([{', '.join(map(repr, vector))}], k={TOP_K + 1}) "
                           f"USING IVF WITH METRIC=cosine ORDER BY score DESC")["rows"], producto_id)


def fuente_metadatos(api: Api, producto_id: int) -> Scores:
    cuerpo = api.get(f"/api/recommend/metadata/{producto_id}?k={TOP_K}")
    return [(int(r["producto_id"]), float(r["score"])) for r in cuerpo["recomendaciones"]]


def leer_compras(api: Api) -> Tuple[Dict[int, Set[int]], Dict[Tuple[int, str], Set[int]]]:
    compras: Dict[int, Set[int]] = {}
    cestas: Dict[Tuple[int, str], Set[int]] = {}
    for fila in api.sql("SELECT usuario_id, producto_id, fecha FROM compras")["rows"]:
        usuario, producto = int(fila["usuario_id"]), int(fila["producto_id"])
        compras.setdefault(usuario, set()).add(producto)
        cestas.setdefault((usuario, str(fila["fecha"])), set()).add(producto)
    return compras, cestas


def fuentes_fijas(api: Api) -> Dict[int, Dict[str, Scores]]:
    """Visual, texto y metadatos de cada producto (no dependen del historial)."""
    return {
        int(p["id"]): {
            "visual": fuente_visual(api, int(p["id"]), str(p.get("embedding") or "")),
            "texto": fuente_texto(api, int(p["id"]), str(p.get("descripcion") or "")),
            "metadatos": fuente_metadatos(api, int(p["id"])),
        }
        for p in api.sql("SELECT id, descripcion, embedding FROM productos")["rows"]
    }


# --- Programa ----------------------------------------------------------------

def escribir_ts(resultado: dict, destino: Path = SALIDA) -> None:
    evaluacion = {k: v for k, v in resultado.items() if k not in ("pesos", "pliegues")}
    destino.write_text(
        "// Generado por `python -m tools.aprender_pesos`. No editar a mano.\n"
        f"export const PESOS_APRENDIDOS: Record<string, number> = {json.dumps(resultado['pesos'])};\n\n"
        f"export const EVALUACION_PESOS = {json.dumps(evaluacion, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.aprender_pesos", description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("BD2_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--pliegues", type=int, default=5)
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--salida", type=Path, default=SALIDA)
    args = p.parse_args(argv)
    api = Api(args.api)
    try:
        esperar_api(api, 30)
        compras, cestas = leer_compras(api)
        if not compras:
            raise SeedError("la tabla compras está vacía")
        resultado = evaluar(fuentes_fijas(api), compras, cestas, k_pliegues=args.pliegues, semilla=args.semilla)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    escribir_ts(resultado, args.salida)
    for i, r in enumerate(resultado["pliegues"], 1):
        print(f"pliegue {i}: iguales {r['iguales']:.4f}  aprendidos {r['aprendidos']:.4f}  {r['pesos']}")
    print(f"Precision@10 media ({resultado['usuarios']} usuarios, {resultado['casos']} casos): "
          f"iguales {resultado['precision_iguales']:.4f} -> aprendidos {resultado['precision_aprendidos']:.4f}")
    print(f"pesos finales: {resultado['pesos']}")
    print(f"escrito {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
