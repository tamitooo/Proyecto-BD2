import type {
  CellValue,
  CreateTableRequest,
  CreateTableResponse,
  CsvImportResult,
  QueryResult,
  SpatialBounds,
  SpatialKind,
  SpatialMetric,
  SpatialPoint,
  SpatialPoints,
  SpatialQueryRequest,
  SpatialQueryResult,
  TableInfo,
} from './types';

const BASE = '/api';

/**
 * Lee la respuesta y, si el motor devolvió un error, lanza **el mensaje del
 * motor**. FastAPI envuelve el error en `{"detail": "..."}`, así que se extrae:
 * el usuario ve "la tabla 'x' already exists" en vez del JSON crudo.
 */
async function parse<T>(response: Response): Promise<T> {
  const raw = await response.text();

  if (!response.ok) {
    let detail = raw || `HTTP ${response.status}`;

    try {
      const payload = JSON.parse(raw) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Si no es JSON, se conserva el cuerpo tal cual.
    }

    throw new Error(detail);
  }

  return JSON.parse(raw) as T;
}

export async function fetchTables(): Promise<TableInfo[]> {
  const data = await parse<{ tables: TableInfo[] }>(await fetch(`${BASE}/tables`));
  return data.tables;
}

/**
 * Crea una tabla dinámica desde el panel.
 *
 * Va por ``POST /api/tables``, que en el motor reutiliza el mismo
 * ``CREATE TABLE`` que el panel de consultas: una sola implementación.
 */
export async function createTable(request: CreateTableRequest): Promise<TableInfo> {
  const payload = await parse<CreateTableResponse>(
    await fetch(`${BASE}/tables`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
  return payload.table;
}

/**
 * Sube un CSV y **crea la tabla deduciendo el esquema** desde el archivo.
 *
 * Se llama ``importCsvFile`` para no chocar con :func:`importCsv`, que carga un
 * CSV en una tabla que **ya existe** (es la otra mitad de la funcionalidad).
 */
export async function importCsvFile(
  file: File,
  options: {
    name: string;
    primaryKey: string;
    storageKind: 'heap' | 'sequential';
  },
): Promise<CsvImportResult> {
  const form = new FormData();

  form.append('file', file);
  form.append('name', options.name);
  form.append('primary_key', options.primaryKey);
  form.append('storage_kind', options.storageKind);

  return parse<CsvImportResult>(
    await fetch(`${BASE}/tables/import-csv`, {
      method: 'POST',
      body: form,
    }),
  );
}

export async function runQuery(sql: string): Promise<QueryResult> {
  const response = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql }),
  });
  return parse<QueryResult>(response);
}

export interface CsvImportReport {
  table: string;
  columns: string[];
  rows_read: number;
  inserted: number;
  failed: number;
  errors: string[];
  success: boolean;
}

export async function importCsv(
  table: string,
  csvText: string,
  hasHeader = true,
  delimiter = ',',
): Promise<CsvImportReport> {
  const response = await fetch(`${BASE}/tables/${encodeURIComponent(table)}/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      csv_text: csvText,
      has_header: hasHeader,
      delimiter,
    }),
  });
  return parse<CsvImportReport>(response);
}

/* ------------------------------------------------------------------ *
 * Parte 2: API espacial
 *
 * El backend espacial se escribe en paralelo, así que aquí se normaliza
 * cada respuesta campo por campo: si llega un shape inesperado se lanza un
 * Error legible en vez de dejar pasar `undefined` al panel de mapa.
 * ------------------------------------------------------------------ */

/** Ruta no registrada en FastAPI: el backend espacial aún no está desplegado. */
export function isSpatialEndpointMissing(error: unknown): boolean {
  const text = error instanceof Error ? error.message : String(error);
  if (/HTTP (404|405|501)/.test(text) === false) return false;
  // FastAPI contesta {"detail":"Not Found"} cuando la ruta no existe o el
  // método no está permitido; un 404 con otro detalle sí viene de la ruta
  // espacial (p. ej. "la tabla no tiene columnas espaciales").
  return /HTTP (405|501)/.test(text) || /"detail"\s*:\s*"?\s*not found/i.test(text);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function asOptionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asRow(value: unknown): Record<string, CellValue> {
  const row: Record<string, CellValue> = {};
  for (const [key, cell] of Object.entries(asRecord(value))) {
    if (cell === null || ['string', 'number', 'boolean'].includes(typeof cell)) {
      row[key] = cell as CellValue;
    } else {
      row[key] = JSON.stringify(cell);
    }
  }
  return row;
}

function normalizeSpatialPoint(raw: unknown): SpatialPoint | null {
  const item = asRecord(raw);
  const lat = asOptionalNumber(item.lat);
  const lon = asOptionalNumber(item.lon);
  if (lat === null || lon === null) return null;
  const label = typeof item.label === 'string' && item.label.trim() ? item.label : null;
  return {
    rid: typeof item.rid === 'string' ? item.rid : '',
    lat,
    lon,
    label,
    distance_m: asOptionalNumber(item.distance_m),
    row: asRow(item.row),
  };
}

function normalizeBounds(raw: unknown): SpatialBounds | null {
  const item = asRecord(raw);
  const minLat = asOptionalNumber(item.min_lat);
  const maxLat = asOptionalNumber(item.max_lat);
  const minLon = asOptionalNumber(item.min_lon);
  const maxLon = asOptionalNumber(item.max_lon);
  if (minLat === null || maxLat === null || minLon === null || maxLon === null) return null;
  return { min_lat: minLat, max_lat: maxLat, min_lon: minLon, max_lon: maxLon };
}

function normalizePointList(raw: unknown): SpatialPoint[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map(normalizeSpatialPoint)
    .filter((point): point is SpatialPoint => point !== null);
}

/** GET /api/spatial/points/{table} · puntos de una tabla con columnas espaciales. */
export async function fetchSpatialPoints(table: string): Promise<SpatialPoints> {
  const response = await fetch(`${BASE}/spatial/points/${encodeURIComponent(table)}`);
  const data = asRecord(await parse<unknown>(response));
  if (!Array.isArray(data.points)) {
    throw new Error(
      `respuesta inesperada de /api/spatial/points/${table}: falta la lista "points"`,
    );
  }
  const points = normalizePointList(data.points);
  return {
    table: typeof data.table === 'string' ? data.table : table,
    lat_column: typeof data.lat_column === 'string' ? data.lat_column : '',
    lon_column: typeof data.lon_column === 'string' ? data.lon_column : '',
    label_column: typeof data.label_column === 'string' ? data.label_column : null,
    count: asOptionalNumber(data.count) ?? points.length,
    bounds: normalizeBounds(data.bounds),
    points,
  };
}

/** POST /api/spatial/query · búsqueda por rango / k-NN / polígono sobre el R-Tree. */
export async function runSpatialQuery(body: SpatialQueryRequest): Promise<SpatialQueryResult> {
  const response = await fetch(`${BASE}/spatial/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = asRecord(await parse<unknown>(response));
  const kind: SpatialKind =
    data.kind === 'knn' || data.kind === 'range' ? data.kind : body.kind;
  const metric: SpatialMetric =
    data.metric === 'euclidean' || data.metric === 'haversine' ? data.metric : (body.metric ?? 'haversine');
  const error = typeof data.error === 'string' && data.error ? data.error : null;
  return {
    success:
      typeof data.success === 'boolean' ? data.success : error === null,
    kind,
    metric,
    table: typeof data.table === 'string' ? data.table : body.table,
    access_path: typeof data.access_path === 'string' ? data.access_path : '—',
    used_indexes: Array.isArray(data.used_indexes)
      ? data.used_indexes.filter((item): item is string => typeof item === 'string')
      : [],
    execution_time_ms: asOptionalNumber(data.execution_time_ms) ?? 0,
    distance_unit: typeof data.distance_unit === 'string' ? data.distance_unit : 'm',
    points: normalizePointList(data.points),
    candidates_visited: asOptionalNumber(data.candidates_visited),
    error,
  };
}