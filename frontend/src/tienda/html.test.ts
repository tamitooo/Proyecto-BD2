import assert from 'node:assert/strict';
import test from 'node:test';
import { escaparHtml } from './html.ts';

test('escaparHtml neutraliza etiquetas y atributos', () => {
  assert.equal(escaparHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.equal(escaparHtml("Tom & Jerry's"), 'Tom &amp; Jerry&#39;s');
});

test('escaparHtml acepta valores vacíos', () => {
  assert.equal(escaparHtml(null), '');
  assert.equal(escaparHtml(undefined), '');
  assert.equal(escaparHtml('Miraflores'), 'Miraflores');
});
