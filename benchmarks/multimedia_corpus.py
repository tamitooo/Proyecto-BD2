"""Dataset sintetico de imagenes y audios para la Parte 4.

Genera objetos por familia, entrena el pipeline de ``multimedia`` (SIFT/MFCC,
K-Means, histogramas, TF-IDF) y guarda un vector por objeto. La familia es la
etiqueta de similitud: dos objetos de la misma familia deberian acercarse en el
espacio vectorial.

Los archivos se generan localmente con semilla fija y no se versionan.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
import wave
from pathlib import Path

import cv2
import numpy as np

from benchmarks.common import write_rows
from multimedia import MultimediaFeaturePipeline, MultimediaObject

LADO = 160
FRECUENCIA = 22050
DURACION = 1.0
FAMILIAS_IMAGEN = ("circulos", "franjas", "bloques", "ruido", "damero", "elipses", "cruces", "anillos")
FAMILIAS_AUDIO = ("tono_bajo", "tono_alto", "barrido", "ruido", "cuadrada", "dos_tonos")


def _imagen(familia: str, rng: np.random.Generator) -> np.ndarray:
    lienzo = np.full((LADO, LADO), 30, dtype=np.uint8)
    if familia == "circulos":
        for _ in range(6):
            cv2.circle(lienzo, (int(rng.integers(20, 140)), int(rng.integers(20, 140))),
                       int(rng.integers(8, 26)), int(rng.integers(120, 256)), -1)
    elif familia == "franjas":
        paso = int(rng.integers(6, 16))
        for x in range(0, LADO, paso * 2):
            cv2.rectangle(lienzo, (x, 0), (x + paso, LADO), int(rng.integers(140, 256)), -1)
    elif familia == "bloques":
        for _ in range(7):
            x, y = int(rng.integers(0, 120)), int(rng.integers(0, 120))
            ancho, alto = int(rng.integers(20, 60)), int(rng.integers(20, 60))
            cv2.rectangle(lienzo, (x, y), (x + ancho, y + alto),
                          int(rng.integers(120, 256)), -1)
    elif familia == "ruido":
        lienzo = rng.integers(0, 256, (LADO, LADO), dtype=np.uint8)
        lienzo = cv2.GaussianBlur(lienzo, (5, 5), 0)
    elif familia == "damero":
        celda = int(rng.integers(10, 30))
        for y in range(0, LADO, celda):
            for x in range(0, LADO, celda):
                if ((x // celda) + (y // celda)) % 2 == 0:
                    cv2.rectangle(lienzo, (x, y), (x + celda, y + celda), 220, -1)
    elif familia == "elipses":
        for _ in range(5):
            cv2.ellipse(lienzo, (int(rng.integers(30, 130)), int(rng.integers(30, 130))),
                        (int(rng.integers(10, 40)), int(rng.integers(6, 20))),
                        float(rng.integers(0, 180)), 0, 360, int(rng.integers(140, 256)), 2)
    elif familia == "cruces":
        for _ in range(6):
            x, y = int(rng.integers(20, 140)), int(rng.integers(20, 140))
            color = int(rng.integers(130, 256))
            cv2.line(lienzo, (x - 12, y), (x + 12, y), color, 3)
            cv2.line(lienzo, (x, y - 12), (x, y + 12), color, 3)
    else:
        for _ in range(4):
            cv2.circle(lienzo, (LADO // 2, LADO // 2), int(rng.integers(20, 70)),
                       int(rng.integers(120, 256)), int(rng.integers(2, 6)))

    # Estructura comun a todas las familias: sin esquinas o manchas, SIFT no
    # encuentra puntos en las imagenes lisas y el vector sale todo cero.
    # El contraste se lleva a los extremos para que funcione sobre degradados.
    for _ in range(6):
        cv2.circle(lienzo, (int(rng.integers(18, LADO - 18)), int(rng.integers(18, LADO - 18))),
                   int(rng.integers(4, 11)), 255 if rng.random() < 0.5 else 0, -1)
    return lienzo


def _audio(familia: str, rng: np.random.Generator) -> np.ndarray:
    t = np.linspace(0.0, DURACION, int(FRECUENCIA * DURACION), endpoint=False)
    if familia == "tono_bajo":
        onda = np.sin(2 * np.pi * rng.uniform(180, 320) * t)
    elif familia == "tono_alto":
        onda = np.sin(2 * np.pi * rng.uniform(900, 1400) * t)
    elif familia == "barrido":
        inicio, fin = rng.uniform(200, 400), rng.uniform(1200, 1800)
        fase = 2 * np.pi * (inicio * t + (fin - inicio) * t ** 2 / (2 * DURACION))
        onda = np.sin(fase)
    elif familia == "ruido":
        onda = rng.normal(0, 0.3, t.size)
    elif familia == "cuadrada":
        onda = np.sign(np.sin(2 * np.pi * rng.uniform(200, 500) * t))
    else:
        onda = 0.6 * np.sin(2 * np.pi * rng.uniform(300, 400) * t) + \
               0.4 * np.sin(2 * np.pi * rng.uniform(800, 1000) * t)
    return (onda * 0.4).astype(np.float32)


def _guardar_wav(ruta: Path, onda: np.ndarray, frecuencia: int = FRECUENCIA) -> None:
    """Escribe un WAV mono de 16 bits sin depender de soundfile."""
    muestras = np.clip(onda, -1.0, 1.0)
    enteros = (muestras * 32767).astype("<i2")
    with wave.open(str(ruta), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(frecuencia)
        archivo.writeframes(enteros.tobytes())


def generar(cantidad: int, familias, semilla: int, carpeta: Path, prefijo: str) -> list[dict]:
    carpeta.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(semilla)
    objetos = []
    for indice in range(cantidad):
        familia = familias[indice % len(familias)]
        if prefijo == "img":
            ruta = carpeta / f"{prefijo}_{indice:05d}_{familia}.png"
            cv2.imwrite(str(ruta), _imagen(familia, rng))
        else:
            ruta = carpeta / f"{prefijo}_{indice:05d}_{familia}.wav"
            _guardar_wav(ruta, _audio(familia, rng))
        objetos.append({"id": indice, "familia": familia, "ruta": str(ruta)})
    return objetos


def main() -> None:
    ap = argparse.ArgumentParser(description="Dataset sintetico de la Parte 4")
    ap.add_argument("--images", type=int, default=1000)
    ap.add_argument("--audios", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/multimedia")
    args = ap.parse_args()

    base = Path(args.out)
    imagenes = generar(args.images, FAMILIAS_IMAGEN, args.seed, base / "images", "img")
    audios = generar(args.audios, FAMILIAS_AUDIO, args.seed + 1, base / "audio", "aud")

    objetos = [MultimediaObject("image", item["ruta"]) for item in imagenes]
    audio_disponible = importlib.util.find_spec("librosa") is not None
    if audio_disponible:
        objetos += [MultimediaObject("audio", item["ruta"], sample_rate=FRECUENCIA) for item in audios]

    inicio = time.perf_counter()
    pipeline = MultimediaFeaturePipeline(random_state=args.seed)
    pipeline.fit(objetos)
    entrenamiento = time.perf_counter() - inicio

    filas = []
    vectores = []
    inicio = time.perf_counter()

    for indice, meta in enumerate(imagenes):
        objeto = objetos[indice]
        momento = time.perf_counter()
        vector = pipeline.extract_features(objeto)
        filas.append({"id": meta["id"], "modalidad": "image", "familia": meta["familia"],
                      "ms": round((time.perf_counter() - momento) * 1000, 3),
                      "dimension": int(vector.size)})
        vectores.append({"clave": f"img:{meta['id']}", "id": meta["id"], "modalidad": "image",
                         "familia": meta["familia"], "ruta": meta["ruta"],
                         "vector": [round(float(valor), 6) for valor in vector]})

    for meta in audios:
        if not audio_disponible:
            vectores.append({"clave": f"aud:{meta['id']}", "id": meta["id"], "modalidad": "audio",
                             "familia": meta["familia"], "ruta": meta["ruta"], "vector": None,
                             "nota": "MFCC requiere librosa, no instalado"})
            continue
        objeto = MultimediaObject("audio", meta["ruta"], sample_rate=FRECUENCIA)
        momento = time.perf_counter()
        vector = pipeline.extract_features(objeto)
        filas.append({"id": meta["id"], "modalidad": "audio", "familia": meta["familia"],
                      "ms": round((time.perf_counter() - momento) * 1000, 3),
                      "dimension": int(vector.size)})
        vectores.append({"clave": f"aud:{meta['id']}", "id": meta["id"], "modalidad": "audio",
                         "familia": meta["familia"], "ruta": meta["ruta"],
                         "vector": [round(float(valor), 6) for valor in vector]})

    extraccion = time.perf_counter() - inicio

    (base / "vectors.json").write_text(
        json.dumps({"semilla": args.seed, "objetos": vectores}, ensure_ascii=False),
        encoding="utf-8",
    )
    pipeline.save(base / "pipeline.npz")
    write_rows(
        filas,
        base / "extraccion.csv",
        base / "extraccion.json",
        {
            "semilla": args.seed,
            "imagenes": args.images,
            "audios": args.audios,
            "entrenamiento_s": round(entrenamiento, 2),
            "extraccion_s": round(extraccion, 2),
        },
    )

    print(f"imagenes: {args.images} | audios: {args.audios}")
    print(f"entrenamiento: {entrenamiento:.1f} s")
    print(f"extraccion: {extraccion:.1f} s ({extraccion / len(filas) * 1000:.1f} ms por objeto)")
    print("dimension del vector:", filas[0]["dimension"])
    print("salida:", base)


if __name__ == "__main__":
    main()
