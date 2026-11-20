import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import CatalogoProductos, { POR_PAGINA } from './CatalogoProductos.tsx';
import type { Producto } from './datos.ts';

const productos = (n: number): Producto[] =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1, nombre: `Producto ${i + 1}`, categoria: 'sillas', precio: 100, imagen: `p${i + 1}.jpg`,
  }) as Producto);

const tarjetas = (html: string) => (html.match(/class="catalogo-card"/g) ?? []).length;

test('muestra solo la primera página y cuántos faltan', () => {
  const html = renderToStaticMarkup(createElement(CatalogoProductos, { productos: productos(2531) }));
  assert.equal(tarjetas(html), POR_PAGINA);
  assert.match(html, new RegExp(`Ver más \\(${2531 - POR_PAGINA} restantes\\)`));
  assert.match(html, /loading="lazy"/);
});

test('sin botón cuando todo entra en una página', () => {
  const html = renderToStaticMarkup(createElement(CatalogoProductos, { productos: productos(5) }));
  assert.equal(tarjetas(html), 5);
  assert.doesNotMatch(html, /Ver más/);
});
