import { runQuery } from "../api";
import { cargarProducto } from "./datos.ts";
import type { Recomendacion } from "./tipos.ts";

const TOP_K_TEXTO = 10;

function literalSql(valor: string): string {
  return `'${valor.replace(/'/g, "''")}'`;
}

interface DependenciasFuenteTexto {
  cargarProductoFn?: typeof cargarProducto;
  runQueryFn?: typeof runQuery;
}

export async function recomendarPorTexto(
  productoId: number,
  dependencias: DependenciasFuenteTexto = {},
): Promise<Recomendacion[]> {
  const cargarProductoFn =
    dependencias.cargarProductoFn ?? cargarProducto;

  const runQueryFn =
    dependencias.runQueryFn ?? runQuery;

  const producto = await cargarProductoFn(productoId);

  if (!producto) {
    throw new Error(`No existe el producto ${productoId}`);
  }

  const descripcion = producto.descripcion?.trim();

  if (!descripcion) {
    return [];
  }

  const sql = `
    SELECT id, SCORE() AS score
    FROM productos
    WHERE MATCH(descripcion, ${literalSql(descripcion)})
    USING BM25
    ORDER BY score DESC
    LIMIT ${TOP_K_TEXTO + 1}
  `.trim();

  const resultado = await runQueryFn(sql);

  if (!resultado.success) {
    throw new Error(
      resultado.error ?? "Falló la recomendación textual con BM25",
    );
  }

  return resultado.rows
    .map((fila) => ({
      producto_id: Number(fila.id),
      score: Number(fila.score),
    }))
    .filter(
      (item) =>
        item.producto_id !== productoId &&
        Number.isFinite(item.producto_id) &&
        Number.isFinite(item.score),
    )
    .slice(0, TOP_K_TEXTO);
}