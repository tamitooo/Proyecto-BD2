// Issue #20 + gestión dinámica de tablas/CSV
import type { TableInfo } from '../types';
import TableManager from './TableManager';

interface Props {
  tables: TableInfo[];
  selectedTable: string | null;
  onSelectTable: (name: string) => void;
  onTablesChanged: (preferredTable?: string) => Promise<void>;
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

const SOURCE_LABEL: Record<string, string> = {
  demo: 'Demo',
  manual: 'Creada desde UI',
  csv: 'Importada desde CSV',
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

export default function FilesPanel({
  tables,
  selectedTable,
  onSelectTable,
  onTablesChanged,
}: Props) {
  const table =
    tables.find((item) => item.name === selectedTable) ?? null;

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
                item.name === selectedTable
                  ? 'table-list__item is-active'
                  : 'table-list__item'
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

        {tables.length === 0 && (
          <li className="panel__hint">
            Sin tablas registradas.
          </li>
        )}
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
                  <td>
                    {name === table.schema.primary_key
                      ? 'PK'
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className="panel__subtitle">Índices secundarios</h3>
          {table.indexes.length === 0 ? (
            <p className="panel__hint">
              Sin índices registrados.
            </p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>Nombre</th>
                  <th>Columna</th>
                  <th>Técnica</th>
                  <th>Único</th>
                </tr>
              </thead>
              <tbody>
                {table.indexes.map((index) => (
                  <tr key={index.name}>
                    <td className="mono">{index.name}</td>
                    <td>{index.column}</td>
                    <td>{INDEX_LABEL[index.kind] ?? index.kind}</td>
                    <td>{index.unique ? 'Sí' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
