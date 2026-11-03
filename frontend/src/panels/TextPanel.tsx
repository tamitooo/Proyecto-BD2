import { useState } from 'react';
import type { TableInfo } from '../types';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  onRun: (sql: string) => void;
  running: boolean;
}

const RANKINGS = [
  { value: 'bm25', label: 'BM25' },
  { value: 'tf_idf', label: 'TF-IDF + coseno' },
];

export default function TextPanel({ tables, selectedTable, onSelectTable, onRun, running }: Props) {
  const [column, setColumn] = useState('');
  const [text, setText] = useState('');
  const [ranking, setRanking] = useState('bm25');
  const [limit, setLimit] = useState(10);

  const table = tables.find((t) => t.name === selectedTable) ?? tables[0] ?? null;
  const schema = table?.schema.columnas ?? [];
  const columns = schema.map(([name]) => name);
  const textColumns = schema.filter(([, type]) => /^(VARCHAR|CHAR|TEXT|CLOB|STRING)/i.test(type)).map(([name]) => name);
  const defaultColumn = textColumns[0] ?? columns[0] ?? '';
  const activeColumn = columns.includes(column) ? column : defaultColumn;
  const typeOf = (name: string) => schema.find(([n]) => n === name)?.[1] ?? '';
  const canRun = Boolean(table && textColumns.length > 0 && activeColumn && text.trim() && limit > 0);

  const buildSql = (): string => {
    if (!table) return '';
    const escaped = text.trim().replace(/'/g, "''");
    const selected = table.schema.columnas.map(([name]) => name).join(', ');
    return `SELECT ${selected}, SCORE() as score FROM ${table.name} ` +
      `WHERE MATCH(${activeColumn}, '${escaped}') ` +
      `USING ${ranking.toUpperCase()} LIMIT ${limit}`;
  };
  const sql = buildSql();

  return (
    <div className="panel">
      <h2 className="panel__title">Búsqueda textual (Parte 3)</h2>
      <p className="panel__hint">MATCH con BM25 o TF-IDF; el resultado incluye la puntuación de relevancia.</p>
      <div className="form-grid">
        <label className="field">
          <span>Tabla</span>
          <select className="select" value={table?.name ?? ''} onChange={(e) => { onSelectTable(e.target.value); setColumn(''); }}>
            {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Columna de texto</span>
          <select className="select" value={activeColumn} onChange={(e) => setColumn(e.target.value)}>
            {columns.map((c) => <option key={c} value={c}>{c} · {typeOf(c)}</option>)}
          </select>
        </label>
        {table && textColumns.length === 0 && (
          <p className="panel__hint alert alert--error">Esta tabla no tiene columnas de texto (VARCHAR).</p>
        )}
        <label className="field">
          <span>Ranking</span>
          <select className="select" value={ranking} onChange={(e) => setRanking(e.target.value)}>
            {RANKINGS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Límite</span>
          <input className="input" type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </label>
      </div>
      <label className="field field--wide">
        <span>Texto a buscar</span>
        <input className="input" value={text} placeholder="p. ej. base de datos vectorial" onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!canRun || running} onClick={() => onRun(sql)}>
          {running ? 'Buscando…' : 'Buscar'}
        </button>
      </div>
      {sql && <p className="panel__hint mono">{sql}</p>}
    </div>
  );
}
