import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ResultsPanel from './ResultsPanel.tsx';
import type { QueryResult } from '../types.ts';

function result(columns: string[], rows: Record<string, string | number>[]): QueryResult {
  return { success: true, statement: 'SELECT', columns, rows,
    affected_rows: rows.length, execution_time_ms: 1.2,
    execution_plan: null, error: null };
}

test('renders actual image search result thumbnail beside filename', () => {
  const html = renderToStaticMarkup(createElement(ResultsPanel, { result: result(
    ['id', 'imagen', 'score'],
    [{id: 7, imagen: 'geom_000007.png', score: 0.987},
     {id: 8, imagen: 'geom_000008.png', score: 0.891}]) }));
  assert.equal((html.match(/class="result-thumbnail"/g) ?? []).length, 2);
  assert.match(html, /src="\/api\/media\/geom_000007\.png"/);
  assert.match(html, /geom_000007\.png<\/span>/);
  assert.match(html, /0\.9870/);
});

test('audio results have audio controls but no image tags', () => {
  const html = renderToStaticMarkup(createElement(ResultsPanel, { result: result(
    ['id', 'archivo'], [{id: 1, archivo: 'consulta_440.wav'}]) }));
  assert.match(html, /<audio/);
  assert.match(html, /src="\/api\/media\/consulta_440\.wav"/);
  assert.doesNotMatch(html, /<img/);
});

test('unsafe filename cannot create a media URL or image tag', () => {
  const html = renderToStaticMarkup(createElement(ResultsPanel, { result: result(
    ['imagen'], [{imagen: '../secret.png'}]) }));
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /secret\.png/);
});
