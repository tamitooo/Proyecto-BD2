import { useState } from 'react';
import { extractMedia } from '../api';
import type { MediaFeatures, TableInfo } from '../types';

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

function escapeSql(value: string): string {
  return value.replace(/'/g, "''");
}

export default function MultimediaPanel({ tables, selectedTable, onSelectTable, onRun, running }: Props) {
  const [column, setColumn] = useState('');
  const [vectorText, setVectorText] = useState('');
  const [index, setIndex] = useState('HNSW');
  const [metric, setMetric] = useState('cosine');
  const [k, setK] = useState(5);
  const [media, setMedia] = useState<MediaFeatures | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [lastRun, setLastRun] = useState<{ index: string; metric: string; k: number; source: string } | null>(null);

  const table = tables.find((t) => t.name === selectedTable) ?? tables[0] ?? null;
  const schema = table?.schema.columnas ?? [];
  const columns = schema.map(([name]) => name);
  const namedVectorColumns = schema
    .filter(([name]) => VECTOR_NAMES.includes(name.toLowerCase()))
    .map(([name]) => name);
  const varcharColumns = schema
    .filter(([, type]) => /^(VARCHAR|CHAR|TEXT|CLOB|STRING)/i.test(type))
    .map(([name]) => name);
  // Si hay una columna con nombre de vector (embedding, vector, ...), el panel
  // la prioriza; si no, deja elegir entre las columnas VARCHAR.
  const columnOptions = namedVectorColumns.length > 0 ? namedVectorColumns : varcharColumns;
  const defaultColumn = columnOptions[0] ?? columns[0] ?? '';
  const activeColumn = columns.includes(column) ? column : defaultColumn;
  const manualVector = parseVector(vectorText);
  const target = media
    ? `'${escapeSql(media.name)}'`
    : manualVector
      ? `[${manualVector.join(', ')}]`
      : '';
  // La columna de vectores no se proyecta: es JSON largo y empuja el score
  // fuera de la tabla de resultados. El panel ya muestra dimensión y muestra.
  const projectedColumns = schema
    .filter(([name]) => name !== activeColumn && !namedVectorColumns.includes(name))
    .map(([name]) => name);
  const previewValues = media
    ? media.vector.filter((value) => Math.abs(value) > 1e-9).slice(0, 6)
    : [];
  const vectorNorm = media ? Math.hypot(...media.vector) : 0;
  const canRun = Boolean(table && activeColumn && target && k > 0 && !extracting);

  const buildSql = (): string => {
    if (!table || !target) return '';
    const selected = projectedColumns.join(', ');
    const projection = selected ? `${selected}, ` : '';
    return `SELECT ${projection}SIMILARITY_SCORE() as score FROM ${table.name} ` +
      `WHERE SIMILAR_TO(${target}, k=${k}) ` +
      `USING ${index} WITH METRIC=${metric}`;
  };
  const sql = buildSql();

  const handleFile = async (file: File | null) => {
    if (!file) {
      setMedia(null);
      setMediaError(null);
      return;
    }
    setExtracting(true);
    setMediaError(null);
    try {
      const features = await extractMedia(file);
      setMedia(features);
      setVectorText('');
    } catch (error) {
      setMedia(null);
      setMediaError(error instanceof Error ? error.message : String(error));
    } finally {
      setExtracting(false);
    }
  };

  const run = () => {
    if (!canRun) return;
    setLastRun({ index, metric, k, source: media ? 'archivo' : 'vector' });
    onRun(sql);
  };

  return (
    <div className="panel">
      <h2 className="panel__title">Búsqueda multimedia (Parte 4)</h2>
      <p className="panel__hint">
        Sube una imagen o un WAV: el servidor ejecuta SIFT/MFCC, cuantiza con K-Means
        (Bag of Words) y aplica TF-IDF. La consulta usa
        <code> SIMILAR_TO('archivo', k=N)</code>, la sintaxis del enunciado.
      </p>
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
            {columnOptions.map((c) => <option key={c} value={c}>{c}</option>)}
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

      {table && varcharColumns.length === 0 && (
        <p className="panel__hint alert alert--error">Esta tabla no tiene columnas VARCHAR para guardar/consultar vectores.</p>
      )}

      <label className="field field--wide">
        <span>Imagen o audio</span>
        <input
          className="input"
          type="file"
          accept="image/*,audio/wav,audio/x-wav,audio/wave"
          disabled={extracting}
          onChange={(e) => {
            const input = e.target;
            void handleFile(input.files?.[0] ?? null).finally(() => { input.value = ''; });
          }}
        />
      </label>

      {extracting && <p className="panel__hint">Extrayendo características en el servidor…</p>}
      {mediaError && <p className="panel__hint alert alert--error">{mediaError}</p>}
      {media && (
        <div className="metrics">
          <span>Archivo: {media.name}</span>
          <span>Tipo: {media.kind}</span>
          {media.sift_backend && <span>SIFT: {media.sift_backend}</span>}
          <span>Dimensión: {media.dimension}</span>
          <span>Palabras: {media.n_words ?? media.dimension}</span>
          <span>Extracción: {media.elapsed_ms.toFixed(1)} ms</span>
        </div>
      )}
      {media && (
        <p className="panel__hint mono">
          vector (primeros no nulos): {previewValues.length
            ? `${previewValues.map((value) => value.toFixed(4)).join(', ')}, …`
            : 'sin componentes no nulos'} · norma L2 ≈ {vectorNorm.toFixed(3)}
        </p>
      )}
      {media && (
        <div className="button-row">
          <button className="button" type="button" onClick={() => setMedia(null)}>Quitar archivo</button>
        </div>
      )}

      <label className="field field--wide">
        <span>Vector de consulta manual (opcional)</span>
        <input
          className="input"
          value={vectorText}
          placeholder="[0.1, 0.2, 0.3]"
          onChange={(e) => {
            setVectorText(e.target.value);
            if (e.target.value.trim()) setMedia(null);
          }}
        />
      </label>

      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!canRun || running} onClick={run}>
          {running ? 'Buscando…' : 'Buscar similares'}
        </button>
      </div>

      {lastRun && (
        <div className="metrics">
          <span>Origen: {lastRun.source}</span>
          <span>Índice: {lastRun.index}</span>
          <span>Métrica: {lastRun.metric}</span>
          <span>k = {lastRun.k}</span>
        </div>
      )}
      {sql && <p className="panel__hint mono">{sql}</p>}
    </div>
  );
}
