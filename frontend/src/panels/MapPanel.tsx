// Parte 2 (2.2.2): panel de mapa interactivo.
//
// Mapa cartográfico con Leaflet + teselas de OpenStreetMap: zoom, desplazamiento
// (pan) y mapa base. Sobre él se dibujan los puntos de la tabla y se resaltan
// los resultados de las búsquedas espaciales (rango, k-NN y polígono), que el
// backend resuelve con el R-Tree propio.
//
// * Clic en el mapa  -> fija el punto de consulta y la variable de sesión
//   `mi_ubicacion`, para que el SQL del enunciado funcione tal cual:
//   SELECT * FROM t ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10
// * Modo polígono    -> cada clic añade un vértice.
// * El círculo del rango se dibuja en METROS reales (L.circle), no en grados.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { fetchSpatialPoints, isSpatialEndpointMissing, runSpatialQuery } from '../api';
import type {
  LatLon,
  SpatialKind,
  SpatialMetric,
  SpatialPoint,
  SpatialPoints,
  SpatialQueryRequest,
  SpatialQueryResult,
  TableInfo,
} from '../types';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  /** Punto de consulta compartido con el panel SQL como `mi_ubicacion`. */
  myLocation: LatLon;
  onMyLocationChange: (point: LatLon) => void;
}

const LAT_NAMES = ['lat', 'latitud', 'latitude'];
const LON_NAMES = ['lon', 'lng', 'long', 'longitud', 'longitude'];
const MAX_LABELLED = 15;
const MAX_RESULT_ROWS = 25;

/** Una tabla es espacial si tiene un R-Tree o un par de columnas lat/lon. */
function isSpatialTable(table: TableInfo): boolean {
  if (table.indexes.some((index) => index.kind === 'rtree')) return true;
  const columns = new Set(table.schema.columnas.map((column) => String(column[0]).toLowerCase()));
  return LAT_NAMES.some((name) => columns.has(name)) && LON_NAMES.some((name) => columns.has(name));
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatDistance(point: SpatialPoint, unit: string): string | null {
  if (point.distance_m === null || point.distance_m === undefined) return null;
  if (unit !== 'm') return `${point.distance_m.toFixed(5)}°`;
  return point.distance_m >= 1000
    ? `${(point.distance_m / 1000).toFixed(2)} km`
    : `${point.distance_m.toFixed(1)} m`;
}

function pointTooltip(point: SpatialPoint, unit: string): string {
  const parts = [point.label ?? point.rid ?? 'punto', `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`];
  const distance = formatDistance(point, unit);
  if (distance) parts.push(`distancia: ${distance}`);
  return parts.join(' · ');
}

export default function MapPanel({
  tables,
  selectedTable,
  onSelectTable,
  myLocation,
  onMyLocationChange,
}: Props) {
  const spatialTables = useMemo(() => tables.filter(isSpatialTable), [tables]);
  const activeTable =
    selectedTable && spatialTables.some((table) => table.name === selectedTable)
      ? selectedTable
      : spatialTables[0]?.name ?? null;

  const [points, setPoints] = useState<SpatialPoints | null>(null);
  const [loadingPoints, setLoadingPoints] = useState(false);
  const [pointsError, setPointsError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [kind, setKind] = useState<SpatialKind>('range');
  const [radius, setRadius] = useState(5000);
  const [k, setK] = useState(10);
  const [metric, setMetric] = useState<SpatialMetric>('haversine');
  const [polygon, setPolygon] = useState<LatLon[]>([]);

  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [result, setResult] = useState<SpatialQueryResult | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);

  const mapHost = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const baseLayer = useRef<L.LayerGroup | null>(null);
  const overlayLayer = useRef<L.LayerGroup | null>(null);
  const fittedFor = useRef<string | null>(null);
  const initialCenter = useRef<LatLon>(myLocation);
  // Los manejadores de Leaflet se registran una sola vez: leen el estado
  // actual a través de esta referencia.
  const clickState = useRef({ kind, onMyLocationChange });
  useEffect(() => {
    clickState.current = { kind, onMyLocationChange };
  }, [kind, onMyLocationChange]);

  // ----------------------------------------------------- crear el mapa (1 vez)
  useEffect(() => {
    if (!mapHost.current || mapRef.current) return;
    const start = initialCenter.current;
    const map = L.map(mapHost.current, { preferCanvas: true, zoomControl: true }).setView(
      [start.lat, start.lon],
      11,
    );
    const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; colaboradores de OpenStreetMap',
    });
    tiles.on('tileerror', () => setTilesFailed(true));
    tiles.addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    baseLayer.current = L.layerGroup().addTo(map);
    overlayLayer.current = L.layerGroup().addTo(map);
    map.on('click', (event: L.LeafletMouseEvent) => {
      const point = { lat: event.latlng.lat, lon: event.latlng.lng };
      if (clickState.current.kind === 'polygon') {
        setPolygon((current) => [...current, point]);
      } else {
        clickState.current.onMyLocationChange(point);
      }
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ------------------------------------------------------- cargar los puntos
  useEffect(() => {
    if (!activeTable) return;
    let cancelled = false;
    // Los reinicios de estado van en una microtarea: no se llama a setState
    // de forma síncrona dentro del efecto (evita renders en cascada).
    queueMicrotask(() => {
      if (cancelled) return;
      setLoadingPoints(true);
      setPointsError(null);
      setResult(null);
      setSearchError(null);
    });
    fetchSpatialPoints(activeTable)
      .then((data) => {
        if (!cancelled) setPoints(data);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPoints(null);
        setPointsError(
          isSpatialEndpointMissing(error)
            ? `El backend espacial no responde (GET /api/spatial/points). ${errorText(error)}`
            : errorText(error),
        );
      })
      .finally(() => {
        if (!cancelled) setLoadingPoints(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTable, reloadToken]);

  const hitByRid = useMemo(() => {
    const map = new Map<string, SpatialPoint>();
    for (const point of result?.points ?? []) if (point.rid) map.set(point.rid, point);
    return map;
  }, [result]);
  const unit = result?.distance_unit ?? 'm';
  const shownPoints = activeTable ? points : null;

  // ---------------------------------------------- capa base: puntos de tabla
  useEffect(() => {
    const map = mapRef.current;
    const layer = baseLayer.current;
    if (!map || !layer) return;
    layer.clearLayers();
    const all = shownPoints?.points ?? [];
    for (const point of all) {
      const hit = hitByRid.get(point.rid);
      L.circleMarker([point.lat, point.lon], {
        radius: hit ? 7 : 4,
        color: hit ? '#b45309' : '#1d4ed8',
        weight: hit ? 2 : 1,
        fillColor: hit ? '#f59e0b' : '#3b82f6',
        fillOpacity: result && !hit ? 0.25 : 0.85,
      })
        .bindTooltip(pointTooltip(hit ?? point, unit))
        .addTo(layer);
    }
    // Resultados cuyo RID no está en la lista cargada (la tabla cambió).
    for (const point of result?.points ?? []) {
      if (point.rid && all.some((p) => p.rid === point.rid)) continue;
      L.circleMarker([point.lat, point.lon], {
        radius: 7,
        color: '#b45309',
        weight: 2,
        fillColor: '#f59e0b',
        fillOpacity: 0.9,
      })
        .bindTooltip(pointTooltip(point, unit))
        .addTo(layer);
    }
    // Encuadre automático sólo al cambiar de tabla (no al buscar).
    if (all.length > 0 && fittedFor.current !== shownPoints?.table) {
      fittedFor.current = shownPoints?.table ?? null;
      map.fitBounds(L.latLngBounds(all.map((point) => [point.lat, point.lon] as [number, number])), {
        padding: [24, 24],
        maxZoom: 15,
      });
    }
  }, [shownPoints, hitByRid, result, unit]);

  // ------------------------------- capa superior: consulta y su resaltado
  useEffect(() => {
    const layer = overlayLayer.current;
    if (!layer) return;
    layer.clearLayers();
    const origin: [number, number] = [myLocation.lat, myLocation.lon];

    if (kind === 'range' && radius > 0) {
      L.circle(origin, {
        radius,
        color: '#dc2626',
        weight: 2,
        fillOpacity: 0.06,
        dashArray: result ? undefined : '6 6',
        interactive: false,
      }).addTo(layer);
    }
    if (kind === 'polygon' && polygon.length > 0) {
      const vertices = polygon.map((p) => [p.lat, p.lon] as [number, number]);
      if (polygon.length >= 3) {
        L.polygon(vertices, { color: '#7c3aed', weight: 2, fillOpacity: 0.08, interactive: false }).addTo(
          layer,
        );
      } else {
        L.polyline(vertices, { color: '#7c3aed', weight: 2, dashArray: '4 4', interactive: false }).addTo(
          layer,
        );
      }
      polygon.forEach((p, index) =>
        L.circleMarker([p.lat, p.lon], { radius: 4, color: '#7c3aed', fillOpacity: 1 })
          .bindTooltip(`vértice ${index + 1}`)
          .addTo(layer),
      );
    }
    if (kind === 'knn' && result) {
      result.points.forEach((point, index) => {
        L.polyline([origin, [point.lat, point.lon]], {
          color: '#b45309',
          weight: 1,
          opacity: 0.7,
          interactive: false,
        }).addTo(layer);
        if (index < MAX_LABELLED) {
          L.marker([point.lat, point.lon], {
            icon: L.divIcon({ className: 'map__rank', html: String(index + 1), iconSize: [18, 18] }),
            interactive: false,
          }).addTo(layer);
        }
      });
    }
    if (kind !== 'polygon') {
      L.circleMarker(origin, {
        radius: 7,
        color: '#111827',
        weight: 3,
        fillColor: '#ffffff',
        fillOpacity: 1,
      })
        .bindTooltip(`mi_ubicacion = POINT(${myLocation.lat.toFixed(5)}, ${myLocation.lon.toFixed(5)})`)
        .addTo(layer);
    }
  }, [kind, radius, polygon, myLocation, result]);

  // ---------------------------------------------------------------- buscar
  const search = useCallback(async () => {
    if (!activeTable) return;
    if (kind === 'range' && !(radius > 0)) {
      setSearchError('El radio debe ser mayor que 0 (en metros).');
      return;
    }
    if (kind === 'knn' && !(k >= 1)) {
      setSearchError('k debe ser un entero mayor o igual que 1.');
      return;
    }
    if (kind === 'polygon' && polygon.length < 3) {
      setSearchError('Haz clic en el mapa para marcar al menos 3 vértices del polígono.');
      return;
    }
    const body: SpatialQueryRequest = {
      table: activeTable,
      kind,
      lat: myLocation.lat,
      lon: myLocation.lon,
      metric,
    };
    if (kind === 'range') body.radius_m = radius;
    if (kind === 'knn') body.k = Math.round(k);
    if (kind === 'polygon') body.polygon = polygon.map((p): [number, number] => [p.lat, p.lon]);

    setSearching(true);
    setSearchError(null);
    try {
      const data = await runSpatialQuery(body);
      if (!data.success) {
        setResult(null);
        setSearchError(data.error ?? 'La búsqueda espacial no pudo completarse.');
        return;
      }
      setResult(data);
    } catch (error) {
      setResult(null);
      setSearchError(errorText(error));
    } finally {
      setSearching(false);
    }
  }, [activeTable, kind, radius, k, metric, polygon, myLocation]);

  const hits = result?.points ?? [];

  return (
    <div className="panel">
      <h2 className="panel__title">Panel de mapa</h2>
      <p className="panel__hint">
        Mapa interactivo (Leaflet + OpenStreetMap): rueda o botones para el zoom, arrastrar para
        desplazarse. Haz clic para fijar <code>mi_ubicacion</code>; en modo polígono cada clic añade un
        vértice. Los resultados del R-Tree se resaltan en naranja.
      </p>

      {spatialTables.length === 0 ? (
        <div className="alert alert--ok">
          No hay tablas espaciales. Crea una con columnas <code>lat</code>/<code>lon</code> y su índice:
          <code> CREATE INDEX idx_geo ON tabla (lat, lon) USING RTREE</code>.
        </div>
      ) : (
        <div className="map__controls">
          <label className="map__field">
            Tabla espacial
            <select
              className="select"
              value={activeTable ?? ''}
              onChange={(event) => onSelectTable(event.target.value)}
            >
              {spatialTables.map((table) => (
                <option key={table.name} value={table.name}>
                  {table.name}
                  {table.indexes.some((index) => index.kind === 'rtree') ? ' (R-Tree)' : ' (sin índice)'}
                </option>
              ))}
            </select>
          </label>

          <label className="map__field">
            Modo
            <select
              className="select"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as SpatialKind);
                setResult(null);
              }}
            >
              <option value="range">Rango (radio)</option>
              <option value="knn">k-NN (k vecinos)</option>
              <option value="polygon">Polígono (clics)</option>
            </select>
          </label>

          {kind === 'range' && (
            <label className="map__field">
              Radio (m)
              <input
                className="input"
                type="number"
                min={1}
                step={100}
                value={radius}
                onChange={(event) => setRadius(Number(event.target.value))}
              />
            </label>
          )}
          {kind === 'knn' && (
            <label className="map__field">
              k
              <input
                className="input"
                type="number"
                min={1}
                step={1}
                value={k}
                onChange={(event) => setK(Number(event.target.value))}
              />
            </label>
          )}
          {kind !== 'polygon' && (
            <label className="map__field">
              Métrica
              <select
                className="select"
                value={metric}
                onChange={(event) => setMetric(event.target.value as SpatialMetric)}
              >
                <option value="haversine">Geodésica (Haversine)</option>
                <option value="euclidean">Euclidiana (grados)</option>
              </select>
            </label>
          )}

          <div className="map__buttons">
            <button
              type="button"
              className="button button--primary"
              disabled={searching || loadingPoints}
              onClick={() => void search()}
            >
              {searching ? 'Buscando…' : 'Buscar'}
            </button>
            {kind === 'polygon' && (
              <button type="button" className="button" onClick={() => setPolygon([])}>
                Borrar vértices
              </button>
            )}
            <button type="button" className="button" onClick={() => setReloadToken((v) => v + 1)}>
              Recargar puntos
            </button>
            <button type="button" className="button" disabled={!result} onClick={() => setResult(null)}>
              Limpiar resaltado
            </button>
          </div>
        </div>
      )}

      {metric === 'euclidean' && kind === 'range' && (
        <p className="panel__hint">
          Con métrica Euclidiana el radio en metros se convierte a grados (÷ 111 320) antes de
          consultar, para que el círculo dibujado y la búsqueda coincidan.
        </p>
      )}
      {loadingPoints && <p className="panel__hint">Cargando puntos de {activeTable}…</p>}
      {pointsError && <div className="alert alert--error">{pointsError}</div>}
      {searchError && <div className="alert alert--error">{searchError}</div>}
      {tilesFailed && (
        <div className="alert alert--error">
          No se pudieron descargar las teselas de OpenStreetMap (¿sin Internet?). Los puntos y las
          búsquedas siguen funcionando sobre el lienzo vacío.
        </div>
      )}

      <div className="map__meta">
        <span className="map__pill">
          mi_ubicacion: <strong>{myLocation.lat.toFixed(5)}, {myLocation.lon.toFixed(5)}</strong>
        </span>
        {shownPoints && (
          <span className="map__pill">
            Puntos: <strong>{shownPoints.points.length}</strong>
            {shownPoints.lat_column && ` (${shownPoints.lat_column}, ${shownPoints.lon_column})`}
          </span>
        )}
        {result && (
          <>
            <span className="map__pill">
              Plan: <strong>{result.access_path ?? '—'}</strong>
            </span>
            <span className="map__pill">
              Índice: <strong>{result.used_indexes.join(', ') || 'ninguno (escaneo)'}</strong>
            </span>
            <span className="map__pill">
              Resultados: <strong>{hits.length}</strong> · {result.execution_time_ms.toFixed(2)} ms
            </span>
          </>
        )}
      </div>

      <div ref={mapHost} className="map__leaflet" aria-label="Mapa interactivo espacial" />

      {result && hits.length > 0 && (
        <div className="scroll map__results">
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>Etiqueta</th>
                <th>Latitud</th>
                <th>Longitud</th>
                <th>Distancia</th>
              </tr>
            </thead>
            <tbody>
              {hits.slice(0, MAX_RESULT_ROWS).map((point, index) => (
                <tr
                  key={`${point.rid}-${index}`}
                  onClick={() => mapRef.current?.setView([point.lat, point.lon], 16)}
                  className="map__result-row"
                >
                  <td>{index + 1}</td>
                  <td>{point.label ?? point.rid}</td>
                  <td>{point.lat.toFixed(5)}</td>
                  <td>{point.lon.toFixed(5)}</td>
                  <td>{formatDistance(point, unit) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {hits.length > MAX_RESULT_ROWS && (
            <p className="panel__hint">
              Mostrando {MAX_RESULT_ROWS} de {hits.length} resultados (todos están resaltados en el mapa).
            </p>
          )}
        </div>
      )}
    </div>
  );
}
