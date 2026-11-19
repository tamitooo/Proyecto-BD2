import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchNearbyStores } from '../api';
import type { NearbyStore } from '../types';
import './tiendas.css';

declare global {
  interface Window {
    L?: any;
  }
}

interface Props {
  productoId: number;
}

const PUNTOS = [
  { nombre: 'Centro de Lima', lat: -12.0464, lon: -77.0428 },
  { nombre: 'Miraflores', lat: -12.1211, lon: -77.0297 },
  { nombre: 'San Isidro', lat: -12.0975, lon: -77.0365 },
  { nombre: 'Santiago de Surco', lat: -12.146, lon: -76.992 },
  { nombre: 'La Molina', lat: -12.079, lon: -76.942 },
  { nombre: 'Los Olivos', lat: -11.992, lon: -77.07 },
];

export default function TiendasCercanas({ productoId }: Props) {
  const mapEl = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const layerRef = useRef<any>(null);
  const [punto, setPunto] = useState(PUNTOS[0]);
  const [radioKm, setRadioKm] = useState(15);
  const [tiendas, setTiendas] = useState<NearbyStore[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const L = window.L;
    if (!L || !mapEl.current || mapRef.current) return;
    const map = L.map(mapEl.current).setView([punto.lat, punto.lon], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const invalidate = () => map.invalidateSize();
    const timer = window.setTimeout(invalidate, 150);
    window.addEventListener('resize', invalidate);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('resize', invalidate);
      map.remove();
      mapRef.current = null;
    };
    // El mapa se crea una sola vez; el punto se dibuja en el efecto siguiente.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    fetchNearbyStores(productoId, punto.lat, punto.lon, radioKm * 1000)
      .then((respuesta) => {
        if (vigente) setTiendas(respuesta.tiendas);
      })
      .catch((e) => {
        if (!vigente) return;
        setTiendas([]);
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [productoId, punto, radioKm]);

  useEffect(() => {
    const L = window.L;
    if (!L || !layerRef.current || !mapRef.current) return;
    layerRef.current.clearLayers();
    L.circleMarker([punto.lat, punto.lon], {
      radius: 8,
      color: '#0369a1',
      fillColor: '#0369a1',
      fillOpacity: 1,
    })
      .bindPopup('Tu ubicación')
      .addTo(layerRef.current);
    for (const tienda of tiendas) {
      L.marker([tienda.lat, tienda.lon])
        .bindPopup(
          `<strong>${tienda.nombre}</strong><br>${tienda.distrito}<br>` +
            `${(tienda.distancia_m / 1000).toFixed(2)} km · ${tienda.cantidad} u.`,
        )
        .addTo(layerRef.current);
    }
    const puntos: [number, number][] = [
      [punto.lat, punto.lon],
      ...tiendas.map((tienda) => [tienda.lat, tienda.lon] as [number, number]),
    ];
    if (puntos.length > 1) {
      mapRef.current.fitBounds(puntos, { padding: [30, 30], maxZoom: 13 });
    } else {
      mapRef.current.setView([punto.lat, punto.lon], 12);
    }
  }, [tiendas, punto]);

  const sinStock = useMemo(() => !cargando && tiendas.length === 0, [cargando, tiendas]);

  return (
    <section className="panel" aria-labelledby="tiendas-cercanas">
      <h3 id="tiendas-cercanas" className="panel__title">
        Tiendas cercanas
      </h3>
      <p className="panel__hint">
        Tiendas dentro del radio que tienen stock de este producto, con su distancia.
      </p>
      <div className="tiendas__controles">
        <label className="field">
          <span>Tu ubicación</span>
          <select
            className="select"
            value={punto.nombre}
            onChange={(e) => setPunto(PUNTOS.find((p) => p.nombre === e.target.value) ?? PUNTOS[0])}
          >
            {PUNTOS.map((p) => (
              <option key={p.nombre} value={p.nombre}>
                {p.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Radio (km)</span>
          <input
            className="input"
            type="number"
            min={1}
            max={50}
            value={radioKm}
            onChange={(e) => setRadioKm(Math.min(50, Math.max(1, Number(e.target.value))))}
          />
        </label>
      </div>
      <div className="tiendas__cuerpo">
        <div ref={mapEl} className="tiendas__mapa" />
        <div>
          {cargando && <p className="panel__hint">Buscando tiendas…</p>}
          {error && <div className="alert alert--error">{error}</div>}
          {sinStock && (
            <p className="panel__hint">
              Ninguna tienda en {radioKm} km tiene stock de este producto.
            </p>
          )}
          <ul className="tiendas__lista">
            {tiendas.map((tienda) => (
              <li key={tienda.tienda_id} className="tienda-item">
                <div>
                  <strong>{tienda.nombre}</strong>
                  <br />
                  <span className="panel__hint">{tienda.distrito}</span>
                </div>
                <div className="tienda-item__datos">
                  <span>{(tienda.distancia_m / 1000).toFixed(2)} km</span>
                  <span className="chip">{tienda.cantidad} u.</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
