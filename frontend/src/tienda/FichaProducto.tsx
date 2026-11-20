import { useEffect, useMemo, useState } from 'react';
import { consultarFuentes, fusionar, pesosAprendidos, pesosPorDefecto, type ResultadosPorFuente } from './fusion.ts';
import { EVALUACION_PESOS, PESOS_APRENDIDOS } from './pesosAprendidos.ts';
import { cargarProducto, formatoPrecio, urlImagen, type Producto } from './datos.ts';
import { enlaceProducto } from './rutas.ts';
import type { FuenteRegistrada } from './tipos.ts';
import TiendasCercanas from './TiendasCercanas';

const COLORES = ['#0369a1', '#c2410c', '#15803d', '#7e22ce', '#b45309', '#be123c'];

interface Props {
  productoId: number;
  fuentes: FuenteRegistrada[];
  catalogo: Map<number, Producto>;
}

export default function FichaProducto({ productoId, fuentes, catalogo }: Props) {
  const [producto, setProducto] = useState<Producto | null>(null);
  const [resultados, setResultados] = useState<ResultadosPorFuente | null>(null);
  const [pesos, setPesos] = useState(() => pesosPorDefecto(fuentes));
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    Promise.all([cargarProducto(productoId), consultarFuentes(productoId, fuentes)])
      .then(([encontrado, porFuente]) => {
        if (!vigente) return;
        setProducto(encontrado);
        setResultados(porFuente);
      })
      .catch(e => vigente && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => vigente && setCargando(false));
    return () => { vigente = false; };
  }, [productoId, fuentes]);

  const recomendaciones = useMemo(
    () => (resultados ? fusionar(productoId, resultados.porFuente, pesos) : []),
    [productoId, resultados, pesos],
  );
  const color = (id: string) => COLORES[Math.max(0, fuentes.findIndex(f => f.id === id)) % COLORES.length];
  const nombreFuente = (id: string) => fuentes.find(f => f.id === id)?.nombre ?? id;

  if (error) return <div className="alert alert--error">No se pudo cargar el producto: {error}</div>;
  if (cargando && !producto) return <p className="panel__hint">Cargando producto…</p>;
  if (!producto) return <div className="alert">No existe el producto {productoId}.</div>;

  return (
    <div className="ficha" id="ficha-producto" aria-busy={cargando}>
      <section className="panel ficha__producto">
        <img className="ficha__imagen" src={urlImagen(producto.imagen)} alt={producto.nombre} />
        <div>
          <span className="chip">{producto.categoria}</span>
          <h2 className="ficha__nombre">{producto.nombre}</h2>
          <p className="ficha__precio">{formatoPrecio(producto.precio)}</p>
          {producto.descripcion && <p className="ficha__descripcion">{producto.descripcion}</p>}
        </div>
      </section>

      <section className="panel" aria-labelledby="recomendados">
        <h3 id="recomendados" className="panel__title">Te puede interesar</h3>
        {fuentes.length === 0 ? (
          <p className="panel__hint">
            Todavía no hay fuentes de recomendación registradas en <code>frontend/src/tienda/fuentes.ts</code>.
          </p>
        ) : (
          <>
            <fieldset className="pesos">
              <legend className="panel__subtitle">Peso de cada fuente</legend>
              {fuentes.map(f => (
                <label key={f.id} className="pesos__fuente">
                  <span className="pesos__color" style={{ background: color(f.id) }} aria-hidden="true" />
                  {f.nombre}
                  <input type="range" min={0} max={3} step={0.5} value={pesos[f.id] ?? 1}
                    onChange={e => setPesos(p => ({ ...p, [f.id]: Number(e.target.value) }))} />
                  <output>{(pesos[f.id] ?? 1).toFixed(1)}</output>
                </label>
              ))}
            </fieldset>
            <div className="button-row pesos__acciones">
              <button type="button" className="button" onClick={() => setPesos(pesosAprendidos(fuentes, PESOS_APRENDIDOS))}>
                Usar pesos aprendidos
              </button>
              <button type="button" className="button" onClick={() => setPesos(pesosPorDefecto(fuentes))}>
                Pesos iguales
              </button>
              <span className="panel__hint">
                Aprendidos con el historial de compras: Precision@10 {EVALUACION_PESOS.precision_iguales.toFixed(3)} con
                pesos iguales y {EVALUACION_PESOS.precision_aprendidos.toFixed(3)} con los aprendidos (validación cruzada).
              </span>
            </div>
            {fuentes.length === 1 && (
              <p className="panel__hint">
                Con una sola fuente activa, su peso se normaliza a 1 y el orden no
                cambia. Registra otra fuente (texto, metadatos o co-compra) para
                ver el efecto de la fusión.
              </p>
            )}
            {resultados && resultados.fallidas.length > 0 && (
              <div className="alert alert--error">
                Sin resultados de: {resultados.fallidas.map(f => `${nombreFuente(f.fuente)} (${f.error})`).join('; ')}
              </div>
            )}
            {recomendaciones.length === 0 ? (
              <p className="panel__hint">Ninguna fuente devolvió productos para recomendar.</p>
            ) : (
              <ol className="recomendaciones">
                {recomendaciones.map(r => {
                  const otro = catalogo.get(r.producto_id);
                  return (
                    <li key={r.producto_id} className="recomendacion">
                      <a href={enlaceProducto(r.producto_id)} className="recomendacion__enlace">
                        {otro && <img src={urlImagen(otro.imagen)} alt="" className="recomendacion__imagen" />}
                        <span className="recomendacion__nombre">{otro?.nombre ?? `Producto ${r.producto_id}`}</span>
                        {otro && <span className="recomendacion__precio">{formatoPrecio(otro.precio)}</span>}
                      </a>
                      <div className="recomendacion__barra" role="img"
                        aria-label={Object.entries(r.aportes)
                          .map(([f, v]) => `${nombreFuente(f)} ${Math.round(v * 100)}%`).join(', ')}>
                        {Object.entries(r.aportes).map(([f, v]) => (
                          <span key={f} style={{ width: `${v * 100}%`, background: color(f) }}
                            title={`${nombreFuente(f)}: ${Math.round(v * 100)}%`} />
                        ))}
                      </div>
                      <span className="recomendacion__score">{Math.round(r.score * 100)}%</span>
                    </li>
                  );
                })}
              </ol>
            )}
          </>
        )}
      </section>

      <TiendasCercanas productoId={productoId} />
    </div>
  );
}
