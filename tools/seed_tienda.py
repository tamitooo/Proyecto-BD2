"""Carga los datos de la tienda (Parte 5) en el motor a través de la API REST.

    python -m tools.seed_tienda [--api URL] [--datos CARPETA] [--data-dir CARPETA]

Pasos, todos repetibles sin duplicar nada:

1. Espera a que ``/api/health`` responda.
2. Copia el vocabulario BoVW a ``<data-dir>/models`` y las imágenes a
   ``<data-dir>/media`` (la carpeta de datos del backend; en Docker es el
   volumen compartido). Si ya hay un vocabulario distinto, se detiene: el
   backend usa uno solo y cambiarlo invalida los vectores de otras tablas.
3. Importa ``tiendas``, ``stock`` y ``compras`` desde sus CSV.
4. Crea ``productos`` con una columna ``embedding`` e inserta cada producto con
   ``EXTRACT_FEATURES(imagen)``; si se cortó a la mitad, inserta solo los que faltan.
5. Crea el R-Tree de ``tiendas (lat, lon)`` y el IVF de ``productos (embedding)``.

Solo usa la librería estándar, para poder correrlo fuera del backend.
"""

from __future__ import annotations

import argparse
import csv
import filecmp
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS_MUESTRA = RAIZ / "examples" / "tienda"
TABLAS_CSV = ("tiendas", "stock", "compras")
MODELO = "bow_image.npz"
INDICES = (
    ("tiendas", "idx_tiendas_ubicacion", "CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE"),
    ("productos", "idx_productos_embedding",
     "CREATE INDEX idx_productos_embedding ON productos (embedding) USING IVF WITH METRIC=cosine"),
)


class SeedError(Exception):
    pass


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                 timeout: float = 600):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw.decode("utf-8", "replace")

    def _ok(self, status, payload, que: str):
        if status >= 400:
            detalle = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise SeedError(f"{que}: HTTP {status}: {detalle}")
        return payload

    def get(self, path: str, timeout: float = 600):
        return self._ok(*self._request("GET", path, timeout=timeout), f"GET {path}")

    def post_json(self, path: str, data: dict):
        body = json.dumps(data).encode("utf-8")
        return self._ok(*self._request("POST", path, body, {"Content-Type": "application/json"}), f"POST {path}")

    def post_form(self, path: str, campos: dict, archivo: tuple[str, bytes]):
        limite = uuid.uuid4().hex
        partes = []
        for nombre, valor in campos.items():
            partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n{valor}\r\n'.encode())
        nombre_archivo, contenido = archivo
        partes.append(
            f'--{limite}\r\nContent-Disposition: form-data; name="file"; filename="{nombre_archivo}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode() + contenido + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={limite}"}
        return self._ok(*self._request("POST", path, b"".join(partes), headers), f"POST {path}")

    def sql(self, sentencia: str):
        resultado = self.post_json("/api/query", {"sql": sentencia})
        if not resultado.get("success"):
            raise SeedError(f"{sentencia[:80]}...: {resultado.get('error')}")
        return resultado


def esperar_api(api: Api, segundos: float) -> None:
    limite = time.monotonic() + segundos
    while True:
        restante = limite - time.monotonic()
        try:
            api.get("/api/health", timeout=max(0.5, min(5.0, restante)))
            return
        except (SeedError, OSError) as exc:
            if time.monotonic() >= limite:
                raise SeedError(f"la API no respondió en {segundos:.0f} s: {exc}") from None
            time.sleep(1)


def copiar_archivos(datos: Path, data_dir: Path, reemplazar_modelo: bool) -> None:
    origen = datos / "modelo" / MODELO
    destino = data_dir / "models" / MODELO
    if destino.exists() and not filecmp.cmp(origen, destino, shallow=False) and not reemplazar_modelo:
        raise SeedError(
            f"ya hay otro vocabulario en {destino}. El backend usa uno solo y las tablas con vectores "
            "calculados con el anterior quedarían mal. Usa --reemplazar-modelo si igual quieres cambiarlo.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)
    media = data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)
    for imagen in sorted((datos / "imagenes").iterdir()):
        objetivo = media / imagen.name
        if not objetivo.exists() or not filecmp.cmp(imagen, objetivo, shallow=False):
            shutil.copyfile(imagen, objetivo)


def _tablas(api: Api) -> dict[str, dict]:
    return {t["name"]: t for t in api.get("/api/tables")}


def importar_csv(api: Api, datos: Path, existentes: dict) -> None:
    for tabla in TABLAS_CSV:
        if tabla in existentes:
            print(f"{tabla}: ya existe, se omite")
            continue
        r = api.post_form("/api/tables/import", {"name": tabla, "primary_key": "id", "storage_kind": "heap"},
                          (f"{tabla}.csv", (datos / f"{tabla}.csv").read_bytes()))
        print(f"{tabla}: {r.get('imported_rows')} filas")


def _bytes_max(filas: list[dict], columna: str) -> int:
    return max(len(f[columna].encode("utf-8")) for f in filas)


def _texto(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def cargar_productos(api: Api, datos: Path, existentes: dict) -> None:
    with open(datos / "productos.csv", encoding="utf-8", newline="") as f:
        productos = list(csv.DictReader(f))
    if "productos" not in existentes:
        primera = productos[0]["imagen"]
        vector = api.post_form("/api/media/extract", {"kind": "image"},
                               (primera, (datos / "imagenes" / primera).read_bytes()))
        # Cada valor del JSON ocupa a lo sumo 9 bytes ("0.123456,").
        largo_embedding = 9 * int(vector["dimension"]) + 16
        columnas = [("id", "INT"), ("nombre", None), ("categoria", None), ("precio", "FLOAT"),
                    ("descripcion", None), ("imagen", None), ("embedding", f"VARCHAR({largo_embedding})")]
        api.post_json("/api/tables", {
            "name": "productos", "primary_key": "id", "storage_kind": "heap",
            "columns": [{"name": n, "type": t or f"VARCHAR({_bytes_max(productos, n) * 2})"} for n, t in columnas],
        })
    ya = {fila["id"] for fila in api.sql("SELECT id FROM productos")["rows"]}
    faltan = [p for p in productos if int(p["id"]) not in ya]
    for p in faltan:
        api.sql(
            f"INSERT INTO productos VALUES ({int(p['id'])}, {_texto(p['nombre'])}, {_texto(p['categoria'])}, "
            f"{float(p['precio'])}, {_texto(p['descripcion'])}, {_texto(p['imagen'])}, "
            f"EXTRACT_FEATURES({_texto(p['imagen'])}, 'image'))")
    print(f"productos: {len(faltan)} insertados, {len(ya)} ya estaban")


def crear_indices(api: Api) -> None:
    tablas = _tablas(api)
    for tabla, nombre, sentencia in INDICES:
        if any(i["name"] == nombre for i in tablas[tabla]["indexes"]):
            print(f"{nombre}: ya existe")
            continue
        api.sql(sentencia)
        print(f"{nombre}: creado")


def seed(api: Api, datos: Path, data_dir: Path, *, espera: float = 120, reemplazar_modelo: bool = False) -> None:
    esperar_api(api, espera)
    copiar_archivos(datos, data_dir, reemplazar_modelo)
    existentes = _tablas(api)
    importar_csv(api, datos, existentes)
    cargar_productos(api, datos, existentes)
    crear_indices(api)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("BD2_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--datos", type=Path, default=DATOS_MUESTRA,
                   help="carpeta con los CSV, imagenes/ y modelo/ (por defecto, la muestra)")
    p.add_argument("--data-dir", type=Path,
                   default=Path(os.environ.get("BD2_DATA_DIR") or RAIZ / "backend" / "data"),
                   help="carpeta de datos del backend (BD2_DATA_DIR)")
    p.add_argument("--espera", type=float, default=120, help="segundos máximos esperando la API")
    p.add_argument("--reemplazar-modelo", action="store_true")
    args = p.parse_args(argv)
    try:
        seed(Api(args.api), args.datos, args.data_dir, espera=args.espera, reemplazar_modelo=args.reemplazar_modelo)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("tienda lista")
    return 0


if __name__ == "__main__":
    sys.exit(main())
