import test from 'node:test';
import assert from 'node:assert/strict';

import { recomendarPorCoCompra, recomendarPorMetadatos } from './fuentesBackend.ts';

function respuesta(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), { status });
}

test('co-compra llama al endpoint y deja solo producto_id y score', async (t) => {
  const urls: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    urls.push(url);
    return respuesta({
      producto_id: 3,
      recomendaciones: [{ producto_id: 7, score: 0.5, fuente: 'co_compra', evidencia: { co: 2 } }],
    });
  });
  assert.deepEqual(await recomendarPorCoCompra(3), [{ producto_id: 7, score: 0.5 }]);
  assert.deepEqual(urls, ['/api/recommend/copurchase/3?k=10']);
});

test('metadatos usa su propio endpoint', async (t) => {
  const urls: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    urls.push(url);
    return respuesta({ producto_id: 3, recomendaciones: [] });
  });
  assert.deepEqual(await recomendarPorMetadatos(3), []);
  assert.deepEqual(urls, ['/api/recommend/metadata/3?k=10']);
});

test('un error del backend se propaga para que la ficha lo avise', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => respuesta({ detail: 'no existe la tabla compras' }, 400));
  await assert.rejects(recomendarPorCoCompra(3), /no existe la tabla compras/);
});
