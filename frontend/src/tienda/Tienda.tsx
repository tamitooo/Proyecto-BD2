import { useEffect, useMemo, useState } from "react";
import { buscarProductos, cargarCatalogo, type Producto } from "./datos.ts";
import FichaProducto from "./FichaProducto";
import BusquedaVisual from "./BusquedaVisual";
import { FUENTES } from "./fuentes.ts";
import { productoDelHash } from "./rutas.ts";
import CatalogoProductos from "./CatalogoProductos";

type OrdenCatalogo = "relevancia" | "precio_asc" | "precio_desc";

export default function Tienda() {
  const [texto, setTexto] = useState("");
  const [categoria, setCategoria] = useState("");
  const [precioMin, setPrecioMin] = useState("");
  const [precioMax, setPrecioMax] = useState("");
  const [orden, setOrden] = useState<OrdenCatalogo>("relevancia");
  const [buscando, setBuscando] = useState(false);

  const [productoId, setProductoId] = useState(() =>
    productoDelHash(window.location.hash),
  );

  const [catalogo, setCatalogo] = useState<Producto[]>([]);
  const [catalogoBase, setCatalogoBase] = useState<Producto[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const alCambiar = () => {
      setProductoId(productoDelHash(window.location.hash));
    };

    window.addEventListener("hashchange", alCambiar);

    return () => {
      window.removeEventListener("hashchange", alCambiar);
    };
  }, []);

  // La ficha va arriba del catálogo: al cambiar de producto se vuelve al inicio.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [productoId]);

  useEffect(() => {
    let vigente = true;

    cargarCatalogo()
      .then((productos) => {
        if (!vigente) return;

        setCatalogo(productos);
        setCatalogoBase(productos);
        setError(null);
      })
      .catch((e) => {
        if (!vigente) return;

        setError(e instanceof Error ? e.message : String(e));
      });

    return () => {
      vigente = false;
    };
  }, []);

  useEffect(() => {
    let vigente = true;

    const sinFiltros =
      !texto.trim() &&
      !categoria &&
      !precioMin &&
      !precioMax &&
      orden === "relevancia";

    if (sinFiltros) {
      setCatalogo(catalogoBase);
      setError(null);
      setBuscando(false);

      return () => {
        vigente = false;
      };
    }

    setBuscando(true);

    const timer = window.setTimeout(() => {
      buscarProductos({
        texto: texto || undefined,
        categoria: categoria || undefined,
        precioMin: precioMin ? Number(precioMin) : undefined,
        precioMax: precioMax ? Number(precioMax) : undefined,
        orden,
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
          if (vigente) {
            setBuscando(false);
          }
        });
    }, 300);

    return () => {
      vigente = false;
      window.clearTimeout(timer);
    };
  }, [texto, categoria, precioMin, precioMax, orden, catalogoBase]);

  const categorias = useMemo(
    () =>
      [...new Set(catalogoBase.map((producto) => producto.categoria))]
        .filter(Boolean)
        .sort(),
    [catalogoBase],
  );

  const porId = useMemo(
    () => new Map(catalogoBase.map((producto) => [producto.id, producto])),
    [catalogoBase],
  );

  const limpiarFiltros = () => {
    setTexto("");
    setCategoria("");
    setPrecioMin("");
    setPrecioMax("");
    setOrden("relevancia");
  };

  const hayFiltros =
    Boolean(texto.trim()) ||
    Boolean(categoria) ||
    Boolean(precioMin) ||
    Boolean(precioMax) ||
    orden !== "relevancia";

  return (
    <main className="tienda">
      {productoId !== null && (
        <FichaProducto
          productoId={productoId}
          fuentes={FUENTES}
          catalogo={porId}
        />
      )}

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
              placeholder="Ej. silla de comedor"
              onChange={(e) => setTexto(e.target.value)}
            />
          </label>

          <label className="field">
            Categoría
            <select
              className="select"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value)}
            >
              <option value="">Todas</option>

              {categorias.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            Precio mínimo
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              value={precioMin}
              placeholder="0"
              onChange={(e) => setPrecioMin(e.target.value)}
            />
          </label>

          <label className="field">
            Precio máximo
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              value={precioMax}
              placeholder="Sin límite"
              onChange={(e) => setPrecioMax(e.target.value)}
            />
          </label>

          <label className="field">
            Ordenar por
            <select
              className="select"
              value={orden}
              onChange={(e) => setOrden(e.target.value as OrdenCatalogo)}
            >
              <option value="relevancia">Relevancia</option>
              <option value="precio_asc">Precio: menor a mayor</option>
              <option value="precio_desc">Precio: mayor a menor</option>
            </select>
          </label>

          <button
            type="button"
            className="button"
            onClick={limpiarFiltros}
            disabled={!hayFiltros}
          >
            Limpiar filtros
          </button>

          {buscando && <span className="panel__hint">Buscando…</span>}
        </div>

        <div className="tienda__resumen">
          <span className="panel__hint">
            {catalogo.length} producto
            {catalogo.length === 1 ? "" : "s"} encontrado
            {catalogo.length === 1 ? "" : "s"}
          </span>
        </div>

        {error ? (
          <div className="alert alert--error">
            No se pudieron leer los productos ({error}). Carga la tienda con{" "}
            <code>python -m tools.seed_tienda</code>.
          </div>
        ) : catalogo.length === 0 && !buscando ? (
          <div className="tienda__vacio">
            <p>No encontramos productos con los filtros seleccionados.</p>

            <button type="button" className="button" onClick={limpiarFiltros}>
              Ver todos los productos
            </button>
          </div>
        ) : (
          <CatalogoProductos productos={catalogo} />
        )}
      </section>
      <BusquedaVisual catalogo={porId} />
    </main>
  );
}
