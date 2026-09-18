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