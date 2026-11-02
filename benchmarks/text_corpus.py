"""Corpus sintetico para los experimentos de la Parte 3.

Cada consulta tiene documentos escritos para contener todos sus terminos.
El resto de documentos son ruido sobre un vocabulario comun con frecuencia
tipo Zipf, mas algunas palabras de consulta inyectadas a tasa muy baja.
La relevancia queda asi definida por construccion: no hace falta juicio
humano para saber que documento responde a que consulta.
"""

from __future__ import annotations

import argparse
import json
import random
from bisect import bisect
from pathlib import Path

from benchmarks.text_queries import TERMINOS, construir_consultas

SEMILLA = 202602
DOCS_RESPUESTA = 10
LARGO_MIN = 45
LARGO_MAX = 75
PROB_VACIA = 0.22
PROB_RUIDO = 0.0002

VACIAS = "de la el que en y a los del se las por un para con no una su al lo".split()

PALABRAS = """
tiempo gente vida mundo casa ciudad pais trabajo escuela nino mujer hombre
agua tierra fuego aire camino puerta mesa libro papel mano ojo voz noche dia
anio semana hora lugar forma parte grupo caso punto idea fuerza luz color
sonido campo calle barrio pueblo familia amigo hijo padre madre hermano cuerpo
cabeza cara pie sangre salud dolor miedo amor risa juego fiesta musica baile
comida pan carne fruta leche vino cafe silla ventana techo piso pared jardin
arbol flor rio mar montana cielo sol luna estrella lluvia viento nieve piedra
arena metal madera vidrio tela cuero llave moneda billete carta firma numero
palabra frase historia cuento verso cancion nota ritmo acorde pausa silencio
""".split()


def _tabla_zipf(palabras: list[str], caida: float = 1.05):
    """Pesos acumulados para muestrear palabras con frecuencia decreciente."""
    acumulado: list[float] = []
    total = 0.0
    for posicion in range(len(palabras)):
        total += 1.0 / ((posicion + 1) ** caida)
        acumulado.append(total)
    return acumulado, total


def _elegir(rng: random.Random, palabras: list[str], acumulado: list[float], total: float) -> str:
    return palabras[bisect(acumulado, rng.random() * total)]


def posiciones_respuesta(n: int, consultas: list[dict], semilla: int = SEMILLA) -> dict[int, list[int]]:
    """Elige, por consulta, los documentos que responderan a ella."""
    rng = random.Random(semilla * 7919 + n)
    ocupados: set[int] = set()
    respuesta: dict[int, list[int]] = {}

    necesarios = len(consultas) * DOCS_RESPUESTA
    if n < necesarios:
        raise ValueError(f"se necesitan al menos {necesarios} documentos")

    for consulta in consultas:
        puestos: list[int] = []
        while len(puestos) < DOCS_RESPUESTA:
            posicion = rng.randrange(n)
            if posicion in ocupados:
                continue
            ocupados.add(posicion)
            puestos.append(posicion)
        respuesta[consulta["id"]] = sorted(puestos)

    return respuesta


def _documento(rng, palabras, acumulado, total, extra, ruido) -> str:
    # En un documento respuesta los terminos de la consulta se repiten, para
    # que el ranking tenga una senal y no dependa del azar del largo.
    texto = [termino for termino in extra for _ in range(rng.randint(2, 4))]

    if not extra:
        for termino in ruido:
            if rng.random() < PROB_RUIDO:
                texto.append(termino)

    largo = rng.randint(LARGO_MIN, LARGO_MAX)
    while len(texto) < largo:
        if rng.random() < PROB_VACIA:
            texto.append(rng.choice(VACIAS))
        else:
            texto.append(_elegir(rng, palabras, acumulado, total))

    rng.shuffle(texto)
    return " ".join(texto)


def escribir(n: int, destino, semilla: int = SEMILLA) -> dict:
    """Genera corpus.jsonl y queries.json para n documentos."""
    consultas = construir_consultas(semilla)
    respuesta = posiciones_respuesta(n, consultas, semilla)

    por_posicion: dict[int, list[str]] = {}
    for consulta in consultas:
        for posicion in respuesta[consulta["id"]]:
            por_posicion[posicion] = consulta["terminos"]

    carpeta = Path(destino)
    carpeta.mkdir(parents=True, exist_ok=True)
    corpus_path = carpeta / "corpus.jsonl"

    rng = random.Random(semilla + n)
    acumulado, total = _tabla_zipf(PALABRAS)
    with corpus_path.open("w", encoding="utf-8", newline="\n") as archivo:
        for posicion in range(n):
            extra = por_posicion.get(posicion, [])
            texto = _documento(rng, PALABRAS, acumulado, total, extra, TERMINOS)
            archivo.write(json.dumps({"id": posicion, "texto": texto}, ensure_ascii=False))
            archivo.write("\n")

    banco = []
    for consulta in consultas:
        banco.append({**consulta, "relevantes": respuesta[consulta["id"]]})

    queries_path = carpeta / "queries.json"
    contenido = {
        "semilla": semilla,
        "documentos": n,
        "docs_por_consulta": DOCS_RESPUESTA,
        "consultas": banco,
    }
    queries_path.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "corpus": corpus_path,
        "queries": queries_path,
        "documentos": n,
        "consultas": len(banco),
        "bytes": corpus_path.stat().st_size,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera el corpus sintetico de la Parte 3")
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--seed", type=int, default=SEMILLA)
    ap.add_argument("--out", default="data/text")
    args = ap.parse_args()

    for n in args.sizes:
        salida = escribir(n, Path(args.out) / str(n), args.seed)
        print(
            f"{n} documentos, {salida['consultas']} consultas, "
            f"{salida['bytes'] / 1048576:.2f} MB -> {salida['corpus']}"
        )


if __name__ == "__main__":
    main()
