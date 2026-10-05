import type {
  CreateTableRequest,
  QueryResult,
  SpatialPoints,
  SpatialQueryRequest,
  SpatialQueryResult,
  TableInfo,
} from './types';

const BASE = '/api';

async function parse<T>(response: Response): Promise<T> {
  const raw = await response.text();
  let payload: unknown = null;
  if (raw) {
    try { payload = JSON.parse(raw); } catch { payload = raw; }
  }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? String((payload as { detail?: unknown }).detail)
      : raw || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function fetchTables(): Promise<TableInfo[]> {
  return parse<TableInfo[]>(await fetch(`${BASE}/tables`));
}

export async function runQuery(sql: string): Promise<QueryResult> {
  return parse<QueryResult>(await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql }),
  }));
}

export async function createTable(request: CreateTableRequest): Promise<TableInfo> {
  const result = await parse<{ table: TableInfo }>(await fetch(`${BASE}/tables`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  }));
  return result.table;
}

export async function importCsvFile(
  file: File,
  options: { name: string; primaryKey: string; storageKind: 'heap' | 'sequential' },
): Promise<{ table: TableInfo; imported_rows?: number }> {
  const form = new FormData();
  form.append('file', file);
  form.append('name', options.name);
  form.append('primary_key', options.primaryKey);
  form.append('storage_kind', options.storageKind);
  return parse(await fetch(`${BASE}/tables/import`, { method: 'POST', body: form }));
}

export async function importCsvIntoTable(
  table: string,
  file: File,
): Promise<{ inserted?: number; failed?: number; success?: boolean; errors?: string[] }> {
  const form = new FormData();
  form.append('file', file);
  form.append('has_header', 'true');
  return parse(await fetch(`${BASE}/tables/${encodeURIComponent(table)}/import`, {
    method: 'POST',
    body: form,
  }));
}

export function isSpatialEndpointMissing(error: unknown): boolean {
  const text = error instanceof Error ? error.message : String(error);
  return /Not Found|HTTP 404|HTTP 405|HTTP 501/i.test(text);
}

export async function fetchSpatialPoints(table: string): Promise<SpatialPoints> {
  return parse<SpatialPoints>(await fetch(`${BASE}/spatial/points/${encodeURIComponent(table)}`));
}

export async function runSpatialQuery(body: SpatialQueryRequest): Promise<SpatialQueryResult> {
  return parse<SpatialQueryResult>(await fetch(`${BASE}/spatial/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
}
