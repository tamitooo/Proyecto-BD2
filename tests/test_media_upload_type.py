"""Validación del tipo de archivo en ``POST /api/media/extract``.

La ruta rechaza un ``text/plain``/``text/html`` antes de leer o guardar el
archivo. Los casos de extensión y contenido inválido se cubren en
``tests/test_media_engine.py``.
"""

from __future__ import annotations

import asyncio
import io
import unittest

from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from backend.api import media_extract


def _upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


class TestMediaUploadType(unittest.TestCase):
    def test_rechaza_text_plain_en_el_endpoint(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                media_extract(
                    _upload("nota.txt", b"hola", "text/plain"),
                    kind="",
                )
            )
        self.assertEqual(context.exception.status_code, 415)
        self.assertIn("no soportado", context.exception.detail)

    def test_rechaza_html_en_el_endpoint(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                media_extract(
                    _upload("pagina.html", b"<html></html>", "text/html"),
                    kind="",
                )
            )
        self.assertEqual(context.exception.status_code, 415)

    def test_permite_octet_stream_y_deja_que_valide_la_extension(self):
        # Sin content-type de imagen, la ruta permite octet-stream y el motor
        # rechaza un .txt antes de guardarlo.
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                media_extract(
                    _upload("nota.txt", b"hola", "application/octet-stream"),
                    kind="",
                )
            )
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("no soportado", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
