import { useState } from 'react';
import { buscarPorImagen } from './visual.ts';
import { formatoPrecio, urlImagen, type Producto } from './datos.ts';
import { enlaceProducto } from './rutas.ts';
import type { Recomendacion } from './tipos.ts';

interface Props {
  catalogo: Map<number, Producto>;
}

export default function BusquedaVisual({ catalogo }: Props) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [resultados, setResultados] = useState<Recomendacion[] | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [excluirExacta, setExcluirExacta] = useState(true);

  const buscar = async () => {
    if (!archivo) return;
    setCargando(true);
    setError(null);
    try {
      setResultados(await buscarPorImagen(archivo, { excluirCoincidenciaExacta: excluirExacta }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResultados(null);
    } finally {
      setCargando(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="busqueda-visual">
      <h3 id="busqueda-visual" className="panel__title">Buscar productos por imagen</h3>
      <p className="panel__hint">
        Sube una foto y el motor extrae su vector BoVW para buscar los productos
        visualmente más parecidos con <code>SIMILAR_TO ... USING IVF</code>.
      </p>
      <div className="form-grid">
        <label className="field field--wide">
          <span>Imagen de consulta</span>
          <input
            className="input"
            type="file"
            accept="image/*"
            disabled={cargando}
            onChange={e => {
              setArchivo(e.target.files?.[0] ?? null);
              setResultados(null);
              setError(null);
            }}
          />
        </label>
        <label className="field field--wide">
          <span>
            <input
              type="checkbox"
              checked={excluirExacta}
              disabled={cargando}
              onChange={e => {
                setExcluirExacta(e.target.checked);
                setResultados(null);
              }}
            />{' '}
            Excluir la coincidencia exacta (si la imagen es de un producto del catálogo)
          </span>
        </label>
      </div>
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!archivo || cargando} onClick={buscar}>
          {cargando ? 'Buscando…' : 'Buscar similares'}
        </button>
      </div>
      {error && <div className="alert alert--error">No se pudo buscar por imagen: {error}</div>}
      {resultados && resultados.length === 0 && (
        <p className="panel__hint">No se encontraron productos parecidos a esa imagen.</p>
      )}
      {resultados && resultados.length > 0 && (
        <ol className="recomendaciones">
          {resultados.map(item => {
            const producto = catalogo.get(item.producto_id);
            return (
              <li key={item.producto_id} className="recomendacion">
                <a href={enlaceProducto(item.producto_id)} className="recomendacion__enlace">
                  {producto && <img src={urlImagen(producto.imagen)} alt="" className="recomendacion__imagen" />}
                  <span className="recomendacion__nombre">
                    {producto?.nombre ?? `Producto ${item.producto_id}`}
                  </span>
                  {producto && <span className="recomendacion__precio">{formatoPrecio(producto.precio)}</span>}
                </a>
                <span className="recomendacion__score">{Math.round(item.score * 100)}%</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
