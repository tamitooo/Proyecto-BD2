import { useEffect, useMemo, useState } from 'react';
import { cargarCatalogo, type Producto } from './datos.ts';
import FichaProducto from './FichaProducto';
import { FUENTES } from './fuentes.ts';
import { enlaceProducto, productoDelHash } from './rutas.ts';

export default function Tienda() {
  const [productoId, setProductoId] = useState(() => productoDelHash(window.location.hash));
  const [catalogo, setCatalogo] = useState<Producto[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const alCambiar = () => {
      setProductoId(productoDelHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', alCambiar);
    return () => window.removeEventListener('hashchange', alCambiar);
  }, []);

  useEffect(() => {
    cargarCatalogo().then(setCatalogo).catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const porId = useMemo(() => new Map(catalogo.map(p => [p.id, p])), [catalogo]);

  return (
    <main className="tienda">
      <section className="panel">
        <h2 className="panel__title">Tienda</h2>
        <p className="panel__hint">
          Recomendación de productos combinando texto, imágenes, historial de compras y ubicación de tiendas.
        </p>
        {error ? (
          <div className="alert alert--error">
            No se pudieron leer los productos ({error}). Carga la tienda con <code>python -m tools.seed_tienda</code>.
          </div>
        ) : (
          <label className="field tienda__selector">
            Producto (selector provisional hasta el catálogo, #139)
            <select className="select" value={productoId ?? ''}
              onChange={e => { window.location.hash = e.target.value ? enlaceProducto(Number(e.target.value)) : '#tienda'; }}>
              <option value="">— elige un producto —</option>
              {catalogo.map(p => <option key={p.id} value={p.id}>{p.id}. {p.nombre} ({p.categoria})</option>)}
            </select>
          </label>
        )}
      </section>
      {productoId !== null && <FichaProducto productoId={productoId} fuentes={FUENTES} catalogo={porId} />}
    </main>
  );
}
