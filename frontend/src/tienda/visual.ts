import { extractMedia, runQuery } from '../api';
import type { CellValue } from '../types';
import type { Recomendacion } from './tipos.ts';

const K = 10;
const METRIC = 'cosine';

function escaparSql(value: string): string {
  return value.replace(/'/g, "''");
}

async function consultar(sql: string): Promise<Record<string, CellValue>[]> {
  const resultado = await runQuery(sql);
  if (!resultado.success) throw new Error(resultado.error ?? 'la consulta visual falló');
  return resultado.rows;
}

function aRecomendacion(fila: Record<string, CellValue>): Recomendacion | null {
  const productoId = Number(fila.id);
  const score = Number(fila.score);
  if (!Number.isInteger(productoId) || !Number.isFinite(score)) return null;
  return { producto_id: productoId, score };
}

/**
 * Recomendación visual para el producto X usando el embedding ya guardado.
 * Devuelve como máximo 10 productos y nunca incluye X.
 */
export async function recomendarPorImagen(productoId: number): Promise<Recomendacion[]> {
  const id = Math.trunc(productoId);
  if (!Number.isFinite(id)) return [];
  const filas = await consultar(`SELECT embedding FROM productos WHERE id = ${id}`);
  if (filas.length === 0) return [];
  const texto = String(filas[0].embedding ?? '').trim();
  if (!texto) return [];
  let vector: number[];
  try {
    const decodificado = JSON.parse(texto);
    if (!Array.isArray(decodificado)) return [];
    vector = decodificado.map(Number);
  } catch {
    return [];
  }
  if (vector.length === 0 || vector.some(valor => !Number.isFinite(valor))) return [];

  // Pedimos k+1 para poder descartar X sin quedarnos con 9.
  const resultado = await consultar(
    `SELECT id, SIMILARITY_SCORE() AS score FROM productos ` +
    `WHERE SIMILAR_TO([${vector.join(', ')}], k=${K + 1}) ` +
    `USING IVF WITH METRIC=${METRIC} ORDER BY score DESC`,
  );
  return resultado
    .map(aRecomendacion)
    .filter((item): item is Recomendacion => item !== null && item.producto_id !== id)
    .slice(0, K);
}

/**
 * Búsqueda visual subiendo una imagen. La imagen se guarda en el servidor con
 * `/api/media/extract`; luego se consulta con `SIMILAR_TO('archivo')`.
 */
export async function buscarPorImagen(archivo: File): Promise<Recomendacion[]> {
  const media = await extractMedia(archivo);
  const nombre = escaparSql(media.name);
  const resultado = await consultar(
    `SELECT id, SIMILARITY_SCORE() AS score FROM productos ` +
    `WHERE SIMILAR_TO('${nombre}', k=${K}) ` +
    `USING IVF WITH METRIC=${METRIC} ORDER BY score DESC`,
  );
  return resultado
    .map(aRecomendacion)
    .filter((item): item is Recomendacion => item !== null)
    .slice(0, K);
}
