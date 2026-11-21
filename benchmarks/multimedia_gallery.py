"""Galeria de casos de exito y error sobre el dataset sintetico (Parte 4).

Toma una imagen de consulta por familia, recupera las cinco mas parecidas por
similitud coseno y dibuja una fila por consulta. Un borde marca si el vecino
pertenece a la misma familia.

Requiere haber generado antes el dataset con ``benchmarks.multimedia_corpus``.
Lee ``vectors.jsonl``, que se escribe en streaming y por eso aguanta 100 000
objetos sin cargar el corpus completo en memoria de golpe.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

CORPUS = Path("data/multimedia/1000")
SALIDA = Path("benchmarks/results/multimedia/plots")
VECINOS = 5


def coseno(a, b) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return producto / (na * nb) if na and nb else 0.0


def espectrograma(ruta: str):
    """Espectrograma en dB de un WAV mono, para dibujar un audio como imagen."""
    import wave

    import numpy as np

    with wave.open(ruta, "rb") as wav:
        muestras = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(float)
    ventana, salto = 512, 128
    tramas = [muestras[i:i + ventana] * np.hanning(ventana)
              for i in range(0, len(muestras) - ventana, salto)]
    potencia = np.abs(np.fft.rfft(np.array(tramas), axis=1)) ** 2
    return 10 * np.log10(potencia.T + 1e-6)[::-1]


def leer_vectores(corpus: Path, modalidad: str = "image") -> list[dict]:
    archivo = corpus / "vectors.jsonl"
    if not archivo.exists():
        archivo = corpus / "vectors.json"
        if not archivo.exists():
            raise SystemExit(f"no hay vectores en {corpus}; corre benchmarks.multimedia_corpus primero")
        return json.loads(archivo.read_text(encoding="utf-8"))["objetos"]
    objetos = []
    with archivo.open(encoding="utf-8") as lineas:
        for linea in lineas:
            objeto = json.loads(linea)
            # Imagen y audio no se mezclan: cada modalidad tiene su propio vocabulario.
            if objeto.get("vector") and objeto.get("modalidad") == modalidad:
                objetos.append(objeto)
    return objetos


def main() -> None:
    ap = argparse.ArgumentParser(description="Galeria de aciertos y errores del pipeline multimedia")
    ap.add_argument("--corpus", default=str(CORPUS), help="directorio del corpus con vectors.jsonl")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--modalidad", choices=("image", "audio"), default="image")
    args = ap.parse_args()
    if args.salida is None:
        nombre = "galeria_multimedia.png" if args.modalidad == "image" else "galeria_audio.png"
        args.salida = str(SALIDA / nombre)

    corpus = Path(args.corpus)
    objetos = leer_vectores(corpus, args.modalidad)
    if not objetos:
        raise SystemExit("no hay vectores; corre benchmarks.multimedia_corpus primero")

    # vectors.jsonl guarda rutas relativas al corpus, para que el dataset se
    # pueda mover de maquina sin editar los metadatos.
    for objeto in objetos:
        ruta = Path(objeto["ruta"])
        objeto["ruta"] = str(ruta if ruta.is_absolute() else corpus / ruta)

    consultas = {}
    for objeto in objetos:
        consultas.setdefault(objeto["familia"], objeto)

    destino = Path(args.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
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

            if args.modalidad == "audio":
                eje.imshow(espectrograma(objeto["ruta"]), cmap="magma", aspect="auto")
            else:
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
    fig.savefig(destino, dpi=130)
    plt.close(fig)
    print(f"aciertos: {aciertos}/{total} ({aciertos / total:.3f})")
    print("figura:", destino)


if __name__ == "__main__":
    main()
