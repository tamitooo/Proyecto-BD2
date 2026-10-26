export type CellValue = string | number | boolean | null;

export interface SchemaInfo {
  columnas: [string, string][];
  primary_key: string;
}

export interface IndexInfo {
  name: string;
  column: string;
  kind: string;
  unique: boolean;
  lon_column?: string;
}

export interface StorageFile {
  label: string;
  path: string;
  size_bytes: number;
}

export interface TableInfo {
  name: string;
  storage_kind: string;
  schema: SchemaInfo;
  indexes: IndexInfo[];
  files: StorageFile[];
  row_count: number;
  record_size: number;
  source?: string;
  original_filename?: string | null;
}

export interface CreateTableColumn {
  name: string;
  type: string;
}

export interface CreateTableRequest {
  name: string;
  storage_kind: 'heap' | 'sequential';
  primary_key: string;
  columns: CreateTableColumn[];
}

export interface PlanStep {
  operator: string;
  table?: string | null;
  index?: string | null;
  reason?: string;
  details?: Record<string, unknown>;
}

export interface RuntimeStep {
  operator: string;
  elapsed_ms?: number | null;
  rows_in?: number | null;
  rows_out?: number | null;
  table?: string;
  index?: string | null;
  [key: string]: unknown;
}

export interface ExecutionPlan {
  table?: string | null;
  planner_type?: string;
  access_path?: string;
  used_indexes?: string[];
  steps?: PlanStep[];
  runtime_steps?: RuntimeStep[];
  total_execution_time_ms?: number;
  [key: string]: unknown;
}

export interface QueryResult {
  success: boolean;
  statement: string;
  columns: string[];
  rows: Record<string, CellValue>[];
  affected_rows: number;
  execution_time_ms: number;
  execution_plan: ExecutionPlan | null;
  error: string | null;
}

export interface SpatialPoint {
  rid: string;
  lat: number;
  lon: number;
  label: string | null;
  distance_m: number | null;
  row: Record<string, CellValue>;
}

export interface SpatialBounds {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
}

export interface SpatialPoints {
  table: string;
  lat_column: string;
  lon_column: string;
  label_column: string | null;
  count: number;
  bounds: SpatialBounds | null;
  points: SpatialPoint[];
}

export type SpatialKind = 'range' | 'knn' | 'polygon';
export type SpatialMetric = 'euclidean' | 'haversine';

export interface SpatialQueryRequest {
  table: string;
  kind: SpatialKind;
  lat: number;
  lon: number;
  radius_m?: number;
  k?: number;
  metric: SpatialMetric;
  polygon?: [number, number][];
}

export interface SpatialQueryResult {
  success: boolean;
  kind: SpatialKind;
  metric: SpatialMetric;
  table: string;
  access_path: string;
  used_indexes: string[];
  execution_time_ms: number;
  distance_unit: string;
  points: SpatialPoint[];
  candidates_visited: number | null;
  error: string | null;
}
