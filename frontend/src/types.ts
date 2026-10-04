export type CellValue = string | number | boolean | null;

export interface SchemaInfo {
  columnas: [string, string][];
  primary_key: string;
}

export interface IndexInfo {
  name: string;
  column: string;
  kind: string;      // hash | bplus_clustered | bplus_unclustered
  unique: boolean;
}

export interface StorageFile {
  label: string;
  path: string;
  size_bytes: number;
}

export interface TableInfo {
  name: string;
  storage_kind: string;   // heap | sequential
  schema: SchemaInfo;
  indexes: IndexInfo[];
  files: StorageFile[];
  row_count: number;
  record_size: number;
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
  elapsed_ms?: number;
  rows_in?: number;
  rows_out?: number;
  table?: string;
  index?: string | null;
}

export interface ExecutionPlan {
  table: string;
  planner_type: string;
  access_path: string;
  used_indexes: string[];
  steps: PlanStep[];
  runtime_steps: RuntimeStep[];
  total_execution_time_ms?: number;
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

/* ------------------------------------------------------------------ *
 * Parte 2: base de datos espacial (R-Tree, rango, k-NN, polígonos)
 * ------------------------------------------------------------------ */

/** Un punto 2D devuelto por /api/spatial/points o /api/spatial/query. */
export interface SpatialPoint {
  rid: string;
  lat: number;
  lon: number;
  label: string | null;
  /** Solo lo rellena /api/spatial/query (distancia al punto de consulta). */
  distance_m: number | null;
  row: Record<string, CellValue>;
}

export interface SpatialBounds {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
}

/** GET /api/spatial/points/{table} */
export interface SpatialPoints {
  table: string;
  lat_column: string;
  lon_column: string;
  label_column: string | null;
  count: number;
  bounds: SpatialBounds | null;
  points: SpatialPoint[];
}

export type SpatialKind = 'range' | 'knn';
export type SpatialMetric = 'euclidean' | 'haversine';

/** Cuerpo de POST /api/spatial/query */
export interface SpatialQueryRequest {
  table: string;
  kind: SpatialKind;
  lat: number;
  lon: number;
  radius_m?: number;
  k?: number;
  metric?: SpatialMetric;
  /** Vértices [lat, lon] del polígono de intersección (opcional). */
  polygon?: [number, number][];
}

/** Respuesta de POST /api/spatial/query. */
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