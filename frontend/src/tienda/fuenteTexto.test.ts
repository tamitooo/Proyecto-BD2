import test from 'node:test';
import assert from 'node:assert/strict';

import type { QueryResult } from '../types';
import * as api from '../api';
import * as datos from './datos.ts';
import { recomendarPorTexto } from './fuenteTexto.ts';

test('recomendarPorTexto excluye el producto origen y conserva score', async (t) => {
  t.mock.method(datos, 'cargarProducto', async () => ({
    id: 1,
    nombre: 'Laptop Gaming',
    categoria: 'laptops',
    precio: 3500,
    imagen: 'laptop.png',
    descripcion: 'laptop gaming potente con tarjeta grafica',
  }));

  t.mock.method(api, 'runQuery', async () => ({
    success: true,
    rows: [
      { id: 1, score: 10 },
      { id: 2, score: 8.5 },
      { id: 3, score: 7.2 },
    ],
  } as QueryResult));

  const recomendaciones = await recomendarPorTexto(1);

  assert.deepEqual(recomendaciones, [
    { producto_id: 2, score: 8.5 },
    { producto_id: 3, score: 7.2 },
  ]);
});

test('recomendarPorTexto devuelve vacio si no hay descripcion', async (t) => {
  t.mock.method(datos, 'cargarProducto', async () => ({
    id: 1,
    nombre: 'Producto',
    categoria: 'otros',
    precio: 100,
    imagen: 'producto.png',
  }));

  const recomendaciones = await recomendarPorTexto(1);

  assert.deepEqual(recomendaciones, []);
});

test('recomendarPorTexto falla si el producto no existe', async (t) => {
  t.mock.method(datos, 'cargarProducto', async () => null);

  await assert.rejects(
    () => recomendarPorTexto(999),
    /No existe el producto 999/,
  );
});