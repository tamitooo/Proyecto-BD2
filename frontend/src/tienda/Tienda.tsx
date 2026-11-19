import { useEffect, useMemo, useState } from "react";
import { buscarProductos, cargarCatalogo, type Producto } from "./datos.ts";
import FichaProducto from "./FichaProducto";
import { FUENTES } from "./fuentes.ts";
import { productoDelHash } from "./rutas.ts";
import CatalogoProductos from "./CatalogoProductos";

export default function Tienda() {
  const [texto, setTexto] = useState("");
  const [buscando, setBuscando] = useState(false);
  const [productoId, setProductoId] = useState(() =>
    productoDelHash(window.location.hash),
  );
  const [catalogo, setCatalogo] = useState<Producto[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const alCambiar = () => {
      setProductoId(productoDelHash(window.location.hash));
      window.scrollTo(0, 0);
    };

    window.addEventListener("hashchange", alCambiar);

    return () => {
      window.removeEventListener("hashchange", alCambiar);
    };
  }, []);

  useEffect(() => {
    let vigente = true;

    if (!texto.trim()) {
      setBuscando(true);

      cargarCatalogo()
        .then((productos) => {
          if (!vigente) return;

          setCatalogo(productos);
          setError(null);
        })
        .catch((e) => {
          if (!vigente) return;

          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (vigente) setBuscando(false);
        });

      return () => {
        vigente = false;
      };
    }

    setBuscando(true);

    const timer = window.setTimeout(() => {
      buscarProductos({
        texto,
        orden: "relevancia",
      })
        .then((productos) => {
          if (!vigente) return;

          setCatalogo(productos);
          setError(null);
        })
        .catch((e) => {
          if (!vigente) return;

          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (vigente) setBuscando(false);
        });
    }, 300);

    return () => {
      vigente = false;
      window.clearTimeout(timer);
    };
  }, [texto]);

  const porId = useMemo(
    () => new Map(catalogo.map((producto) => [producto.id, producto])),
    [catalogo],
  );

  return (
    <main className="tienda">
      <section className="panel">
        <h2 className="panel__title">Tienda</h2>

        <p className="panel__hint">
          Recomendación de productos combinando texto, imágenes, historial de
          compras y ubicación de tiendas.
        </p>

        <div className="tienda__controles">
          <label className="field">
            Buscar productos
            <input
              className="input"
              type="search"
              value={texto}
              placeholder="Ej. laptop gaming"
              onChange={(e) => setTexto(e.target.value)}
            />
          </label>

          {buscando && <span className="panel__hint">Buscando…</span>}
        </div>

        {error ? (
          <div className="alert alert--error">
            No se pudieron leer los productos ({error}). Carga la tienda con{" "}
            <code>python -m tools.seed_tienda</code>.
          </div>
        ) : (
          <CatalogoProductos productos={catalogo} />
        )}
      </section>

      {productoId !== null && (
        <FichaProducto
          productoId={productoId}
          fuentes={FUENTES}
          catalogo={porId}
        />
      )}
    </main>
  );
}
