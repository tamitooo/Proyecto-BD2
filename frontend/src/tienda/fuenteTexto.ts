import { runQuery } from '../api';
import { cargarProducto } from './datos.ts';
import type { Recomendacion } from './tipos.ts';

const TOP_K_TEXTO = 10;

function literalSql(valor: string): string {
  return `'${valor.replace(/'/g, "''")}'`;
}

export async function recomendarPorTexto(
  productoId: number,
): Promise<Recomendacion[]> {
  const producto = await cargarProducto(productoId);

  if (!producto) {
    throw new Error(`No existe el producto ${productoId}`);
  }

  const descripcion = producto.descripcion?.trim();

  if (!descripcion) {
    return [];
  }

  // Pedimos uno adicional porque el propio producto X puede aparecer
  // entre los mejores resultados de su descripción.
  const sql = `
    SELECT id, SCORE() AS score
    FROM productos
    WHERE MATCH(descripcion, ${literalSql(descripcion)})
    USING BM25
    ORDER BY score DESC
    LIMIT ${TOP_K_TEXTO + 1}
  `.trim();

  const resultado = await runQuery(sql);

  if (!resultado.success) {
    throw new Error(
      resultado.error ?? 'Falló la recomendación textual con BM25',
    );
  }

  return resultado.rows
    .map((fila) => ({
      producto_id: Number(fila.id),
      score: Number(fila.score),
    }))
    .filter(
      (item) =>
        item.producto_id !== productoId
        && Number.isFinite(item.producto_id)
        && Number.isFinite(item.score),
    )
    .slice(0, TOP_K_TEXTO);
}