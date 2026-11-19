import { runQuery } from "../api";
import type { CellValue } from "../types";

export interface Producto {
  id: number;
  nombre: string;
  categoria: string;
  precio: number;
  imagen: string;
  descripcion?: string;
}

export interface FiltrosProductos {
  texto?: string;
  categoria?: string;
  precioMin?: number;
  precioMax?: number;
  orden?: "relevancia" | "precio_asc" | "precio_desc";
  limite?: number;
}

async function filas(sql: string): Promise<Record<string, CellValue>[]> {
  const resultado = await runQuery(sql);

  if (!resultado.success) {
    throw new Error(resultado.error ?? "la consulta falló");
  }

  return resultado.rows;
}

function literalSql(valor: string): string {
  return `'${valor.replace(/'/g, "''")}'`;
}

function aProducto(fila: Record<string, CellValue>): Producto {
  return {
    id: Number(fila.id),
    nombre: String(fila.nombre),
    categoria: String(fila.categoria),
    precio: Number(fila.precio),
    imagen: String(fila.imagen),
    descripcion:
      fila.descripcion == null
        ? undefined
        : String(fila.descripcion),
  };
}

export function construirConsultaProductos(
  filtros: FiltrosProductos = {},
): string {
  const texto = filtros.texto?.trim();
  const categoria = filtros.categoria?.trim();
  const condiciones: string[] = [];

  if (texto) {
    condiciones.push(
      `MATCH(descripcion, ${literalSql(texto)})`,
    );
  }

  if (categoria) {
    condiciones.push(
      `categoria = ${literalSql(categoria)}`,
    );
  }

  if (Number.isFinite(filtros.precioMin)) {
    condiciones.push(
      `precio >= ${filtros.precioMin}`,
    );
  }

  if (Number.isFinite(filtros.precioMax)) {
    condiciones.push(
      `precio <= ${filtros.precioMax}`,
    );
  }

  const columnas = texto
    ? "id, nombre, categoria, precio, imagen, SCORE() AS score"
    : "id, nombre, categoria, precio, imagen";

  let sql = `SELECT ${columnas} FROM productos`;

  if (condiciones.length > 0) {
    sql += ` WHERE ${condiciones.join(" AND ")}`;
  }

  if (texto) {
    sql += " USING BM25";
  }

  switch (filtros.orden) {
    case "precio_asc":
      sql += " ORDER BY precio ASC";
      break;

    case "precio_desc":
      sql += " ORDER BY precio DESC";
      break;

    case "relevancia":
    default:
      sql += texto
        ? " ORDER BY score DESC"
        : " ORDER BY id";
      break;
  }

  if (
    Number.isInteger(filtros.limite) &&
    filtros.limite !== undefined &&
    filtros.limite > 0
  ) {
    sql += ` LIMIT ${filtros.limite}`;
  }

  return sql;
}

export async function cargarCatalogo(): Promise<Producto[]> {
  return (
    await filas(
      "SELECT id, nombre, categoria, precio, imagen FROM productos ORDER BY id",
    )
  ).map(aProducto);
}

export async function buscarProductos(
  filtros: FiltrosProductos = {},
): Promise<Producto[]> {
  const sql = construirConsultaProductos(filtros);

  return (await filas(sql)).map(aProducto);
}

export async function cargarProducto(
  id: number,
): Promise<Producto | null> {
  const encontradas = await filas(
    `SELECT id, nombre, categoria, precio, imagen, descripcion FROM productos WHERE id = ${Math.trunc(id)}`,
  );

  return encontradas[0]
    ? aProducto(encontradas[0])
    : null;
}

export function urlImagen(nombre: string): string {
  return `/api/media/${encodeURIComponent(nombre)}`;
}

export function formatoPrecio(precio: number): string {
  return `S/ ${precio.toLocaleString("es-PE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}