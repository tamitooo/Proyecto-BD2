"""Galeria de casos de exito y error sobre el dataset sintetico (Parte 4).

Toma una imagen de consulta por familia, recupera las cinco mas parecidas por
similitud coseno y dibuja una fila por consulta. Un borde marca si el vecino
pertenece a la misma familia.

Requiere haber generado antes el dataset con ``benchmarks.multimedia_corpus``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

BASE = Path("data/multimedia")
SALIDA = Path("benchmarks/results/multimedia/plots")
VECINOS = 5


def coseno(a, b) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return producto / (na * nb) if na and nb else 0.0


def main() -> None:
    datos = json.loads((BASE / "vectors.json").read_text(encoding="utf-8"))["objetos"]
    objetos = [o for o in datos if o["vector"]]
    if not objetos:
        raise SystemExit("no hay vectores; corre benchmarks.multimedia_corpus primero")

    consultas = {}
    for objeto in objetos:
        consultas.setdefault(objeto["familia"], objeto)

    SALIDA.mkdir(parents=True, exist_ok=True)
    filas = list(consultas.items())
    fig, ejes = plt.subplots(len(filas), VECINOS + 1, figsize=(15, 2.0 * len(filas)))
    aciertos = 0
    total = 0

    for fila, (familia, consulta) in enumerate(filas):
        ranking = sorted(
            (o for o in objetos if o["clave"] != consulta["clave"]),
            key=lambda o: -coseno(consulta["vector"], o["vector"]),
        )[:VECINOS]

        for columna, eje in enumerate(ejes[fila]):
            if columna == 0:
                objeto, titulo, borde = consulta, f"consulta: {familia}", "#333333"
            else:
                objeto = ranking[columna - 1]
                puntaje = coseno(consulta["vector"], objeto["vector"])
                acierto = objeto["familia"] == familia
                aciertos += acierto
                total += 1
                marca = "acierto" if acierto else "error"
                titulo = f"{objeto['familia']} {puntaje:.2f} {marca}"
                borde = "#2e7d32" if acierto else "#c62828"

            eje.imshow(mpimg.imread(objeto["ruta"]), cmap="gray")
            eje.set_xticks([])
            eje.set_yticks([])
            eje.set_title(titulo, fontsize=8)
            for lado in eje.spines.values():
                lado.set_edgecolor(borde)
                lado.set_linewidth(2.5)

    fig.suptitle(
        f"Recuperacion por similitud: consulta y cinco vecinos mas cercanos ({aciertos}/{total} aciertos)",
        fontsize=11,
    )
    fig.tight_layout()
    destino = SALIDA / "galeria_multimedia.png"
    fig.savefig(destino, dpi=130)
    plt.close(fig)
    print(f"aciertos: {aciertos}/{total} ({aciertos / total:.3f})")
    print("figura:", destino)


if __name__ == "__main__":
    main()
