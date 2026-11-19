import { test } from 'node:test';
import assert from 'node:assert/strict';
import { enlaceProducto, productoDelHash } from './rutas.ts';

test('enlaceProducto arma la dirección de la ficha', () => {
  assert.equal(enlaceProducto(12), '#tienda/producto/12');
});

test('productoDelHash lee el id de la ficha', () => {
  assert.equal(productoDelHash('#tienda/producto/12'), 12);
});

test('productoDelHash devuelve null fuera de una ficha o con un id inválido', () => {
  for (const hash of ['', '#tienda', '#motor', '#tienda/producto/', '#tienda/producto/abc', '#tienda/producto/-3', '#tienda/producto/1.5']) {
    assert.equal(productoDelHash(hash), null, hash);
  }
});
