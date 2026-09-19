import type {
  CreateTableRequest,
  CreateTableResponse,
  CsvImportResult,
  QueryResult,
  TableInfo,
} from './types';

const BASE = '/api';

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
      // If it is not JSON, keep the raw response body.
    }

    throw new Error(detail);
  }

  return JSON.parse(raw) as T;
}

export async function fetchTables(): Promise<TableInfo[]> {
  const data = await parse<{ tables: TableInfo[] }>(
    await fetch(`${BASE}/tables`),
  );
  return data.tables;
}

export async function createTable(
  request: CreateTableRequest,
): Promise<TableInfo> {
  const response = await fetch(`${BASE}/tables`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  const payload = await parse<CreateTableResponse>(response);
  return payload.table;
}

export async function importCsv(
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
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ sql }),
  });

  return parse<QueryResult>(response);
}
