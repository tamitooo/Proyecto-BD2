import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import SongRecognitionPanel from './SongRecognitionPanel.tsx';

test('song recognition panel muestra la subida de archivo y el modo SQL/IVF', () => {
  const html = renderToStaticMarkup(createElement(SongRecognitionPanel));
  assert.match(html, /type="file"/);
  assert.match(html, /SQL del motor \+ IVF/);
  assert.match(html, /Coseno exacto/);
  assert.match(html, /Buscar canciones parecidas/);
  assert.match(html, /ignora el silencio/);
});
