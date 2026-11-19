import { enlaceProducto } from "./rutas.ts";
import { formatoPrecio, urlImagen, type Producto } from "./datos.ts";

interface Props {
  productos: Producto[];
}

export default function CatalogoProductos({ productos }: Props) {
  if (productos.length === 0) {
    return <p className="panel__hint">No hay productos disponibles.</p>;
  }

  return (
    <div className="catalogo-grid">
      {productos.map((producto) => (
        <a
          key={producto.id}
          href={enlaceProducto(producto.id)}
          className="catalogo-card"
        >
          <img
            src={urlImagen(producto.imagen)}
            alt={producto.nombre}
            className="catalogo-card__imagen"
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
  );
}
