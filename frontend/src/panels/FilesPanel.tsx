import { useState } from 'react';
import { runQuery } from '../api';
import type { TableInfo } from '../types';
import TableManager from './TableManager';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  /** Recarga el catálogo (tras crear/cargar una tabla o tocar un índice). */
  onTablesChanged: (preferredTable?: string) => Promise<void>;
}

/** Técnicas que acepta el parser: USING HASH | BPLUS_CLUSTERED | BPLUS_UNCLUSTERED. */
const INDEX_TECHNIQUES = [
  { value: 'HASH', label: 'Hash Extendible (igualdad exacta)' },
  { value: 'BPLUS_CLUSTERED', label: 'B+ agrupado (rango y orden)' },
  { value: 'BPLUS_UNCLUSTERED', label: 'B+ no agrupado (rango por RID)' },
] as const;

type Technique = (typeof INDEX_TECHNIQUES)[number]['value'];

/** Sufijos del nombre automático del motor (catalog._INDEX_NAME_SUFFIX). */
const TECHNIQUE_SUFFIX: Record<Technique, string> = {
  HASH: 'hash',
  BPLUS_CLUSTERED: 'bpc',
  BPLUS_UNCLUSTERED: 'bpu',
};

const INDEX_LABEL: Record<string, string> = {
  hash: 'Hash Extendible',
  bplus_clustered: 'B+ agrupado',
  bplus_unclustered: 'B+ no agrupado',
  rtree: 'R-Tree espacial',
};

const KIND_LABEL: Record<string, string> = {
  heap: 'Heap File',
  sequential: 'Archivo Secuencial',
};

/** Origen de la tabla, para distinguir las de formulario de las de CSV. */
const SOURCE_LABEL: Record<string, string> = {
  demo: 'Demo',
  manual: 'Creada desde UI',
  csv: 'Importada desde CSV',
};

function cleanPath(fullPath: string): string {
  const parts = fullPath.split(/[\\/]/);
  return parts.length <= 2 ? fullPath : parts.slice(-2).join('/');
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function buildCreateIndexSql(
  table: string,
  column: string,
  technique: Technique,
  unique: boolean,
): string {
  // El UNIQUE solo lo soporta el Hash Extendible (catalog.create_index).
  const isUnique = unique && technique === 'HASH';
  const name = `idx_${table}_${column}_${TECHNIQUE_SUFFIX[technique]}`;
  return (
    `CREATE ${isUnique ? 'UNIQUE ' : ''}INDEX ${name} ON ${table} (${column}) ` +
    `USING ${technique}`
  );
}

export default function FilesPanel({
  tables,
  selectedTable,
  onSelectTable,
  onTablesChanged,
}: Props) {
  const table = tables.find((item) => item.name === selectedTable) ?? null;

  const [indexBusy, setIndexBusy] = useState(false);
  const [technique, setTechnique] = useState<Technique>('HASH');
  const [uniqueChecked, setUniqueChecked] = useState(false);
  // La columna elegida se recuerda junto al nombre de su tabla: al cambiar de
  // tabla la selección deja de aplicar sin necesidad de un useEffect.
  const [columnChoice, setColumnChoice] = useState<{ table: string; column: string } | null>(
    null,
  );
  const [indexFeedback, setIndexFeedback] = useState<
    { table: string; kind: 'ok' | 'error'; text: string } | null
  >(null);

  const chosenColumn =
    table && columnChoice?.table === table.name ? columnChoice.column : '';
  const feedback = table && indexFeedback?.table === table.name ? indexFeedback : null;
  const unique = uniqueChecked && technique === 'HASH';
  const isIndexedColumn = (name: string) =>
    table !== null && table.indexes.some((index) => index.column === name);
  const freeColumns = table
    ? table.schema.columnas.filter(([name]) => !isIndexedColumn(name))
    : [];

  const handleCreateIndex = async () => {
    if (!table || !chosenColumn) return;
    const sql = buildCreateIndexSql(table.name, chosenColumn, technique, unique);
    setIndexBusy(true);
    setIndexFeedback(null);
    try {
      const result = await runQuery(sql);
      if (!result.success) {
        setIndexFeedback({
          table: table.name,
          kind: 'error',
          text: `CREATE INDEX: ${result.error ?? 'error desconocido'}`,
        });
        return;
      }
      const created = result.rows[0]?.indice;
      setIndexFeedback({
        table: table.name,
        kind: 'ok',
        text:
          `Índice ${typeof created === 'string' ? created : 'creado'} listo sobre ` +
          `${table.name}(${chosenColumn}) · ${INDEX_LABEL[technique.toLowerCase()] ?? technique}` +
          (unique ? ' · único' : ''),
      });
      setColumnChoice(null);
      await onTablesChanged(table.name);
    } catch (error) {
      setIndexFeedback({
        table: table.name,
        kind: 'error',
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIndexBusy(false);
    }
  };

  const handleDropIndex = async (name: string) => {
    if (!table) return;
    setIndexBusy(true);
    setIndexFeedback(null);
    try {
      const result = await runQuery(`DROP INDEX ${name} ON ${table.name}`);
      if (!result.success) {
        setIndexFeedback({
          table: table.name,
          kind: 'error',
          text: `DROP INDEX: ${result.error ?? 'error desconocido'}`,
        });
        return;
      }
      setIndexFeedback({
        table: table.name,
        kind: 'ok',
        text: `Índice ${name} eliminado de ${table.name}.`,
      });
      await onTablesChanged(table.name);
    } catch (error) {
      setIndexFeedback({
        table: table.name,
        kind: 'error',
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setIndexBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2 className="panel__title">Panel de archivos</h2>
      <p className="panel__hint">
        Tablas cargadas, esquema físico, índices y carga de CSV.
      </p>

      <TableManager onChanged={onTablesChanged} />

      <h3 className="panel__subtitle">Tablas registradas</h3>

      <ul className="table-list">
        {tables.map((item) => (
          <li key={item.name}>
            <button
              type="button"
              className={
                item.name === selectedTable ? 'table-list__item is-active' : 'table-list__item'
              }
              onClick={() => onSelectTable(item.name)}
            >
              <span>
                <span className="table-list__name">{item.name}</span>
                {item.source && (
                  <small className="table-list__source">
                    {SOURCE_LABEL[item.source] ?? item.source}
                  </small>
                )}
              </span>

              <span className={`badge badge--${item.storage_kind}`}>
                {KIND_LABEL[item.storage_kind] ?? item.storage_kind}
              </span>
            </button>
          </li>
        ))}

        {tables.length === 0 && <li className="panel__hint">Sin tablas registradas.</li>}
      </ul>

      {table && (
        <>
          <dl className="kv">
            <div>
              <dt>Registros</dt>
              <dd>{table.row_count}</dd>
            </div>
            <div>
              <dt>Tamaño de registro</dt>
              <dd>{table.record_size} bytes</dd>
            </div>
            <div>
              <dt>Clave primaria</dt>
              <dd>{table.schema.primary_key}</dd>
            </div>
          </dl>

          {table.original_filename && (
            <p className="panel__hint">
              CSV origen: <span className="mono">{table.original_filename}</span>
            </p>
          )}

          <h3 className="panel__subtitle">Archivos en disco</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>Archivo</th>
                <th>Ruta</th>
                <th>Tamaño</th>
              </tr>
            </thead>
            <tbody>
              {table.files.map((file) => (
                <tr key={file.path}>
                  <td>{file.label}</td>
                  <td className="mono" title={file.path}>
                    {cleanPath(file.path)}
                  </td>
                  <td>{formatBytes(file.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className="panel__subtitle">Esquema</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>Columna</th>
                <th>Tipo</th>
                <th>Clave</th>
              </tr>
            </thead>
            <tbody>
              {table.schema.columnas.map(([name, tipo]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td className="mono">{tipo}</td>
                  <td>{name === table.schema.primary_key ? 'PK' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className="panel__subtitle">Índices secundarios</h3>
          {table.indexes.length === 0 ? (
            <p className="panel__hint">Sin índices registrados.</p>
          ) : (
            // Tarjetas en lugar de tabla: con 5 columnas los nombres largos
            // (idx_emp_salary_bplus) y el botón se salían del recuadro.
            <ul className="index-list">
              {table.indexes.map((index) => (
                <li key={index.name} className="index-card">
                  <div className="index-card__head">
                    <span className="index-card__name mono">{index.name}</span>
                    <span className={`badge badge--${index.kind}`}>
                      {INDEX_LABEL[index.kind] ?? index.kind}
                    </span>
                  </div>
                  <div className="index-card__meta">
                    <span>
                      Columna{index.kind === 'rtree' ? 's' : ''}:{' '}
                      <strong>
                        {index.kind === 'rtree' && index.lon_column
                          ? `(${index.lat_column ?? index.column}, ${index.lon_column})`
                          : index.column}
                      </strong>
                    </span>
                    <span>
                      Único: <strong>{index.unique ? 'Sí' : 'No'}</strong>
                    </span>
                  </div>
                  <button
                    type="button"
                    className="button button--small button--danger index-card__drop"
                    disabled={indexBusy}
                    onClick={() => void handleDropIndex(index.name)}
                  >
                    Eliminar índice
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Crear índice: es lo que pidió el profesor ("nos falta mejorar
              índices") y no existía forma de hacerlo desde la interfaz. */}
          <h3 className="panel__subtitle">Crear índice</h3>
          <div className="form-grid">
            <label className="field">
              <span>Columna</span>
              <select
                className="select select--compact"
                value={chosenColumn}
                disabled={indexBusy || freeColumns.length === 0}
                onChange={(event) =>
                  setColumnChoice({ table: table.name, column: event.target.value })
                }
              >
                <option value="">— elige una columna —</option>
                {freeColumns.map(([name, tipo]) => (
                  <option key={name} value={name}>
                    {name} ({tipo})
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Técnica</span>
              <select
                className="select select--compact"
                value={technique}
                disabled={indexBusy}
                onChange={(event) => setTechnique(event.target.value as Technique)}
              >
                {INDEX_TECHNIQUES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field field--check">
              <input
                type="checkbox"
                checked={uniqueChecked}
                disabled={indexBusy || technique !== 'HASH'}
                onChange={(event) => setUniqueChecked(event.target.checked)}
              />
              <span>Único (solo Hash)</span>
            </label>
          </div>

          <div className="button-row">
            <button
              type="button"
              className="button button--primary"
              disabled={indexBusy || !chosenColumn}
              onClick={() => void handleCreateIndex()}
            >
              {indexBusy ? 'Trabajando…' : 'Crear índice'}
            </button>
          </div>

          {freeColumns.length === 0 && (
            <p className="panel__hint">
              Todas las columnas de {table.name} ya tienen índice.
            </p>
          )}

          {feedback && (
            <p className={feedback.kind === 'ok' ? 'alert alert--ok' : 'alert alert--error'}>
              {feedback.text}
            </p>
          )}

          <p className="panel__hint">
            El R-Tree espacial se crea por SQL con{' '}
            <span className="mono">CREATE INDEX … ON {table.name} (lat, lon) USING RTREE</span>.
          </p>
        </>
      )}
    </div>
  );
}
