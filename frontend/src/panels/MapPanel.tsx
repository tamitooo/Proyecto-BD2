// Issue 24 (Parte 2): panel de mapa.
//
// El mapa se dibuja con React + SVG, sin Leaflet ni ninguna otra dependencia:
// la proyección es equirectangular (x = longitud, y = latitud invertida), que
// es exacta para la ventana que se usa aquí (decenas de km) y no necesita
// tiles ni red. Los resultados de una búsqueda espacial se resaltan encima.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchSpatialPoints, isSpatialEndpointMissing, runSpatialQuery } from '../api';
import type {
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
}

/* Dimensiones del viewBox: el SVG se escala al ancho del panel y todas las
   coordenadas se calculan en estas unidades. */
const VIEW_W = 760;
const VIEW_H = 460;
const PAD = 34;

/** ~200 m: evita una escala infinita con un solo punto o puntos coincidentes. */
const MIN_SPAN_DEG = 0.002;
const METERS_PER_DEG_LAT = 111320;
/** Mismo suelo que usa el backend (spatial/geo.py: meters_per_degree_lon). */
const COS_LAT_FLOOR = 0.01;

/** Pasos "redondos" para la graticule, de ~50 m a 10°. */
const GRID_STEPS = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10];

const MAX_GRID_LINES = 24;
const MAX_LABELLED_POINTS = 14;
const MAX_RESULT_ROWS = 25;

interface Extent {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
}

interface LatLon {
  lat: number;
  lon: number;
}

interface Projection extends Extent {
  cosMid: number;
  /** Unidades de viewBox por grado de latitud. */
  scale: number;
  /** viewBox x del borde minLon y viewBox y del borde maxLat. */
  x0: number;
  y0: number;
}

/** Evento de clic reducido a lo que necesita el mapa. */
interface MapClickEvent {
  currentTarget: SVGSVGElement;
  clientX: number;
  clientY: number;
}

/** Parámetros de la última búsqueda ejecutada con éxito. */
interface ExecutedSearch {
  kind: SpatialKind;
  lat: number;
  lon: number;
  radius: number;
  k: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Abre la ventana si es degenerada y reparte el contenido dentro del viewBox. */
function buildProjection(extent: Extent): Projection {
  let { minLat, maxLat, minLon, maxLon } = extent;
  if (maxLat - minLat < MIN_SPAN_DEG) {
    const mid = (minLat + maxLat) / 2;
    minLat = mid - MIN_SPAN_DEG / 2;
    maxLat = mid + MIN_SPAN_DEG / 2;
  }
  if (maxLon - minLon < MIN_SPAN_DEG) {
    const mid = (minLon + maxLon) / 2;
    minLon = mid - MIN_SPAN_DEG / 2;
    maxLon = mid + MIN_SPAN_DEG / 2;
  }
  // cos(lat) comprime las longitudes para que el dibujo no salga estirado:
  // es el término equirectangular habitual.
  const midLat = (minLat + maxLat) / 2;
  const cosMid = Math.max(Math.cos((midLat * Math.PI) / 180), 1e-3);
  const rawW = (maxLon - minLon) * cosMid;
  const rawH = maxLat - minLat;
  const availableW = VIEW_W - 2 * PAD;
  const availableH = VIEW_H - 2 * PAD;
  const scale = Math.min(availableW / rawW, availableH / rawH);
  return {
    minLat,
    maxLat,
    minLon,
    maxLon,
    cosMid,
    scale,
    x0: PAD + (availableW - rawW * scale) / 2,
    y0: PAD + (availableH - rawH * scale) / 2,
  };
}

function projectX(projection: Projection, lon: number): number {
  return projection.x0 + (lon - projection.minLon) * projection.cosMid * projection.scale;
}

function projectY(projection: Projection, lat: number): number {
  return projection.y0 + (projection.maxLat - lat) * projection.scale;
}

/** Inversa de projectX/projectY: se usa al hacer clic sobre el mapa. */
function unproject(projection: Projection, x: number, y: number): LatLon {
  return {
    lat: projection.maxLat - (y - projection.y0) / projection.scale,
    lon: projection.minLon + (x - projection.x0) / (projection.cosMid * projection.scale),
  };
}

/** Metros → grados: dlat = m / 111320, dlon = m / (111320 · cos(lat)). */
function metersToDegrees(metres: number, lat: number): { dLat: number; dLon: number } {
  const dLat = metres / METERS_PER_DEG_LAT;
  const cosLat = Math.max(Math.cos((lat * Math.PI) / 180), COS_LAT_FLOOR);
  return { dLat, dLon: metres / (METERS_PER_DEG_LAT * cosLat) };
}

/** Paso de rejilla que deja entre 3 y 6 líneas en el eje. */
function gridStep(span: number): number {
  const target = span / 5;
  return GRID_STEPS.find((step) => step >= target) ?? GRID_STEPS[GRID_STEPS.length - 1];
}

function decimalsFor(step: number): number {
  if (step >= 1) return 0;
  if (step >= 0.1) return 1;
  if (step >= 0.01) return 2;
  if (step >= 0.001) return 3;
  return 4;
}

/** Valores de tick múltiplos de `step` que caen dentro de [min, max]. */
function ticksBetween(min: number, max: number, step: number): number[] {
  const first = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let value = first; value <= max + step / 1000 && out.length < MAX_GRID_LINES; value += step) {
    out.push(value);
  }
  return out;
}

/** "lat,lon" separados por ';' o saltos de línea → vértices del polígono. */
function parsePolygon(text: string): LatLon[] | null {
  const chunks = text.split(/[;\n]+/).map((chunk) => chunk.trim()).filter(Boolean);
  if (chunks.length < 3) return null;
  const vertices: LatLon[] = [];
  for (const chunk of chunks) {
    const parts = chunk.split(/[\s,]+/).map(Number);
    if (parts.length < 2 || !Number.isFinite(parts[0]) || !Number.isFinite(parts[1])) return null;
    vertices.push({ lat: parts[0], lon: parts[1] });
  }
  return vertices;
}

function formatDistance(point: SpatialPoint, unit: string): string | null {
  if (point.distance_m === null) return null;
  if (unit === 'km') return `${point.distance_m.toFixed(3)} km`;
  return point.distance_m >= 1000
    ? `${(point.distance_m / 1000).toFixed(2)} km`
    : `${point.distance_m.toFixed(1)} m`;
}

/** Texto del tooltip nativo (<title>) de cada punto. */
function pointTitle(point: SpatialPoint, unit: string): string {
  const parts = [point.label ?? point.rid ?? 'punto'];
  parts.push(`${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`);
  const distance = formatDistance(point, unit);
  if (distance !== null) parts.push(`distancia: ${distance}`);
  if (point.rid) parts.push(`RID ${point.rid}`);
  return parts.join(' · ');
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Centro por defecto: el del bounding box reportado, o el primer punto. */
function centroidOf(data: SpatialPoints): LatLon | null {
  if (data.bounds) {
    return {
      lat: (data.bounds.min_lat + data.bounds.max_lat) / 2,
      lon: (data.bounds.min_lon + data.bounds.max_lon) / 2,
    };
  }
  const first = data.points[0];
  return first ? { lat: first.lat, lon: first.lon } : null;
}

export default function MapPanel({ tables, selectedTable, onSelectTable }: Props) {
  const [points, setPoints] = useState<SpatialPoints | null>(null);
  const [loadingPoints, setLoadingPoints] = useState(false);
  const [pointsError, setPointsError] = useState<string | null>(null);
  const [endpointMissing, setEndpointMissing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [kind, setKind] = useState<SpatialKind>('range');
  const [radius, setRadius] = useState(5000);
  const [k, setK] = useState(10);
  const [metric, setMetric] = useState<SpatialMetric>('haversine');
  const [polygonText, setPolygonText] = useState('');

  const [center, setCenter] = useState<LatLon | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [result, setResult] = useState<SpatialQueryResult | null>(null);
  // El resaltado se dibuja con los parámetros que se enviaron, no con los del
  // formulario: si el usuario mueve el punto después de buscar, el círculo y
  // las líneas del k-NN siguen describiendo los resultados que se ven.
  const [executed, setExecuted] = useState<ExecutedSearch | null>(null);
  const [selectedRid, setSelectedRid] = useState<string | null>(null);

  // Permite saber si el efecto se dispara por cambio de tabla o por "Recargar
  // puntos": al recargar la misma tabla el resaltado de la búsqueda se conserva.
  const loadedTable = useRef<string | null>(null);

  useEffect(() => {
    if (loadedTable.current !== selectedTable) {
      loadedTable.current = selectedTable;
      setResult(null);
      setExecuted(null);
      setSearchError(null);
      setSelectedRid(null);
    }
    if (!selectedTable) {
      setPoints(null);
      setPointsError(null);
      setCenter(null);
      return;
    }
    let cancelled = false;
    setLoadingPoints(true);
    setPointsError(null);
    setEndpointMissing(false);
    fetchSpatialPoints(selectedTable)
      .then((data) => {
        if (cancelled) return;
        setPoints(data);
        setCenter(centroidOf(data));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPoints(null);
        setCenter(null);
        setEndpointMissing(isSpatialEndpointMissing(error));
        setPointsError(errorText(error));
      })
      .finally(() => {
        if (cancelled) return;
        setLoadingPoints(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTable, reloadToken]);

  const polygon = useMemo(() => parsePolygon(polygonText), [polygonText]);
  const polygonInvalid = polygonText.trim().length > 0 && polygon === null;

  // La ventana abarca los puntos, el punto de consulta (con su radio si aplica)
  // y el polígono, para que todo lo dibujado quepa en el viewBox.
  const projection = useMemo(() => {
    const lats: number[] = [];
    const lons: number[] = [];
    const add = (lat: number, lon: number) => {
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        lats.push(lat);
        lons.push(lon);
      }
    };
    for (const point of points?.points ?? []) add(point.lat, point.lon);
    if (center) {
      add(center.lat, center.lon);
      if (kind === 'range' && radius > 0) {
        const { dLat, dLon } = metersToDegrees(radius, center.lat);
        add(center.lat - dLat, center.lon - dLon);
        add(center.lat + dLat, center.lon + dLon);
      }
    }
    if (executed) {
      add(executed.lat, executed.lon);
      if (executed.kind === 'range' && executed.radius > 0) {
        const { dLat, dLon } = metersToDegrees(executed.radius, executed.lat);
        add(executed.lat - dLat, executed.lon - dLon);
        add(executed.lat + dLat, executed.lon + dLon);
      }
    }
    for (const vertex of polygon ?? []) add(vertex.lat, vertex.lon);
    if (lats.length === 0) return null;
    let minLat = lats[0];
    let maxLat = lats[0];
    let minLon = lons[0];
    let maxLon = lons[0];
    for (let index = 1; index < lats.length; index += 1) {
      minLat = Math.min(minLat, lats[index]);
      maxLat = Math.max(maxLat, lats[index]);
      minLon = Math.min(minLon, lons[index]);
      maxLon = Math.max(maxLon, lons[index]);
    }
    return buildProjection({ minLat, maxLat, minLon, maxLon });
  }, [points, center, kind, radius, polygon, executed]);

  const hits = result?.points ?? [];
  const distanceUnit = result?.distance_unit ?? 'm';

  // Geometría del resaltado: describe la búsqueda ejecutada; si todavía no hay
  // resultados, es una vista previa de lo que se va a buscar.
  const drawnKind: SpatialKind = executed?.kind ?? kind;
  const drawnOrigin: LatLon | null = executed
    ? { lat: executed.lat, lon: executed.lon }
    : center;
  const drawnRadius = executed ? executed.radius : radius;
  // El formulario ya no coincide con los resultados visibles.
  const stale =
    executed !== null &&
    (executed.kind !== kind ||
      executed.lat !== center?.lat ||
      executed.lon !== center?.lon ||
      (kind === 'range' && executed.radius !== radius) ||
      (kind === 'knn' && executed.k !== Math.round(k)));

  const hitByRid = useMemo(() => {
    const map = new Map<string, SpatialPoint>();
    for (const point of result?.points ?? []) {
      if (point.rid) map.set(point.rid, point);
    }
    return map;
  }, [result]);

  // Resultados cuyo RID no está en la lista cargada (la tabla cambió entre la
  // carga y la búsqueda): se dibujan igualmente para no perder el resaltado.
  const extraHits = useMemo(() => {
    const known = new Set((points?.points ?? []).map((point) => point.rid));
    return (result?.points ?? []).filter((point) => !point.rid || !known.has(point.rid));
  }, [result, points]);

  const selectedPoint = useMemo(() => {
    if (!selectedRid) return null;
    return (
      hitByRid.get(selectedRid) ??
      (points?.points ?? []).find((point) => point.rid === selectedRid) ??
      null
    );
  }, [selectedRid, hitByRid, points]);

  const search = useCallback(async () => {
    if (!selectedTable) {
      setSearchError('Selecciona una tabla con columnas espaciales.');
      return;
    }
    if (!center) {
      setSearchError('Haz clic sobre el mapa para fijar el punto de consulta.');
      return;
    }
    if (kind === 'range' && (!Number.isFinite(radius) || radius <= 0)) {
      setSearchError('El radio debe ser un número mayor que 0 (en metros).');
      return;
    }
    if (kind === 'knn' && (!Number.isFinite(k) || k < 1)) {
      setSearchError('k debe ser un número mayor o igual que 1.');
      return;
    }
    if (polygonInvalid) {
      setSearchError('El polígono no es válido: usa al menos 3 vértices "lat,lon" separados por ";".');
      return;
    }
    const body: SpatialQueryRequest = {
      table: selectedTable,
      kind,
      lat: center.lat,
      lon: center.lon,
      metric,
    };
    // El polígono viaja con la petición en ambos modos: el backend decide si lo
    // usa como filtro de intersección además del radio o de los k vecinos.
    if (polygon) body.polygon = polygon.map((vertex): [number, number] => [vertex.lat, vertex.lon]);
    if (kind === 'range') {
      body.radius_m = radius;
    } else {
      body.k = Math.round(k);
    }
    setSearching(true);
    setSearchError(null);
    try {
      const data = await runSpatialQuery(body);
      if (!data.success) {
        setResult(null);
        setExecuted(null);
        setSearchError(data.error ?? 'La búsqueda espacial no pudo completarse.');
        return;
      }
      setResult(data);
      setExecuted({
        kind: body.kind,
        lat: body.lat,
        lon: body.lon,
        radius: body.radius_m ?? radius,
        k: body.k ?? Math.round(k),
      });
      setSelectedRid(null);
    } catch (error) {
      setResult(null);
      setExecuted(null);
      setSearchError(
        isSpatialEndpointMissing(error)
          ? `El backend espacial aún no está disponible (POST /api/spatial/query). ${errorText(error)}`
          : errorText(error),
      );
    } finally {
      setSearching(false);
    }
  }, [selectedTable, center, kind, radius, k, metric, polygon, polygonInvalid]);

  const handleMapClick = (event: MapClickEvent) => {
    if (!projection) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    // preserveAspectRatio="xMidYMid meet" (por defecto): hay que deshacer el
    // escalado uniforme y el centrado antes de invertir la proyección.
    const fit = Math.min(rect.width / VIEW_W, rect.height / VIEW_H);
    const viewX = (event.clientX - rect.left - (rect.width - VIEW_W * fit) / 2) / fit;
    const viewY = (event.clientY - rect.top - (rect.height - VIEW_H * fit) / 2) / fit;
    const { lat, lon } = unproject(projection, viewX, viewY);
    setCenter({ lat: clamp(lat, -90, 90), lon: clamp(lon, -180, 180) });
    setSelectedRid(null);
  };

  const lonStep = projection ? gridStep(projection.maxLon - projection.minLon) : 1;
  const latStep = projection ? gridStep(projection.maxLat - projection.minLat) : 1;
  const lonTicks = projection ? ticksBetween(projection.minLon, projection.maxLon, lonStep) : [];
  const latTicks = projection ? ticksBetween(projection.minLat, projection.maxLat, latStep) : [];

  const tableSelector = (
    <label className="map__field">
      Tabla espacial
      <select
        className="select"
        value={selectedTable ?? ''}
        onChange={(event) => onSelectTable(event.target.value)}
      >
        <option value="" disabled>Elegir tabla…</option>
        {tables.map((table) => (
          <option key={table.name} value={table.name}>{table.name}</option>
        ))}
      </select>
    </label>
  );

  if (!selectedTable) {
    return (
      <div className="panel">
        <h2 className="panel__title">Panel de mapa</h2>
        <p className="panel__hint">
          Visualiza los puntos (latitud, longitud) de una tabla espacial y resalta ahí mismo los
          resultados de las búsquedas por rango, k-NN y polígono sobre el R-Tree.
        </p>
        {tableSelector}
        <p className="panel__hint">Selecciona una tabla en el panel de archivos.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2 className="panel__title">Panel de mapa</h2>
      <p className="panel__hint">
        Proyección equirectangular dibujada con SVG y sin dependencias. Haz clic sobre el mapa para
        fijar el punto de consulta y pulsa «Buscar» para resaltar los resultados. El polígono es
        opcional: si lo indicas, se envía con la búsqueda y se dibuja su contorno.
      </p>

      <div className="map__controls">
        {tableSelector}

        <label className="map__field">
          Modo
          <select
            className="select"
            value={kind}
            onChange={(event) => setKind(event.target.value as SpatialKind)}
          >
            <option value="range">Rango (radio)</option>
            <option value="knn">k-NN (k vecinos)</option>
          </select>
        </label>

        <label className="map__field">
          Radio (m)
          <input
            className="input"
            type="number"
            min={1}
            step={100}
            value={radius}
            disabled={kind !== 'range'}
            onChange={(event) => setRadius(Number(event.target.value))}
          />
        </label>

        <label className="map__field">
          k
          <input
            className="input"
            type="number"
            min={1}
            step={1}
            value={k}
            disabled={kind !== 'knn'}
            onChange={(event) => setK(Number(event.target.value))}
          />
        </label>

        <label className="map__field">
          Métrica
          <select
            className="select"
            value={metric}
            onChange={(event) => setMetric(event.target.value as SpatialMetric)}
          >
            <option value="haversine">Geodésica (Haversine)</option>
            <option value="euclidean">Euclidiana</option>
          </select>
        </label>

        <label className="map__field map__field--wide">
          Polígono opcional (lat,lon; …)
          <input
            className="input"
            type="text"
            value={polygonText}
            placeholder="-12.05,-77.05; -12.05,-77.00; -12.10,-77.02"
            onChange={(event) => setPolygonText(event.target.value)}
          />
        </label>

        <div className="map__buttons">
          <button
            type="button"
            className="button button--primary"
            disabled={searching || loadingPoints}
            onClick={() => void search()}
          >
            {searching ? 'Buscando…' : 'Buscar'}
          </button>
          <button
            type="button"
            className="button"
            disabled={loadingPoints}
            onClick={() => setReloadToken((value) => value + 1)}
          >
            Recargar puntos
          </button>
          <button
            type="button"
            className="button"
            disabled={!result}
            onClick={() => {
              setResult(null);
              setExecuted(null);
              setSearchError(null);
              setSelectedRid(null);
            }}
          >
            Limpiar resaltado
          </button>
        </div>
      </div>

      {polygonInvalid && (
        <p className="panel__hint">
          Polígono ignorado: usa al menos 3 vértices «lat,lon» separados por «;».
        </p>
      )}

      {loadingPoints && <p className="panel__hint">Cargando puntos de {selectedTable}…</p>}

      {pointsError && (
        <div className="alert alert--error">
          {endpointMissing ? (
            <>
              <strong>El backend espacial aún no está disponible</strong> (GET
              <code> /api/spatial/points/{selectedTable}</code>). Los demás paneles siguen
              funcionando.
              <div className="map__raw-error">{pointsError}</div>
            </>
          ) : (
            <>
              <strong>No se pudieron cargar los puntos de {selectedTable}:</strong> {pointsError}
            </>
          )}
        </div>
      )}

      {!pointsError && points && points.points.length === 0 && (
        <div className="alert alert--ok">
          La tabla <strong>{points.table}</strong> se leyó correctamente
          {points.lat_column && points.lon_column
            ? ` (columnas espaciales: ${points.lat_column}, ${points.lon_column})`
            : ''}
          , pero no tiene filas con coordenadas válidas: no hay nada que dibujar.
        </div>
      )}

      {!pointsError && points && points.points.length > 0 && projection && (
        <>
          <div className="map__meta">
            <span className="map__pill">Tabla: <strong>{points.table}</strong></span>
            <span className="map__pill">Puntos: <strong>{points.points.length}</strong></span>
            {points.lat_column && (
              <span className="map__pill">
                Columnas: <strong>{points.lat_column}, {points.lon_column}</strong>
              </span>
            )}
            {points.label_column && (
              <span className="map__pill">Etiqueta: <strong>{points.label_column}</strong></span>
            )}
            <span className="map__pill">
              Ventana:{' '}
              <strong>
                {projection.minLat.toFixed(4)}…{projection.maxLat.toFixed(4)} lat ·{' '}
                {projection.minLon.toFixed(4)}…{projection.maxLon.toFixed(4)} lon
              </strong>
            </span>
          </div>

          <div className="map__frame">
            <svg
              className="map__svg"
              viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
              role="img"
              aria-label={`Mapa de puntos de la tabla ${points.table}`}
              onClick={handleMapClick}
            >
              <rect className="map__background" x={0} y={0} width={VIEW_W} height={VIEW_H} />

              {/* Graticule con etiquetas de latitud y longitud */}
              <g className="map__grid">
                {lonTicks.map((lon) => (
                  <line
                    key={`lon-${lon}`}
                    x1={projectX(projection, lon)}
                    y1={PAD}
                    x2={projectX(projection, lon)}
                    y2={VIEW_H - PAD}
                  />
                ))}
                {latTicks.map((lat) => (
                  <line
                    key={`lat-${lat}`}
                    x1={PAD}
                    y1={projectY(projection, lat)}
                    x2={VIEW_W - PAD}
                    y2={projectY(projection, lat)}
                  />
                ))}
              </g>
              <g className="map__axis">
                {lonTicks.map((lon) => (
                  <text
                    key={`lon-label-${lon}`}
                    className="map__axis-value"
                    x={projectX(projection, lon)}
                    y={VIEW_H - PAD + 14}
                    textAnchor="middle"
                  >
                    {lon.toFixed(decimalsFor(lonStep))}
                  </text>
                ))}
                {latTicks.map((lat) => (
                  // Etiqueta dentro del área de dibujo: los valores con muchos
                  // decimales se saldrían del viewBox si fueran a la izquierda.
                  <text
                    key={`lat-label-${lat}`}
                    className="map__axis-value"
                    x={PAD + 4}
                    y={projectY(projection, lat) + 3}
                    textAnchor="start"
                  >
                    {lat.toFixed(decimalsFor(latStep))}
                  </text>
                ))}
                <text className="map__axis-title" x={VIEW_W - PAD} y={VIEW_H - 6} textAnchor="end">
                  longitud (°)
                </text>
                <text className="map__axis-title" x={6} y={14}>latitud (°)</text>
              </g>

              {/* Polígono de intersección, si se indicó uno */}
              {polygon && polygon.length >= 3 && (
                <polygon
                  className="map__polygon"
                  points={polygon
                    .map((vertex) => `${projectX(projection, vertex.lon)},${projectY(projection, vertex.lat)}`)
                    .join(' ')}
                />
              )}

              {/* Círculo con el radio solicitado (modo rango) */}
              {drawnKind === 'range' && drawnOrigin && drawnRadius > 0 && (
                <g className="map__radius">
                  <circle
                    cx={projectX(projection, drawnOrigin.lon)}
                    cy={projectY(projection, drawnOrigin.lat)}
                    r={metersToDegrees(drawnRadius, drawnOrigin.lat).dLat * projection.scale}
                  />
                  <title>{`Radio de búsqueda: ${drawnRadius.toFixed(0)} m`}</title>
                </g>
              )}

              {/* Líneas del origen del k-NN a cada vecino */}
              {drawnKind === 'knn' && drawnOrigin && hits.length > 0 && (
                <g className="map__knn">
                  {hits.map((point, index) => (
                    <line
                      key={`knn-${point.rid}-${index}`}
                      x1={projectX(projection, drawnOrigin.lon)}
                      y1={projectY(projection, drawnOrigin.lat)}
                      x2={projectX(projection, point.lon)}
                      y2={projectY(projection, point.lat)}
                    />
                  ))}
                </g>
              )}

              {/* Puntos de la tabla: resaltados si la búsqueda los devolvió */}
              <g className="map__points">
                {(points.points ?? []).map((point, index) => {
                  const hit = hitByRid.get(point.rid);
                  const isHit = hit !== undefined;
                  const selected = selectedRid !== null && point.rid === selectedRid;
                  const classes = [
                    'map__point',
                    isHit ? 'map__point--hit' : result ? 'map__point--dim' : '',
                    selected ? 'map__point--selected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <circle
                      key={`p-${point.rid}-${index}`}
                      className={classes}
                      cx={projectX(projection, point.lon)}
                      cy={projectY(projection, point.lat)}
                      r={isHit ? 6.5 : 4}
                      onClick={(event) => {
                        // Sin stopPropagation el clic también movería el punto de consulta.
                        event.stopPropagation();
                        setSelectedRid(selected ? null : point.rid);
                      }}
                    >
                      <title>{pointTitle(hit ?? point, distanceUnit)}</title>
                    </circle>
                  );
                })}
                {extraHits.map((point, index) => (
                  <circle
                    key={`extra-${point.rid}-${index}`}
                    className="map__point map__point--hit"
                    cx={projectX(projection, point.lon)}
                    cy={projectY(projection, point.lat)}
                    r={6.5}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedRid(point.rid);
                    }}
                  >
                    <title>{pointTitle(point, distanceUnit)}</title>
                  </circle>
                ))}
              </g>

              {/* Etiquetas de los resultados (limitadas para no saturar) */}
              {result && hits.length > 0 && (
                <g className="map__labels">
                  {hits.slice(0, MAX_LABELLED_POINTS).map((point, index) => (
                    <text
                      key={`label-${point.rid}-${index}`}
                      x={projectX(projection, point.lon) + 9}
                      y={projectY(projection, point.lat) - 7}
                    >
                      {point.label ?? point.rid ?? 'punto'}
                    </text>
                  ))}
                </g>
              )}

              {/* Rango (1..k) de cada vecino del k-NN */}
              {drawnKind === 'knn' &&
                drawnOrigin &&
                hits.slice(0, MAX_LABELLED_POINTS).map((point, index) => (
                  <g key={`rank-${point.rid}-${index}`} className="map__rank">
                    <circle
                      cx={projectX(projection, point.lon)}
                      cy={projectY(projection, point.lat)}
                      r={5}
                    />
                    <text
                      x={projectX(projection, point.lon)}
                      y={projectY(projection, point.lat) + 3}
                      textAnchor="middle"
                    >
                      {index + 1}
                    </text>
                  </g>
                ))}

              {/* Punto de consulta: centro del rango u origen del k-NN */}
              {center && (
                <g className="map__query">
                  <line
                    x1={projectX(projection, center.lon) - 10}
                    y1={projectY(projection, center.lat)}
                    x2={projectX(projection, center.lon) + 10}
                    y2={projectY(projection, center.lat)}
                  />
                  <line
                    x1={projectX(projection, center.lon)}
                    y1={projectY(projection, center.lat) - 10}
                    x2={projectX(projection, center.lon)}
                    y2={projectY(projection, center.lat) + 10}
                  />
                  <circle
                    cx={projectX(projection, center.lon)}
                    cy={projectY(projection, center.lat)}
                    r={3.5}
                  />
                  <title>
                    {`Punto de consulta: ${center.lat.toFixed(5)}, ${center.lon.toFixed(5)}`}
                  </title>
                </g>
              )}

              {/* Origen de los resultados cuando el formulario ya cambió */}
              {stale && executed && (
                <g className="map__origin">
                  <circle
                    cx={projectX(projection, executed.lon)}
                    cy={projectY(projection, executed.lat)}
                    r={12}
                  />
                  <title>
                    {`Punto de la búsqueda mostrada: ${executed.lat.toFixed(5)}, ${executed.lon.toFixed(5)}`}
                  </title>
                </g>
              )}
            </svg>
          </div>

          <div className="map__legend">
            <span><i className="map__swatch map__swatch--point" /> punto de la tabla</span>
            <span><i className="map__swatch map__swatch--hit" /> resultado de la búsqueda</span>
            <span><i className="map__swatch map__swatch--query" /> punto de consulta</span>
            {drawnKind === 'range' && (
              <span><i className="map__swatch map__swatch--radius" /> radio solicitado</span>
            )}
            {polygon && <span><i className="map__swatch map__swatch--polygon" /> polígono</span>}
          </div>

          <p className="panel__hint">
            {center
              ? `Punto de consulta: ${center.lat.toFixed(5)}, ${center.lon.toFixed(5)} (haz clic en el mapa para cambiarlo).`
              : 'Haz clic sobre el mapa para fijar el punto de consulta.'}{' '}
            Pasa el cursor por un punto para ver su etiqueta y distancia; pulsa para seleccionarlo.
          </p>
          {stale && (
            <p className="panel__hint">
              El resaltado corresponde a la búsqueda anterior
              {executed?.kind === 'knn'
                ? ` (k-NN con k=${executed.k})`
                : ` (rango de ${executed?.radius ?? 0} m)`}
              : pulsa «Buscar» para recalcular con los valores actuales.
            </p>
          )}
        </>
      )}

      {searchError && (
        <div className="alert alert--error">
          <strong>Búsqueda espacial:</strong> {searchError}
        </div>
      )}

      {result && (
        <>
          <h3 className="panel__subtitle">Evidencia del R-Tree</h3>
          <div className="metrics">
            <div className="metric"><span>Tabla</span><strong>{result.table}</strong></div>
            <div className="metric">
              <span>Modo</span>
              <strong>
                {result.kind === 'knn'
                  ? `k-NN (k=${executed?.k ?? k})`
                  : `Rango (${executed?.radius ?? radius} m)`}
              </strong>
            </div>
            <div className="metric"><span>Métrica</span><strong>{result.metric}</strong></div>
            <div className="metric">
              <span>Ruta de acceso</span><strong>{result.access_path}</strong>
            </div>
            <div className="metric"><span>Resultados</span><strong>{hits.length}</strong></div>
            <div className="metric">
              <span>Tiempo</span><strong>{result.execution_time_ms.toFixed(3)} ms</strong>
            </div>
            {result.candidates_visited !== null && (
              <div className="metric">
                <span>Candidatos visitados</span><strong>{result.candidates_visited}</strong>
              </div>
            )}
          </div>

          <h3 className="panel__subtitle">Índices utilizados</h3>
          {result.used_indexes.length === 0 ? (
            <p className="panel__hint">
              El backend no reportó índices para esta búsqueda ({result.access_path}): puede haberse
              resuelto con un escaneo secuencial sobre los puntos.
            </p>
          ) : (
            <ul className="chips">
              {result.used_indexes.map((index) => <li key={index} className="chip">{index}</li>)}
            </ul>
          )}

          <h3 className="panel__subtitle">
            {result.kind === 'knn'
              ? `${hits.length} vecinos más cercanos`
              : `${hits.length} puntos dentro del radio`}
          </h3>
          {hits.length === 0 ? (
            <p className="panel__hint">
              La búsqueda no devolvió puntos: amplía el radio o mueve el punto de consulta.
            </p>
          ) : (
            <div className="scroll">
              <table className="grid">
                <thead>
                  <tr>
                    {result.kind === 'knn' && <th>#</th>}
                    <th>Etiqueta</th>
                    <th>Latitud</th>
                    <th>Longitud</th>
                    <th>Distancia</th>
                    <th>RID</th>
                  </tr>
                </thead>
                <tbody>
                  {hits.slice(0, MAX_RESULT_ROWS).map((point, index) => (
                    <tr
                      key={`row-${point.rid}-${index}`}
                      className={
                        point.rid === selectedRid ? 'map__row map__row--selected' : 'map__row'
                      }
                      onClick={() => setSelectedRid(point.rid === selectedRid ? null : point.rid)}
                    >
                      {result.kind === 'knn' && <td>{index + 1}</td>}
                      <td>{point.label ?? '—'}</td>
                      <td className="mono">{point.lat.toFixed(5)}</td>
                      <td className="mono">{point.lon.toFixed(5)}</td>
                      <td className="mono">{formatDistance(point, distanceUnit) ?? '—'}</td>
                      <td className="mono">{point.rid || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {hits.length > MAX_RESULT_ROWS && (
                <p className="panel__hint">
                  Se muestran los primeros {MAX_RESULT_ROWS} de {hits.length} resultados; en el mapa
                  están todos.
                </p>
              )}
            </div>
          )}

          {selectedPoint && (
            <>
              <h3 className="panel__subtitle">
                Punto seleccionado: {selectedPoint.label ?? selectedPoint.rid ?? 'sin etiqueta'}
              </h3>
              <dl className="kv">
                <div><dt>Latitud</dt><dd>{selectedPoint.lat.toFixed(6)}</dd></div>
                <div><dt>Longitud</dt><dd>{selectedPoint.lon.toFixed(6)}</dd></div>
                <div>
                  <dt>Distancia</dt>
                  <dd>{formatDistance(selectedPoint, distanceUnit) ?? '—'}</dd>
                </div>
              </dl>
              {Object.keys(selectedPoint.row).length > 0 && (
                <pre className="code">{JSON.stringify(selectedPoint.row, null, 2)}</pre>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
