import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import SongRecognitionPanel from './SongRecognitionPanel.tsx';

test('song recognition panel exposes an upload and SQL/IVF search mode', () => {
  const html = renderToStaticMarkup(createElement(SongRecognitionPanel));
  assert.match(html, /type="file"/);
  assert.match(html, /Database SQL \+ IVF/);
  assert.match(html, /Exact cosine baseline/);
  assert.match(html, /Find matching songs/);
  assert.match(html, /ignores silence/);
});
