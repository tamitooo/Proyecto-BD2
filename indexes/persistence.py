"""Persistencia atómica reutilizable para índices del minigestor.

Los índices mantienen una representación en RAM para ejecutar el algoritmo, pero su
estado canónico se sincroniza a un archivo propio. Al reiniciar se recupera desde ese
archivo; no hace falta reconstruirlo escaneando la tabla base.
"""
from __future__ import annotations
import os
import pickle
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1


def atomic_pickle_write(path: str | os.PathLike[str], payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as fh:
        pickle.dump({"format": FORMAT_VERSION, "payload": payload}, fh, protocol=pickle.HIGHEST_PROTOCOL)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)


def pickle_read(path: str | os.PathLike[str]) -> Any:
    target = Path(path)
    with target.open("rb") as fh:
        wrapper = pickle.load(fh)
    if not isinstance(wrapper, dict) or wrapper.get("format") != FORMAT_VERSION:
        raise ValueError(f"formato de índice no soportado: {target}")
    return wrapper["payload"]


def remove_if_exists(path: str | os.PathLike[str] | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
