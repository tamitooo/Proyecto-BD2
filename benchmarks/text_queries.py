"""Banco de consultas para los experimentos de la Parte 3.

Las consultas salen de una lista de terminos del curso y se agrupan por
cantidad de palabras: una, tres y cinco o mas, que es lo que pide el
enunciado. La semilla fija hace que el banco sea siempre el mismo.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEMILLA = 202602
POR_GRUPO = 12

TERMINOS = list(
    dict.fromkeys(
        """
algoritmo indice protocolo servidor cliente columna registro consulta
transaccion bloqueo arbol nodo pagina disco memoria vector matriz distancia
vecino centroide cluster ranking corpus termino frecuencia relevancia umbral
semilla particion bloque mezcla lista cola cubeta hash clave rango predicado
optimizador planificador ejecutor catalogo esquema tupla atributo indice
imagen audio pixel frame espectro mel cepstrum descriptor histograma
cuantizacion vecindad grafo capa salto poda aproximado exacto recall precision
latencia rendimiento heap secuencial ordenamiento agrupamiento join
""".split()
    )
)


def construir_consultas(semilla: int = SEMILLA, por_grupo: int = POR_GRUPO) -> list[dict]:
    """Devuelve el banco completo, ordenado de una a cinco palabras."""
    rng = random.Random(semilla)
    banco: list[dict] = []

    for grupo, base in (("una", 1), ("tres", 3), ("larga", 5)):
        for _ in range(por_grupo):
            cantidad = base if base < 5 else rng.randint(5, 7)
            terminos = rng.sample(TERMINOS, cantidad)
            banco.append(
                {
                    "id": len(banco) + 1,
                    "grupo": grupo,
                    "n_palabras": cantidad,
                    "terminos": terminos,
                    "texto": " ".join(terminos),
                }
            )

    return banco


def escribir_banco(ruta, semilla: int = SEMILLA) -> list[dict]:
    """Escribe el banco en JSON y devuelve las consultas."""
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    consultas = construir_consultas(semilla)
    contenido = {"semilla": semilla, "consultas": consultas}
    destino.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return consultas
