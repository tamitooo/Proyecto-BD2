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
ofrece con el botón "Usar pesos aprendidos". La comparación de cada fuente sola
contra la fusión (#141) queda en benchmarks/results/parte5/precision_fuentes.*
y p5_precision_por_fuente.png.

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
RESULTADOS = RAIZ / "benchmarks" / "results" / "parte5"
NOMBRES = {"visual": "Imagen similar", "texto": "Descripción similar",
           "cocompra": "Comprados juntos", "metadatos": "Misma categoría y precio"}
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


def preparar(producto_id: int, por_fuente: Mapping[str, Scores]) -> Dict[str, Scores]:
    """Quita a X y normaliza cada fuente; no depende de los pesos."""
    return {f: normalizar([(p, s) for p, s in lista if p != producto_id]) for f, lista in por_fuente.items()}


def fusionar_preparadas(preparadas: Mapping[str, Scores], pesos: Mapping[str, float],
                        k: int = TOP_K) -> List[int]:
    activas = [f for f in preparadas if pesos.get(f, 1) > 0]
    total = sum(pesos.get(f, 1) for f in activas)
    score: Dict[int, float] = {}
    aportes: Dict[int, int] = {}
    for fuente in activas:
        peso = pesos.get(fuente, 1) / total
        for p, s in preparadas[fuente]:
            score[p] = score.get(p, 0.0) + s * peso
            aportes[p] = aportes.get(p, 0) + 1
    return sorted(score, key=lambda p: (-score[p], -aportes[p], p))[:k]


def fusionar(producto_id: int, por_fuente: Mapping[str, Scores], pesos: Mapping[str, float],
             k: int = TOP_K) -> List[int]:
    return fusionar_preparadas(preparar(producto_id, por_fuente), pesos, k)


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


def _precision_preparada(casos: Sequence[Caso], preparadas: Mapping[Caso, Mapping[str, Scores]],
                         pesos: Mapping[str, float]) -> float:
    if not casos:
        return 0.0
    aciertos = sum(len(c.relevantes.intersection(fusionar_preparadas(preparadas[c], pesos))) for c in casos)
    return aciertos / (TOP_K * len(casos))


def precision(casos: Sequence[Caso], fuentes_de: FuentesDe, pesos: Mapping[str, float]) -> float:
    return _precision_preparada(casos, {c: preparar(c.producto, fuentes_de(c)) for c in casos}, pesos)


def techo(casos: Sequence[Caso]) -> float:
    """Precision@10 máxima: un caso con menos de 10 relevantes no puede llenar el top 10."""
    if not casos:
        return 0.0
    return sum(min(len(c.relevantes), TOP_K) for c in casos) / (TOP_K * len(casos))


def _proporcion(combinacion: Sequence[float]) -> Tuple[float, ...]:
    # Pesos proporcionales dan la misma fusión (se divide por la suma).
    total = sum(combinacion)
    return tuple(round(w / total, 9) for w in combinacion)


def buscar_pesos(casos: Sequence[Caso], fuentes_de: FuentesDe,
                 fuentes: Sequence[str] = FUENTES, rejilla: Sequence[float] = REJILLA) -> Dict[str, float]:
    """Mayor Precision@10; a igualdad, lo más cercano a pesos iguales."""
    preparadas = {c: preparar(c.producto, fuentes_de(c)) for c in casos}
    medidas: Dict[Tuple[float, ...], float] = {}
    mejor_clave, mejor = None, None
    for combinacion in itertools.product(rejilla, repeat=len(fuentes)):
        if not any(combinacion):
            continue
        pesos = dict(zip(fuentes, combinacion))
        forma = _proporcion(combinacion)
        if forma not in medidas:
            medidas[forma] = _precision_preparada(casos, preparadas, pesos)
        clave = (medidas[forma], -sum(abs(w - 1) for w in combinacion))
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
        preparadas = {c: preparar(c.producto, fuentes_de(c)) for c in casos_prueba}
        resultados.append({
            "usuarios": len(prueba),
            "casos": len(casos_prueba),
            "iguales": round(_precision_preparada(casos_prueba, preparadas, iguales), 4),
            "aprendidos": round(_precision_preparada(casos_prueba, preparadas, pesos), 4),
            "solas": {f: round(_precision_preparada(casos_prueba, preparadas,
                                                    {g: float(g == f) for g in FUENTES}), 4)
                      for f in FUENTES},
            "techo": round(techo(casos_prueba), 4),
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
        "precision_solas": {f: round(sum(r["solas"][f] for r in resultados) / len(resultados), 4)
                            for f in FUENTES},
        "techo": media("techo"),
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


def filas_resultado(resultado: dict) -> List[Tuple[str, float, List[float]]]:
    filas = [(NOMBRES[f], resultado["precision_solas"][f], [r["solas"][f] for r in resultado["pliegues"]])
             for f in FUENTES]
    filas.append(("Fusión, pesos iguales", resultado["precision_iguales"],
                  [r["iguales"] for r in resultado["pliegues"]]))
    filas.append(("Fusión, pesos aprendidos", resultado["precision_aprendidos"],
                  [r["aprendidos"] for r in resultado["pliegues"]]))
    return filas


def escribir_resultados(resultado: dict, carpeta: Path = RESULTADOS) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "precision_fuentes.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    filas = filas_resultado(resultado)
    n = len(resultado["pliegues"])
    with (carpeta / "precision_fuentes.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(["metodo", "precision_at_10"] + [f"pliegue_{i}" for i in range(1, n + 1)]) + "\n")
        for nombre, media, por_pliegue in filas:
            f.write(",".join([nombre, f"{media:.4f}"] + [f"{v:.4f}" for v in por_pliegue]) + "\n")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib no está instalado: no se generó el gráfico", file=sys.stderr)
        return
    nombres = [f[0] for f in filas][::-1]
    valores = [f[1] for f in filas][::-1]
    colores = ["#2a78d6" if n.startswith("Fusión") else "#86b6ef" for n in nombres]
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=200)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.barh(nombres, valores, color=colores, height=0.6, edgecolor="#fcfcfb", linewidth=2)
    tope = resultado["techo"]
    ax.axvline(tope, color="#52514e", linestyle="--", linewidth=1)
    ax.text(tope, len(nombres) - 0.45, f" máximo posible {tope:.3f}", color="#52514e",
            fontsize=8, va="bottom", ha="right")
    for y, v in enumerate(valores):
        ax.text(v + tope * 0.01, y, f"{v:.3f}", va="center", fontsize=8, color="#0b0b0b")
    ax.set_xlim(0, tope * 1.08)
    ax.set_xlabel(f"Precision@10 (media de {n} pliegues por usuarios)", fontsize=8, color="#52514e")
    ax.tick_params(labelsize=8, colors="#52514e", length=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.grid(axis="x", color="#e8e7e2", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(carpeta / "p5_precision_por_fuente.png", facecolor=fig.get_facecolor())
    plt.close(fig)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.aprender_pesos", description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("BD2_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--pliegues", type=int, default=5)
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--salida", type=Path, default=SALIDA)
    p.add_argument("--resultados", type=Path, default=RESULTADOS)
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
    escribir_resultados(resultado, args.resultados)
    for i, r in enumerate(resultado["pliegues"], 1):
        print(f"pliegue {i}: iguales {r['iguales']:.4f}  aprendidos {r['aprendidos']:.4f}  {r['pesos']}")
    print(f"Precision@10 media ({resultado['usuarios']} usuarios, {resultado['casos']} casos): "
          f"iguales {resultado['precision_iguales']:.4f} -> aprendidos {resultado['precision_aprendidos']:.4f}")
    for nombre, media, _ in filas_resultado(resultado):
        print(f"  {nombre:28s} {media:.4f}")
    print(f"  máximo posible               {resultado['techo']:.4f}")
    print(f"pesos finales: {resultado['pesos']}")
    print(f"escrito {args.salida} y {args.resultados}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
