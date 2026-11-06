"""Banco de consultas de 1, 3 y 5+ palabras para la Parte 3 (semilla fija)."""

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
transaccion bloqueo nodo pagina disco memoria vector matriz distancia
vecino centroide cluster ranking corpus termino frecuencia relevancia umbral
semilla particion bloque mezcla lista cola cubeta hash clave rango predicado
optimizador planificador ejecutor catalogo esquema tupla atributo indice
imagen audio pixel frame espectro mel cepstrum descriptor histograma
cuantizacion vecindad grafo capa salto poda aproximado exacto recall precision
latencia rendimiento heap secuencial ordenamiento agrupamiento join
dominio integridad restriccion disparador vista secuencia cursor deadlock
commit rollback aislamiento serializacion checkpoint buffer cache sector
cabecera factor llenado division fusion rebalanceo altura raiz hoja
selectividad cardinalidad estimacion costo operador proyeccion filtro union
interseccion diferencia producto agregacion promedio conteo suma maximo
minimo muestreo sesgo aproximacion exactitud cobertura ruido margen corte
similitud peso norma normalizacion radio arista candidato exploracion
refinamiento metadato ponderacion tokenizador lematizacion sinopsis prefijo
sufijo entropia varianza covarianza gradiente iteracion convergencia
tolerancia iterador generador gestor almacen respaldo replica fragmento
instantanea auditoria bitacora trazabilidad
""".split()
    )
)


def construir_consultas(semilla: int = SEMILLA, por_grupo: int = POR_GRUPO) -> list[dict]:
    """Ninguna consulta comparte términos, para que la relevancia quede bien definida."""
    rng = random.Random(semilla)
    disponibles = list(TERMINOS)
    rng.shuffle(disponibles)
    banco: list[dict] = []
    siguiente = 0

    for grupo, base in (("una", 1), ("tres", 3), ("larga", 5)):
        for _ in range(por_grupo):
            cantidad = base if base < 5 else rng.randint(5, 7)
            if siguiente + cantidad > len(disponibles):
                raise ValueError("no hay suficientes terminos distintos para el banco")
            terminos = disponibles[siguiente:siguiente + cantidad]
            siguiente += cantidad
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
