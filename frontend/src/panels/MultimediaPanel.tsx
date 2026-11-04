import { useState } from 'react';
import type { TableInfo } from '../types';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  onRun: (sql: string) => void;
  running: boolean;
}

const METRICS = [
  { value: 'cosine', label: 'Coseno' },
  { value: 'euclidean', label: 'Euclidiana' },
  { value: 'dot_product', label: 'Producto punto' },
];

const INDEXES = [
  { value: 'HNSW', label: 'HNSW' },
  { value: 'IVF', label: 'IVF' },
];

const VECTOR_NAMES = ['embedding', 'vector', 'vectors', 'features', 'descriptor', 'histogram'];

function parseVector(value: string): number[] | null {
  const cleaned = value.trim().replace(/^\[/, '').replace(/\]$/, '');
  if (!cleaned) return null;
  const parts = cleaned.split(/[,\s]+/).filter(Boolean);
  if (parts.length === 0) return null;
  const numbers = parts.map(Number);
  if (numbers.some((n) => !Number.isFinite(n))) return null;
  return numbers;
}

export default function MultimediaPanel({ tables, selectedTable, onSelectTable, onRun, running }: Props) {
  const [column, setColumn] = useState('');
  const [vectorText, setVectorText] = useState('');
  const [index, setIndex] = useState('HNSW');
  const [metric, setMetric] = useState('cosine');
  const [k, setK] = useState(5);
  const [fileName, setFileName] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<{ index: string; metric: string; k: number } | null>(null);

  const table = tables.find((t) => t.name === selectedTable) ?? tables[0] ?? null;
  const schema = table?.schema.columnas ?? [];
  const columns = schema.map(([name]) => name);
  const vectorColumns = schema
    .filter(([name, type]) => VECTOR_NAMES.includes(name.toLowerCase()) || /^(VARCHAR|CHAR|TEXT|CLOB|STRING)/i.test(type))
    .map(([name]) => name);
  const defaultColumn = vectorColumns[0] ?? columns[0] ?? '';
  const activeColumn = columns.includes(column) ? column : defaultColumn;
  const vector = parseVector(vectorText);
  const canRun = Boolean(table && activeColumn && vector && k > 0);

  const buildSql = (): string => {
    if (!table || !vector) return '';
    const selected = schema.map(([name]) => name).join(', ');
    return `SELECT ${selected}, SIMILARITY_SCORE() as score FROM ${table.name} ` +
      `WHERE SIMILAR_TO([${vector.join(', ')}], k=${k}) ` +
      `USING ${index} WITH METRIC=${metric}`;
  };
  const sql = buildSql();

  const run = () => {
    if (!canRun) return;
    setLastRun({ index, metric, k });
    onRun(sql);
  };

  return (
    <div className="panel">
      <h2 className="panel__title">Búsqueda multimedia (Parte 4)</h2>
      <p className="panel__hint">SIMILAR_TO con HNSW o IVF y métrica euclidiana, coseno o producto punto.</p>
      <div className="form-grid">
        <label className="field">
          <span>Tabla</span>
          <select className="select" value={table?.name ?? ''} onChange={(e) => { onSelectTable(e.target.value); setColumn(''); }}>
            {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Columna de vectores</span>
          <select className="select" value={activeColumn} onChange={(e) => setColumn(e.target.value)}>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Índice</span>
          <select className="select" value={index} onChange={(e) => setIndex(e.target.value)}>
            {INDEXES.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Métrica</span>
          <select className="select" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRICS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>k vecinos</span>
          <input className="input" type="number" min={1} max={100} value={k} onChange={(e) => setK(Number(e.target.value))} />
        </label>
      </div>
      <label className="field field--wide">
        <span>Vector de consulta</span>
        <input className="input" value={vectorText} placeholder="[0.1, 0.2, 0.3]" onChange={(e) => setVectorText(e.target.value)} />
      </label>
      <label className="field field--wide">
        <span>Imagen o audio (opcional)</span>
        <input className="input" type="file" accept="image/*,audio/*" onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)} />
      </label>
      {fileName && (
        <p className="panel__hint alert alert--error">
          {fileName}: la extracción de características (SIFT/MFCC) llega con #107; por ahora pega el vector manualmente.
        </p>
      )}
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!canRun || running} onClick={run}>
          {running ? 'Buscando…' : 'Buscar similares'}
        </button>
      </div>
      {lastRun && (
        <div className="metrics">
          <span>Índice: {lastRun.index}</span>
          <span>Métrica: {lastRun.metric}</span>
          <span>k = {lastRun.k}</span>
        </div>
      )}
      {sql && <p className="panel__hint mono">{sql}</p>}
    </div>
  );
}
