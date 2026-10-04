import type { QueryResult, TableInfo } from './types';

const BASE = '/api';

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

export async function fetchTables(): Promise<TableInfo[]> {
  const data = await parse<{ tables: TableInfo[] }>(await fetch(`${BASE}/tables`));
  return data.tables;
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