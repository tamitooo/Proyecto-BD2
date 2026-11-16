"""Dataset sintetico de imagenes y audios para la Parte 4 (#92).

Genera objetos por familia, entrena el pipeline de ``multimedia`` (SIFT/MFCC,
K-Means, histogramas, TF-IDF) sobre una muestra del corpus, extrae un vector por
objeto y mide la calidad del espacio vectorial. La familia generada funciona
como etiqueta de relevancia.

Escala a 10 000 y 100 000 objetos sin cambiar el contrato:

* un directorio por tamano (``<out>/<n>``) en vez de uno solo;
* semilla por objeto, asi que reanudar no altera el contenido ni el orden;
* el vocabulario y el IDF se entrenan con una muestra declarada;
* los vectores se escriben en streaming (JSONL), no en un unico JSON en memoria;
* las metricas de calidad se calculan en la misma corrida.

Los archivos se generan localmente y no se versionan. Lo que si se versiona es
el resumen por tamano en ``benchmarks/results/multimedia/``.

Uso:
    python -m benchmarks.multimedia_corpus --sizes 1000 10000 100000
    python -m benchmarks.multimedia_corpus --sizes 100000 --reanudar
    python -m benchmarks.multimedia_corpus --sizes 1000 --solo-metricas
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

from multimedia import MultimediaFeaturePipeline, MultimediaObject

LADO = 160
FRECUENCIA = 22050
DURACION = 1.0
FAMILIAS_IMAGEN = ("circulos", "franjas", "bloques", "ruido", "damero", "elipses", "cruces", "anillos")
FAMILIAS_AUDIO = ("tono_bajo", "tono_alto", "barrido", "ruido", "cuadrada", "dos_tonos")
VECINOS = 10


# --------------------------------------------------------------------------
# Generacion
# --------------------------------------------------------------------------


def _rng(semilla: int, modalidad: str, indice: int) -> np.random.Generator:
    """Semilla independiente por objeto: reanudar o paralelizar no cambia el dato."""
    return np.random.default_rng([semilla, 0 if modalidad == "image" else 1, indice])


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


def generar(cantidad: int, familias, semilla: int, carpeta: Path, prefijo: str,
            reanudar: bool = False) -> list[dict]:
    """Crea ``cantidad`` objetos; con ``reanudar`` no reescribe los que ya existen."""
    carpeta.mkdir(parents=True, exist_ok=True)
    extension = ".png" if prefijo == "img" else ".wav"
    escritos = 0
    objetos = []
    for indice in range(cantidad):
        familia = familias[indice % len(familias)]
        ruta = carpeta / f"{prefijo}_{indice:06d}_{familia}{extension}"
        if not (reanudar and ruta.exists()):
            rng = _rng(semilla, "image" if prefijo == "img" else "audio", indice)
            # Escritura atomica: si el proceso muere a mitad, no queda un archivo
            # truncado que luego se salte por existir y rompa la extraccion.
            temporal = ruta.with_name(ruta.stem + ".tmp" + ruta.suffix)
            if prefijo == "img":
                cv2.imwrite(str(temporal), _imagen(familia, rng))
            else:
                _guardar_wav(temporal, _audio(familia, rng))
            temporal.replace(ruta)
            escritos += 1
        objetos.append({"id": indice, "familia": familia, "ruta": str(ruta)})
    objetos[0]["_escritos"] = escritos
    return objetos


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------


def _muestra(cantidad: int, limite: int) -> np.ndarray:
    """Indices equiespaciados: cubren todas las familias aunque haya 100 000 objetos."""
    if limite <= 0 or limite >= cantidad:
        return np.arange(cantidad)
    return np.unique(np.linspace(0, cantidad - 1, limite).astype(np.int64))


def _disco_bytes(carpeta: Path) -> int:
    return sum(archivo.stat().st_size for archivo in carpeta.iterdir() if archivo.is_file())


def _calidad(matriz: np.ndarray, etiquetas: np.ndarray, consultas: int, pares: int) -> dict:
    """Coseno intra/inter familia y Precision@10 sobre una sola modalidad.

    No se mezclan imagen y audio: cada modalidad tiene su propio codebook, asi
    que sus vectores viven en espacios distintos y un coseno cruzado no
    significa nada.
    """
    n = len(etiquetas)
    if n < 2:
        return {"vectores": n}
    normas = np.linalg.norm(matriz, axis=1)
    unitaria = matriz / np.where(normas == 0, 1.0, normas)[:, None]

    rng = np.random.default_rng(0)
    a = rng.integers(0, n, pares)
    b = rng.integers(0, n, pares)
    coseno = np.einsum("ij,ij->i", unitaria[a], unitaria[b])
    misma = etiquetas[a] == etiquetas[b]

    k = min(VECINOS, n - 1)
    elegidas = rng.choice(n, size=min(consultas, n), replace=False)
    similitud = unitaria @ unitaria[elegidas].T
    candidatos = np.argpartition(-similitud, k, axis=0)[: k + 1]
    aciertos = 0
    for columna, consulta in enumerate(elegidas):
        orden = candidatos[:, columna][np.argsort(-similitud[candidatos[:, columna], columna])]
        vecinos = [indice for indice in orden if indice != consulta][:k]
        aciertos += int((etiquetas[vecinos] == etiquetas[consulta]).sum())

    return {
        "vectores": n,
        "coseno_misma_familia": round(float(coseno[misma].mean()), 4) if misma.any() else None,
        "coseno_distinta_familia": round(float(coseno[~misma].mean()), 4) if (~misma).any() else None,
        "precision_at_10": round(aciertos / (len(elegidas) * k), 4),
        "consultas_p10": int(len(elegidas)),
        "pares_coseno": int(pares),
    }


def metricas(vectores: Path, consultas: int = 200, pares: int = 20000) -> dict:
    """Metricas por modalidad; cada una se evalua contra su propio espacio."""
    filas: dict[str, list] = {"image": [], "audio": []}
    familias: dict[str, list] = {"image": [], "audio": []}
    with vectores.open(encoding="utf-8") as archivo:
        for linea in archivo:
            objeto = json.loads(linea)
            if not objeto.get("vector"):
                continue
            filas[objeto["modalidad"]].append(objeto["vector"])
            familias[objeto["modalidad"]].append(objeto["familia"])

    resumen: dict = {"dimension": 0, "vectores": 0, "vectores_cero": 0, "por_modalidad": {}}
    for modalidad in ("image", "audio"):
        if not filas[modalidad]:
            continue
        matriz = np.asarray(filas[modalidad], dtype=np.float32)
        etiquetas = np.asarray(familias[modalidad])
        resumen["por_modalidad"][modalidad] = _calidad(matriz, etiquetas, consultas, pares)
        resumen["vectores"] += len(etiquetas)
        resumen["vectores_cero"] += int((np.linalg.norm(matriz, axis=1) == 0).sum())
        resumen["dimension"] = int(matriz.shape[1])
    return resumen


# --------------------------------------------------------------------------
# Corrida
# --------------------------------------------------------------------------


def _entrenar(pipeline: MultimediaFeaturePipeline, imagenes: list[dict], audios: list[dict],
              disponible: bool, muestra: int) -> tuple[float, int]:
    objetos = [MultimediaObject("image", item["ruta"]) for item in
               (imagenes[i] for i in _muestra(len(imagenes), muestra))]
    if disponible:
        # Sin sample_rate: con un archivo como fuente, mfcc.py exige la tasa del
        # propio WAV (22050 Hz) y rechaza un override.
        objetos += [MultimediaObject("audio", item["ruta"]) for item in
                    (audios[i] for i in _muestra(len(audios), muestra))]
    inicio = time.perf_counter()
    pipeline.fit(objetos)
    return time.perf_counter() - inicio, len(objetos)


def _ruta_publica(ruta: str, base: Path) -> str:
    """Ruta relativa al corpus: el JSONL se puede mover de maquina sin romperse."""
    camino = Path(ruta)
    try:
        return camino.relative_to(base).as_posix()
    except ValueError:
        return camino.as_posix()


def _extraer(pipeline: MultimediaFeaturePipeline, items: list[dict], modalidad: str,
             salida, filas: list[dict], base: Path, disponible: bool = True) -> float:
    inicio = time.perf_counter()
    for meta in items:
        if modalidad == "audio" and not disponible:
            filas.append({"id": meta["id"], "modalidad": modality_label(modalidad),
                          "familia": meta["familia"], "ms": None, "dimension": 0})
            salida.write(json.dumps({"clave": f"aud:{meta['id']}", "id": meta["id"],
                                     "modalidad": "audio", "familia": meta["familia"],
                                     "ruta": _ruta_publica(meta["ruta"], base), "vector": None,
                                     "nota": "MFCC requiere librosa, no instalado"},
                                    ensure_ascii=False) + "\n")
            continue
        objeto = MultimediaObject(modalidad, meta["ruta"])
        momento = time.perf_counter()
        vector = pipeline.extract_features(objeto)
        filas.append({"id": meta["id"], "modalidad": modality_label(modalidad),
                      "familia": meta["familia"],
                      "ms": round((time.perf_counter() - momento) * 1000, 3),
                      "dimension": int(vector.size)})
        salida.write(json.dumps({"clave": f"{'img' if modalidad == 'image' else 'aud'}:{meta['id']}",
                                 "id": meta["id"], "modalidad": modalidad,
                                 "familia": meta["familia"],
                                 "ruta": _ruta_publica(meta["ruta"], base),
                                 "vector": [round(float(v), 6) for v in vector]},
                                ensure_ascii=False) + "\n")
    return time.perf_counter() - inicio


def modality_label(modalidad: str) -> str:
    return "image" if modalidad == "image" else "audio"


def procesar(tamano: int, args, disponible: bool) -> dict:
    base = Path(args.out) / str(tamano)
    base.mkdir(parents=True, exist_ok=True)
    imagenes_ruta = base / "images"
    audios_ruta = base / "audio"

    inicio = time.perf_counter()
    imagenes = generar(tamano, FAMILIAS_IMAGEN, args.seed, imagenes_ruta, "img", args.reanudar)
    audios = generar(tamano, FAMILIAS_AUDIO, args.seed + 1, audios_ruta, "aud", args.reanudar)
    generacion = time.perf_counter() - inicio
    escritos = imagenes[0].pop("_escritos", 0) + audios[0].pop("_escritos", 0)

    pipeline = MultimediaFeaturePipeline(random_state=args.seed)
    entrenamiento, muestras = _entrenar(pipeline, imagenes, audios, disponible, args.train_sample)

    vectores = base / "vectors.jsonl"
    filas: list[dict] = []
    with vectores.open("w", encoding="utf-8") as salida:
        extraccion = _extraer(pipeline, imagenes, "image", salida, filas)
        extraccion += _extraer(pipeline, audios, "audio", salida, filas, disponible)

    modelo = base / "pipeline.npz"
    if modelo.exists():
        modelo.unlink()
    pipeline.save(modelo)
    _escribir_csv(filas, base / "extraccion.csv")

    resumen = {
        "tamano": tamano,
        "semilla": args.seed,
        "imagenes": tamano,
        "audios": tamano,
        "archivos_escritos": escritos,
        "generacion_s": round(generacion, 1),
        "entrenamiento_s": round(entrenamiento, 1),
        "objetos_entrenamiento": muestras,
        "extraccion_s": round(extraccion, 1),
        "disco_mb": round((_disco_bytes(imagenes_ruta) + _disco_bytes(audios_ruta)) / 1e6, 1),
        "audio_con_vector": disponible,
    }
    tiempos = {}
    for modalidad in ("image", "audio"):
        valores = [fila["ms"] for fila in filas
                   if fila["ms"] is not None and fila["modalidad"] == modalidad]
        if valores:
            tiempos[modalidad] = {"p50": round(float(np.percentile(valores, 50)), 1),
                                  "p95": round(float(np.percentile(valores, 95)), 1)}
    resumen["ms_por_objeto"] = tiempos
    resumen.update(metricas(vectores, consultas=args.consultas))
    return resumen


def _escribir_csv(filas: list[dict], destino: Path) -> None:
    import csv
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=["id", "modalidad", "familia", "ms", "dimension"])
        escritor.writeheader()
        escritor.writerows(filas)


def _ms_por_objeto(origen: Path) -> dict:
    """Percentiles de ms por objeto leidos del CSV de la corrida original."""
    import csv
    if not origen.exists():
        return {}
    tiempos: dict[str, list[float]] = {"image": [], "audio": []}
    with origen.open(encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            if fila["ms"]:
                tiempos[fila["modalidad"]].append(float(fila["ms"]))
    return {modalidad: {"p50": round(float(np.percentile(valores, 50)), 1),
                        "p95": round(float(np.percentile(valores, 95)), 1)}
            for modalidad, valores in tiempos.items() if valores}


def main() -> int:
    ap = argparse.ArgumentParser(description="Dataset sintetico de la Parte 4 (#92)")
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000],
                    help="tamanos a generar (por defecto 1000)")
    ap.add_argument("--images", type=int, default=None, help="atajo: un solo tamano de imagenes")
    ap.add_argument("--audios", type=int, default=None, help="atajo: un solo tamano de audios")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/multimedia", help="raiz de los corpus")
    ap.add_argument("--results", default="benchmarks/results/multimedia")
    ap.add_argument("--train-sample", type=int, default=2000,
                    help="objetos por modalidad para entrenar el vocabulario (0 = todos)")
    ap.add_argument("--consultas", type=int, default=200, help="consultas para Precision@10")
    ap.add_argument("--reanudar", action="store_true",
                    help="no reescribe archivos que ya existen")
    ap.add_argument("--solo-metricas", action="store_true",
                    help="recalcula las metricas de corpus ya generados")
    ap.add_argument("--sin-audio", action="store_true",
                    help="genera los WAV pero no extrae sus vectores")
    args = ap.parse_args()

    if args.images is not None or args.audios is not None:
        elegido = args.images or args.audios
        args.sizes = [elegido]

    disponible = importlib.util.find_spec("librosa") is not None
    if not disponible:
        print("aviso: librosa no instalado; los audios se generan pero sin vector")
    elif args.sin_audio:
        print("aviso: --sin-audio; los audios se generan pero sin vector")
        disponible = False

    resultados = []
    for tamano in args.sizes:
        print(f"\n== {tamano} objetos ==")
        base = Path(args.out) / str(tamano)
        destino = Path(args.results) / f"extraccion_{tamano}.json"
        if args.solo_metricas:
            # Conserva tiempos y disco de la corrida original; solo recalcula la
            # calidad del espacio vectorial.
            resumen = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {
                "tamano": tamano, "semilla": args.seed, "imagenes": tamano, "audios": tamano}
            resumen["disco_mb"] = round((_disco_bytes(base / "images")
                                         + _disco_bytes(base / "audio")) / 1e6, 1)
            resumen["ms_por_objeto"] = _ms_por_objeto(base / "extraccion.csv")
            for clave in ("ms_p50", "ms_p95", "coseno_misma_familia",
                          "coseno_distinta_familia", "precision_at_10",
                          "consultas_p10", "pares_coseno"):
                resumen.pop(clave, None)
            resumen.update(metricas(base / "vectors.jsonl", consultas=args.consultas))
        else:
            resumen = procesar(tamano, args, disponible)
        resultados.append(resumen)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(resumen, ensure_ascii=False, indent=2))
        print("resumen:", destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
