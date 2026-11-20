import test from "node:test";
import assert from "node:assert/strict";

import { recomendarPorTexto } from "./fuenteTexto.ts";

test(
  "recomendarPorTexto excluye el producto origen y conserva score",
  async () => {
    const recomendaciones = await recomendarPorTexto(1, {
      cargarProductoFn: async () => ({
        id: 1,
        nombre: "Laptop Gaming",
        categoria: "laptops",
        precio: 3500,
        imagen: "laptop.png",
        descripcion: "laptop gaming potente con tarjeta grafica",
      }),

      runQueryFn: async () => ({
        success: true,
        statement: "SELECT",
        columns: ["id", "score"],
        rows: [
          { id: 1, score: 10 },
          { id: 2, score: 8.5 },
          { id: 3, score: 7.2 },
        ],
        affected_rows: 3,
        execution_time_ms: 1,
        execution_plan: null,
        error: null,
      }),
    });

    assert.deepEqual(recomendaciones, [
      { producto_id: 2, score: 8.5 },
      { producto_id: 3, score: 7.2 },
    ]);
  },
);

test(
  "recomendarPorTexto devuelve vacio si no hay descripcion",
  async () => {
    const recomendaciones = await recomendarPorTexto(1, {
      cargarProductoFn: async () => ({
        id: 1,
        nombre: "Producto",
        categoria: "otros",
        precio: 100,
        imagen: "producto.png",
      }),
    });

    assert.deepEqual(recomendaciones, []);
  },
);

test(
  "recomendarPorTexto falla si el producto no existe",
  async () => {
    await assert.rejects(
      () =>
        recomendarPorTexto(999, {
          cargarProductoFn: async () => null,
        }),
      /No existe el producto 999/,
    );
  },
);