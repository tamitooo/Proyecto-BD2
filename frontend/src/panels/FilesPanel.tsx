// Issue #20
import { useRef, useState } from 'react';
import type { TableInfo } from '../types';
import { importCsv, runQuery } from '../api';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  onImported?: () => void | Promise<void>;
}

const KIND_LABEL: Record<string, string> = {
  heap: 'Heap File',
  sequential: 'Archivo Secuencial Paginado',
};

const INDEX_LABEL: Record<string, string> = {
  hash: 'Extendible Hashing',
  bplus_clustered: 'B+ Tree agrupado',
  bplus_unclustered: 'B+ Tree no agrupado',
};

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

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function cleanPath(fullPath: string): string {
  const normalized = fullPath.replace(/\\/g, '/');
  const idx = normalized.lastIndexOf('backend/data');
  if (idx !== -1) {
    return normalized.substring(idx);
  }
  return normalized.split('/').pop() ?? fullPath;
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
  onImported,
}: Props) {
  const table = tables.find((item) => item.name === selectedTable) ?? null;
  const fileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const [technique, setTechnique] = useState<Technique>('HASH');
  const [uniqueChecked, setUniqueChecked] = useState(false);
  // La columna elegida se recuerda junto al nombre de su tabla: al cambiar de
  // tabla la selección deja de aplicar sin necesidad de un useEffect.
  const [columnChoice, setColumnChoice] = useState<{ table: string; column: string } | null>(null);
  const [indexFeedback, setIndexFeedback] = useState<
    { table: string; kind: 'ok' | 'error'; text: string } | null
  >(null);
  // Un CSV exportado desde Excel en español usa ';' y puede no traer cabecera.
  const [delimiter, setDelimiter] = useState<',' | ';' | '\t'>(',');
  const [hasHeader, setHasHeader] = useState(true);

  const chosenColumn = table && columnChoice?.table === table.name ? columnChoice.column : '';
  const feedback = table && indexFeedback?.table === table.name ? indexFeedback : null;
  const unique = uniqueChecked && technique === 'HASH';
  const isIndexedColumn = (name: string) =>
    table !== null && table.indexes.some((index) => index.column === name);
  const freeColumns = table ? table.schema.columnas.filter(([name]) => !isIndexedColumn(name)) : [];

  const refresh = async () => {
    await onImported?.();
  };

  const handleFile = async (file: File | undefined) => {
    if (!file || !selectedTable) return;
    setImporting(true);
    setMessage(null);
    setImportError(null);
    try {
      const text = await file.text();
      const report = await importCsv(selectedTable, text, hasHeader, delimiter);
      setMessage(
        `"${file.name}": ${report.inserted} filas insertadas en ${report.table}` +
          (report.failed ? `, ${report.failed} rechazadas` : ''),
      );
      if (report.errors.length > 0) {
        setImportError(report.errors.slice(0, 3).join(' · '));
      }
      await onImported?.();
    } catch (error) {
      setImportError(error instanceof Error ? error.message : String(error));
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  const handleCreateIndex = async () => {
    if (!table || !chosenColumn) return;
    const sql = buildCreateIndexSql(table.name, chosenColumn, technique, unique);
    setIndexBusy(true);
    setIndexFeedback(null);
    try {
      const result = await runQuery(sql);
      const created = result.rows[0]?.indice;
      if (!result.success) {
        setIndexFeedback({
          table: table.name,
          kind: 'error',
          text: `CREATE INDEX: ${result.error ?? 'error desconocido'}`,
        });
        return;
      }
      setIndexFeedback({
        table: table.name,
        kind: 'ok',
        text:
          `Índice ${typeof created === 'string' ? created : 'creado'} listo sobre ` +
          `${table.name}(${chosenColumn}) · ${INDEX_LABEL[technique.toLowerCase()] ?? technique}` +
          (unique ? ' · único' : ''),
      });
      setColumnChoice(null);
      await refresh();
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
      await refresh();
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
      <p className="panel__hint">Tablas cargadas, esquema físico e índices.</p>

      <ul className="table-list">
        {tables.map((item) => (
          <li key={item.name}>
            <button
              type="button"
              className={item.name === selectedTable ? 'table-list__item is-active' : 'table-list__item'}
              onClick={() => onSelectTable(item.name)}
            >
              <span className="table-list__name">{item.name}</span>
              <span className={`badge badge--${item.storage_kind}`}>
                {KIND_LABEL[item.storage_kind] ?? item.storage_kind}
              </span>
            </button>
          </li>
        ))}
        {tables.length === 0 && <li className="panel__hint">Sin tablas registradas.</li>}
      </ul>

      <div className="import">
        <label className="panel__subtitle" htmlFor="csv-input">
          Cargar CSV en la tabla seleccionada
        </label>
        <div className="index-form index-form--inline">
          <label>
            Separador
            <select
              className="select"
              value={delimiter}
              onChange={(event) => setDelimiter(event.target.value as ',' | ';' | '\t')}
            >
              <option value=",">Coma ( , )</option>
              <option value=";">Punto y coma ( ; ) — Excel en español</option>
              <option value="\t">Tabulador</option>
            </select>
          </label>
          <label className="index-form__check">
            <input
              type="checkbox"
              checked={hasHeader}
              onChange={(event) => setHasHeader(event.target.checked)}
            />
            La primera fila es el encabezado
          </label>
        </div>
        <input
          id="csv-input"
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          disabled={!table || importing}
          onChange={(event) => void handleFile(event.target.files?.[0])}
        />
        <p className="panel__hint">
          {importing
            ? 'Importando…'
            : 'Usa el mismo camino que INSERT: respeta la clave primaria y actualiza los índices. ' +
              (hasHeader
                ? 'El encabezado debe nombrar las columnas de la tabla (en cualquier orden).'
                : 'Sin encabezado se importa por posición.')}
        </p>
        {message && <p className="panel__hint">{message}</p>}
        {importError && <p className="import__error">{importError}</p>}
      </div>

      {table && (
        <>
          <dl className="kv">
            <div><dt>Registros</dt><dd>{table.row_count}</dd></div>
            <div><dt>Tamaño de registro</dt><dd>{table.record_size} bytes</dd></div>
            <div><dt>Clave primaria</dt><dd>{table.schema.primary_key}</dd></div>
          </dl>

          <h3 className="panel__subtitle">Archivos en disco</h3>
          <table className="grid">
            <thead>
              <tr><th>Archivo</th><th>Ruta</th><th>Tamaño</th></tr>
            </thead>
            <tbody>
              {table.files.map((file) => (
                <tr key={file.path}>
                  <td>{file.label}</td>
                  <td className="mono" title={file.path}>{cleanPath(file.path)}</td>
                  <td>{formatBytes(file.size_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className="panel__subtitle">Esquema</h3>
          <table className="grid">
            <thead>
              <tr><th>Columna</th><th>Tipo</th><th>Clave</th></tr>
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

          <div className="index-form">
            <label htmlFor="index-column">
              Columna
              <select
                id="index-column"
                className="select"
                value={chosenColumn}
                disabled={indexBusy || freeColumns.length === 0}
                onChange={(event) =>
                  setColumnChoice({ table: table.name, column: event.target.value })
                }
              >
                <option value="">Elegir columna…</option>
                {table.schema.columnas.map(([name]) => (
                  <option key={name} value={name} disabled={isIndexedColumn(name)}>
                    {name}{isIndexedColumn(name) ? ' (ya indexada)' : ''}
                  </option>
                ))}
              </select>
            </label>

            <label htmlFor="index-technique">
              Técnica
              <select
                id="index-technique"
                className="select"
                value={technique}
                disabled={indexBusy}
                onChange={(event) => setTechnique(event.target.value as Technique)}
              >
                {INDEX_TECHNIQUES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>

            <label className="index-form__check" htmlFor="index-unique">
              <input
                id="index-unique"
                type="checkbox"
                checked={unique}
                disabled={indexBusy || technique !== 'HASH'}
                onChange={(event) => setUniqueChecked(event.target.checked)}
              />
              Único (solo Hash)
            </label>

            <div className="index-form__actions">
              <button
                type="button"
                className="button button--primary"
                disabled={indexBusy || !chosenColumn}
                onClick={() => void handleCreateIndex()}
              >
                {indexBusy ? 'Aplicando…' : 'Crear índice'}
              </button>
            </div>
          </div>

          <p className="panel__hint">
            {freeColumns.length === 0
              ? 'Todas las columnas ya tienen índice: elimina uno para poder crear otro.'
              : 'El índice se construye recorriendo la tabla, así que también indexa filas ya cargadas.'}
          </p>

          {feedback && (
            <p className={feedback.kind === 'ok' ? 'alert alert--ok' : 'alert alert--error'}>
              {feedback.text}
            </p>
          )}

          {table.indexes.length === 0 ? (
            <p className="panel__hint">Sin índices registrados.</p>
          ) : (
            <>
              <table className="grid">
                <thead>
                  <tr><th>Nombre</th><th>Columna</th><th>Técnica</th><th>Único</th><th>Acciones</th></tr>
                </thead>
                <tbody>
                  {table.indexes.map((index) => {
                    // El índice de la PK es el que aplica la unicidad de la clave;
                    // eliminarlo desde aquí desactivaría la restricción.
                    const isPrimaryIndex = index.column === table.schema.primary_key;
                    return (
                      <tr key={index.name}>
                        <td className="mono">{index.name}</td>
                        <td>{index.column}</td>
                        <td>{INDEX_LABEL[index.kind] ?? index.kind}</td>
                        <td>{index.unique ? 'Sí' : 'No'}</td>
                        <td>
                          <button
                            type="button"
                            className="button button--small"
                            disabled={isPrimaryIndex || indexBusy}
                            title={
                              isPrimaryIndex
                                ? 'Es el índice que aplica la PRIMARY KEY: no se puede eliminar. Usa DROP TABLE para borrar la tabla completa.'
                                : `DROP INDEX ${index.name} ON ${table.name}`
                            }
                            onClick={() => void handleDropIndex(index.name)}
                          >
                            Eliminar
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {table.indexes.some((index) => index.column === table.schema.primary_key) && (
                <p className="panel__hint">
                  El índice de la PRIMARY KEY ({table.schema.primary_key}) está deshabilitado porque
                  es el que hace cumplir la clave: para quitarlo hay que eliminar la tabla.
                </p>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
