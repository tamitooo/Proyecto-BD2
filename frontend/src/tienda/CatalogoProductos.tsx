import * as React from "react";
import { useEffect, useState } from "react";
import { enlaceProducto } from "./rutas.ts";
import { formatoPrecio, urlImagen, type Producto } from "./datos.ts";

export const POR_PAGINA = 24;

interface Props {
  productos: Producto[];
}

export default function CatalogoProductos({ productos }: Props) {
  const [visibles, setVisibles] = useState(POR_PAGINA);

  useEffect(() => {
    setVisibles(POR_PAGINA);
  }, [productos]);

  if (productos.length === 0) {
    return <p className="panel__hint">No hay productos disponibles.</p>;
  }

  const restantes = productos.length - visibles;

  return (
    <>
      <div className="catalogo-grid">
        {productos.slice(0, visibles).map((producto) => (
          <a
            key={producto.id}
            href={enlaceProducto(producto.id)}
            className="catalogo-card"
          >
            <img
              src={urlImagen(producto.imagen)}
              alt={producto.nombre}
              className="catalogo-card__imagen"
              loading="lazy"
              decoding="async"
            />

            <div className="catalogo-card__contenido">
              <span className="chip">{producto.categoria}</span>

              <h3 className="catalogo-card__nombre">{producto.nombre}</h3>

              <p className="catalogo-card__precio">
                {formatoPrecio(producto.precio)}
              </p>
            </div>
          </a>
        ))}
      </div>

      {restantes > 0 && (
        <div className="catalogo-mas">
          <button
            type="button"
            className="button"
            onClick={() => setVisibles((n) => n + POR_PAGINA)}
          >
            Ver más ({restantes} restantes)
          </button>
        </div>
      )}
    </>
  );
}
