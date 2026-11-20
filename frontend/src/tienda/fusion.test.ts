import { test } from 'node:test';
import assert from 'node:assert/strict';
import { consultarFuentes, fusionar, normalizar, pesosAprendidos, recomendar } from './fusion.ts';
import type { FuenteRegistrada, Recomendacion } from './tipos.ts';

const r = (producto_id: number, score: number): Recomendacion => ({ producto_id, score });

test('normalizar lleva los scores a [0, 1]', () => {
  assert.deepEqual(normalizar([r(1, 10), r(2, 5), r(3, 0)]), [r(1, 1), r(2, 0.5), r(3, 0)]);
});

test('normalizar deja en 1 una fuente con todos los scores iguales', () => {
  assert.deepEqual(normalizar([r(1, 3), r(2, 3)]), [r(1, 1), r(2, 1)]);
});

test('normalizar descarta scores no finitos y se queda con el mayor de un producto repetido', () => {
  assert.deepEqual(normalizar([r(1, 2), r(1, 8), r(2, Number.NaN), r(3, 4), r(4, Infinity)]), [r(1, 1), r(3, 0)]);
});

test('fusionar suma por producto, excluye X y ordena por score', () => {
  const salida = fusionar(1, { texto: [r(1, 9), r(2, 4), r(3, 2)], visual: [r(3, 6), r(4, 1)] });
  assert.deepEqual(salida.map(x => x.producto_id), [3, 2, 4]);
  assert.equal(salida[0].score, 0.5);
  assert.deepEqual(salida[0].aportes, { texto: 0, visual: 0.5 });
});

test('fusionar saca a X antes de normalizar para que no defina la escala', () => {
  const salida = fusionar(1, { texto: [r(1, 100), r(2, 4), r(3, 2)] });
  assert.equal(salida[0].producto_id, 2);
  assert.equal(salida[0].score, 1);
});

test('fusionar respeta los pesos y divide por la suma de pesos activos', () => {
  const salida = fusionar(0, { a: [r(1, 1), r(2, 0)], b: [r(2, 1), r(1, 0)] }, { a: 3, b: 1 });
  assert.deepEqual(salida.map(x => x.producto_id), [1, 2]);
  assert.equal(salida[0].score, 0.75);
  assert.equal(salida[1].score, 0.25);
});

test('fusionar ignora fuentes con peso 0 o negativo', () => {
  const salida = fusionar(0, { a: [r(1, 1)], b: [r(2, 1)], c: [r(3, 1)] }, { b: 0, c: -2 });
  assert.deepEqual(salida.map(x => x.producto_id), [1]);
  assert.deepEqual(salida[0].aportes, { a: 1 });
});

test('fusionar corta en k y desempata por cantidad de fuentes y luego por id', () => {
  const salida = fusionar(0, { a: [r(5, 1), r(4, 1), r(3, 1)], b: [r(3, 1), r(2, 0)] }, {}, 2);
  assert.equal(salida.length, 2);
  assert.deepEqual(salida.map(x => x.producto_id), [3, 4]);
});

test('fusionar sin fuentes devuelve vacío', () => {
  assert.deepEqual(fusionar(1, {}), []);
});

test('recomendar sigue con las demás fuentes si una falla', async () => {
  const fuentes: FuenteRegistrada[] = [
    { id: 'texto', nombre: 'Texto', ejecutar: async () => [r(2, 1)] },
    { id: 'visual', nombre: 'Visual', ejecutar: async () => { throw new Error('sin índice'); } },
  ];
  const { recomendaciones, fallidas } = await recomendar(1, fuentes);
  assert.deepEqual(recomendaciones.map(x => x.producto_id), [2]);
  assert.deepEqual(fallidas, [{ fuente: 'visual', error: 'sin índice' }]);
});

test('recomendar usa el peso de cada fuente si no se pasan pesos', async () => {
  const fuentes: FuenteRegistrada[] = [
    { id: 'a', nombre: 'A', peso: 1, ejecutar: async () => [r(1, 1), r(2, 0)] },
    { id: 'b', nombre: 'B', peso: 4, ejecutar: async () => [r(2, 1), r(1, 0)] },
  ];
  const { recomendaciones } = await recomendar(0, fuentes);
  assert.deepEqual(recomendaciones.map(x => x.producto_id), [2, 1]);
});

test('recomendar pasa el id del producto a cada fuente', async () => {
  let recibido: number | null = null;
  await recomendar(7, [{ id: 'a', nombre: 'A', ejecutar: async id => { recibido = id; return []; } }]);
  assert.equal(recibido, 7);
});

test('consultarFuentes separa resultados por fuente y las fallidas', async () => {
  const fuentes: FuenteRegistrada[] = [
    { id: 'a', nombre: 'A', ejecutar: async () => [r(2, 1)] },
    { id: 'b', nombre: 'B', ejecutar: async () => { throw 'caída'; } },
  ];
  const { porFuente, fallidas } = await consultarFuentes(1, fuentes);
  assert.deepEqual(porFuente, { a: [r(2, 1)] });
  assert.deepEqual(fallidas, [{ fuente: 'b', error: 'caída' }]);
});

test('pesosAprendidos usa lo aprendido y deja el peso propio a las fuentes nuevas', () => {
  const fuentes: FuenteRegistrada[] = [
    { id: 'a', nombre: 'A', ejecutar: async () => [] },
    { id: 'b', nombre: 'B', peso: 2, ejecutar: async () => [] },
    { id: 'c', nombre: 'C', ejecutar: async () => [] },
  ];
  assert.deepEqual(pesosAprendidos(fuentes, { a: 0, b: 1.5, z: 3 }), { a: 0, b: 1.5, c: 1 });
});
