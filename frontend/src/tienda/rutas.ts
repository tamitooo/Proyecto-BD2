const PREFIJO_PRODUCTO = '#tienda/producto/';

export function enlaceProducto(productoId: number): string {
  return `${PREFIJO_PRODUCTO}${productoId}`;
}

export function productoDelHash(hash: string): number | null {
  if (!hash.startsWith(PREFIJO_PRODUCTO)) return null;
  const texto = hash.slice(PREFIJO_PRODUCTO.length);
  return /^\d+$/.test(texto) ? Number(texto) : null;
}
