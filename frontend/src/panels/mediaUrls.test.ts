import assert from 'node:assert/strict';
import test from 'node:test';
import { resultImageUrl, resultMediaUrl } from '../mediaUrls.ts';

test('only whitelisted basename image paths are rendered', () => {
  assert.equal(resultImageUrl('imagen', 'geom_000001.png'), '/api/media/geom_000001.png');
  assert.deepEqual(resultMediaUrl('archivo', 'foto_004.jpeg'), {url: '/api/media/foto_004.jpeg', kind: 'image'});
  for (const bad of ['../secret.png', 'http://evil/image.png', 'data:image/png', 'x.svg', 'x..png', '', '.secret.png']) {
    assert.equal(resultMediaUrl('imagen', bad), null);
  }
  assert.equal(resultMediaUrl('precio', 'geom_000001.png'), null);
});

test('audio filenames get sound player URLs, not image URLs', () => {
  assert.deepEqual(resultMediaUrl('nombre', 'consulta_440.wav'), {url: '/api/media/consulta_440.wav', kind: 'audio'});
  assert.deepEqual(resultMediaUrl('audio', 'consulta_440.mp3'), {url: '/api/media/consulta_440.mp3', kind: 'audio'});
  assert.equal(resultImageUrl('audio', 'consulta_440.wav'), null);
  assert.equal(resultMediaUrl('imagen', 'consulta_440.wav'), null);
});
