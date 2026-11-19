import test from "node:test";
import assert from "node:assert/strict";

import { construirConsultaProductos } from "./datos.ts";

test("construye busqueda BM25 por relevancia", () => {
  const sql = construirConsultaProductos({
    texto: "laptop gaming",
    orden: "relevancia",
  });

  assert.equal(
    sql,
    "SELECT id, nombre, categoria, precio, imagen, SCORE() AS score " +
      "FROM productos " +
      "WHERE MATCH(descripcion, 'laptop gaming') " +
      "USING BM25 " +
      "ORDER BY score DESC",
  );
});

test("combina categoria y rango de precio", () => {
  const sql = construirConsultaProductos({
    categoria: "laptops",
    precioMin: 2000,
    precioMax: 5000,
  });

  assert.equal(
    sql,
    "SELECT id, nombre, categoria, precio, imagen " +
      "FROM productos " +
      "WHERE categoria = 'laptops' AND precio >= 2000 AND precio <= 5000 " +
      "ORDER BY id",
  );
});

test("ordena por precio ascendente", () => {
  const sql = construirConsultaProductos({
    orden: "precio_asc",
  });

  assert.equal(
    sql,
    "SELECT id, nombre, categoria, precio, imagen " +
      "FROM productos ORDER BY precio ASC",
  );
});

test("ordena por precio descendente", () => {
  const sql = construirConsultaProductos({
    orden: "precio_desc",
  });

  assert.equal(
    sql,
    "SELECT id, nombre, categoria, precio, imagen " +
      "FROM productos ORDER BY precio DESC",
  );
});

test("aplica LIMIT cuando es valido", () => {
  const sql = construirConsultaProductos({
    texto: "celular",
    limite: 10,
  });

  assert.match(sql, /LIMIT 10$/);
});

test("escapa comillas simples en texto y categoria", () => {
  const sql = construirConsultaProductos({
    texto: "laptop gamer d'alta",
    categoria: "tecnologia d'oficina",
  });

  assert.match(
    sql,
    /MATCH\(descripcion, 'laptop gamer d''alta'\)/,
  );

  assert.match(
    sql,
    /categoria = 'tecnologia d''oficina'/,
  );
});