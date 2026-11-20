/** Safe media URLs for SQL query results. Never use arbitrary user-supplied paths. */
const IMAGE_COLUMNS = new Set(['imagen', 'image', 'foto', 'ruta_imagen', 'image_path']);
const AUDIO_COLUMNS = new Set(['audio', 'ruta_audio', 'audio_path', 'archivo_audio', 'sonido']);
const GENERIC_COLUMNS = new Set(['archivo', 'filename', 'nombre', 'name', 'ruta', 'path']);
const IMAGE_EXT = /\.(?:png|jpe?g|webp|gif|bmp|tiff?)$/i;
const AUDIO_EXT = /\.(?:wav|wave|mp3|ogg|oga|opus|flac|m4a|aac)$/i;
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;

export type MediaLink = { url: string; kind: 'image' | 'audio' };

export function resultMediaUrl(column: string, value: unknown): MediaLink | null {
  if (typeof value !== 'string' || !SAFE_NAME.test(value) || value.includes('..')) return null;
  const normalizedColumn = column.toLowerCase();
  const image = IMAGE_EXT.test(value) && (IMAGE_COLUMNS.has(normalizedColumn) || GENERIC_COLUMNS.has(normalizedColumn));
  const audio = AUDIO_EXT.test(value) && (AUDIO_COLUMNS.has(normalizedColumn) || GENERIC_COLUMNS.has(normalizedColumn));
  if (!image && !audio) return null;
  return { url: `/api/media/${encodeURIComponent(value)}`, kind: image ? 'image' : 'audio' };
}

/** Compatibility helper for existing image consumers. */
export function resultImageUrl(column: string, value: unknown): string | null {
  const media = resultMediaUrl(column, value);
  return media?.kind === 'image' ? media.url : null;
}
