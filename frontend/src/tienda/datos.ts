import { runQuery } from '../api';
import type { CellValue } from '../types';

export interface Producto {
  id: number;
  nombre: string;
  categoria: string;
  precio: number;
  imagen: string;
  descripcion?: string;
}

async function filas(sql: string): Promise<Record<string, CellValue>[]> {
  const resultado = await runQuery(sql);
  if (!resultado.success) throw new Error(resultado.error ?? 'la consulta falló');
  return resultado.rows;
}

function aProducto(fila: Record<string, CellValue>): Producto {
  return {
    id: Number(fila.id),
    nombre: String(fila.nombre),
    categoria: String(fila.categoria),
    precio: Number(fila.precio),
    imagen: String(fila.imagen),
    descripcion: fila.descripcion == null ? undefined : String(fila.descripcion),
  };
}

export async function cargarCatalogo(): Promise<Producto[]> {
  return (await filas('SELECT id, nombre, categoria, precio, imagen FROM productos ORDER BY id')).map(aProducto);
}

export async function cargarProducto(id: number): Promise<Producto | null> {
  const encontradas = await filas(
    `SELECT id, nombre, categoria, precio, imagen, descripcion FROM productos WHERE id = ${Math.trunc(id)}`);
  return encontradas[0] ? aProducto(encontradas[0]) : null;
}

export function urlImagen(nombre: string): string {
  return `/api/media/${encodeURIComponent(nombre)}`;
}

export function formatoPrecio(precio: number): string {
  return `S/ ${precio.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
