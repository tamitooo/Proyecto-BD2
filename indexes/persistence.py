"""Persistencia atómica reutilizable para índices del minigestor."""
from __future__ import annotations
import os
import pickle
import time
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
    replace_with_retry(tmp, target)


def replace_with_retry(source, destination, attempts: int = 20) -> None:
    """``os.replace`` reintentando: en Windows/OneDrive el destino puede estar tomado un instante."""
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


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
