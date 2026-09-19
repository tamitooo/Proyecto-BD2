import { useMemo, useState } from 'react';
import { createTable, importCsv } from '../api';
import type { CreateTableColumn } from '../types';

interface Props {
  onChanged: (preferredTable?: string) => Promise<void>;
}

type StorageKind = 'heap' | 'sequential';

const TYPE_OPTIONS = [
  'INT',
  'FLOAT',
  'VARCHAR(16)',
  'VARCHAR(32)',
  'VARCHAR(64)',
  'VARCHAR(128)',
  'VARCHAR(255)',
];

function safeTableName(filename: string): string {
  const withoutExtension = filename.replace(/\.csv$/i, '');
  let value = withoutExtension
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');

  if (!value) value = 'tabla_csv';
  if (/^\d/.test(value)) value = `t_${value}`;

  return value;
}

export default function TableManager({ onChanged }: Props) {
  const [mode, setMode] = useState<'create' | 'csv'>('csv');

  const [tableName, setTableName] = useState('nueva_tabla');
  const [storageKind, setStorageKind] = useState<StorageKind>('heap');
  const [columns, setColumns] = useState<CreateTableColumn[]>([
    { name: 'id', type: 'INT' },
    { name: 'nombre', type: 'VARCHAR(64)' },
  ]);
  const [primaryKey, setPrimaryKey] = useState('id');

  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvTableName, setCsvTableName] = useState('');
  const [csvPrimaryKey, setCsvPrimaryKey] = useState('id');
  const [csvStorageKind, setCsvStorageKind] = useState<StorageKind>('heap');

  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const availablePrimaryKeys = useMemo(
    () => columns.map((column) => column.name.trim()).filter(Boolean),
    [columns],
  );

  const updateColumn = (
    index: number,
    field: keyof CreateTableColumn,
    value: string,
  ) => {
    setColumns((current) =>
      current.map((column, position) =>
        position === index
          ? { ...column, [field]: value }
          : column,
      ),
    );
  };

  const addColumn = () => {
    setColumns((current) => [
      ...current,
      {
        name: `columna_${current.length + 1}`,
        type: 'VARCHAR(64)',
      },
    ]);
  };

  const removeColumn = (index: number) => {
    setColumns((current) => {
      if (current.length <= 1) return current;

      const removed = current[index]?.name;
      const next = current.filter((_, position) => position !== index);

      if (removed === primaryKey) {
        setPrimaryKey(next[0]?.name ?? '');
      }

      return next;
    });
  };

  const handleCreate = async () => {
    setWorking(true);
    setError(null);
    setMessage(null);

    try {
      const table = await createTable({
        name: tableName,
        storage_kind: storageKind,
        primary_key: primaryKey,
        columns,
      });

      setMessage(`Tabla "${table.name}" creada correctamente.`);
      await onChanged(table.name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setWorking(false);
    }
  };

  const handleCsvFile = (file: File | null) => {
    setCsvFile(file);

    if (file && !csvTableName.trim()) {
      setCsvTableName(safeTableName(file.name));
    }
  };

  const handleImport = async () => {
    if (!csvFile) {
      setError('Selecciona un archivo CSV.');
      return;
    }

    setWorking(true);
    setError(null);
    setMessage(null);

    try {
      const result = await importCsv(csvFile, {
        name: csvTableName,
        primaryKey: csvPrimaryKey,
        storageKind: csvStorageKind,
      });

      setMessage(
        `CSV importado: ${result.imported_rows} registros en "${result.table.name}".`,
      );
      await onChanged(result.table.name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setWorking(false);
    }
  };

  return (
    <section className="table-manager">
      <div className="table-manager__tabs">
        <button
          type="button"
          className={mode === 'csv' ? 'tab is-active' : 'tab'}
          onClick={() => setMode('csv')}
        >
          Importar CSV
        </button>
        <button
          type="button"
          className={mode === 'create' ? 'tab is-active' : 'tab'}
          onClick={() => setMode('create')}
        >
          Crear tabla
        </button>
      </div>

      {mode === 'csv' ? (
        <div className="form-stack">
          <label className="field">
            <span>Archivo CSV</span>
            <input
              className="file-input"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) =>
                handleCsvFile(event.target.files?.[0] ?? null)
              }
            />
          </label>

          <label className="field">
            <span>Nombre de tabla</span>
            <input
              className="input"
              value={csvTableName}
              onChange={(event) => setCsvTableName(event.target.value)}
              placeholder="clientes"
            />
          </label>

          <div className="form-grid">
            <label className="field">
              <span>Primary key</span>
              <input
                className="input"
                value={csvPrimaryKey}
                onChange={(event) => setCsvPrimaryKey(event.target.value)}
                placeholder="id"
              />
            </label>

            <label className="field">
              <span>Storage</span>
              <select
                className="select select--compact"
                value={csvStorageKind}
                onChange={(event) =>
                  setCsvStorageKind(event.target.value as StorageKind)
                }
              >
                <option value="heap">Heap File</option>
                <option value="sequential">Secuencial</option>
              </select>
            </label>
          </div>

          <p className="panel__hint">
            Se infieren automáticamente INT, FLOAT y VARCHAR(n). La PK debe
            existir en la cabecera y no puede tener duplicados.
          </p>

          <button
            type="button"
            className="button button--primary"
            disabled={
              working ||
              !csvFile ||
              !csvTableName.trim() ||
              !csvPrimaryKey.trim()
            }
            onClick={() => void handleImport()}
          >
            {working ? 'Importando…' : 'Importar CSV'}
          </button>
        </div>
      ) : (
        <div className="form-stack">
          <label className="field">
            <span>Nombre de tabla</span>
            <input
              className="input"
              value={tableName}
              onChange={(event) => setTableName(event.target.value)}
            />
          </label>

          <label className="field">
            <span>Storage</span>
            <select
              className="select select--compact"
              value={storageKind}
              onChange={(event) =>
                setStorageKind(event.target.value as StorageKind)
              }
            >
              <option value="heap">Heap File</option>
              <option value="sequential">Archivo Secuencial</option>
            </select>
          </label>

          <div className="columns-editor">
            <div className="columns-editor__header">
              <strong>Columnas</strong>
              <button
                type="button"
                className="button button--small"
                onClick={addColumn}
              >
                + Columna
              </button>
            </div>

            {columns.map((column, index) => (
              <div className="column-row" key={index}>
                <input
                  className="input"
                  value={column.name}
                  onChange={(event) =>
                    updateColumn(index, 'name', event.target.value)
                  }
                  placeholder="columna"
                />
                <select
                  className="select select--compact"
                  value={column.type}
                  onChange={(event) =>
                    updateColumn(index, 'type', event.target.value)
                  }
                >
                  {TYPE_OPTIONS.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="button button--danger button--icon"
                  disabled={columns.length <= 1}
                  onClick={() => removeColumn(index)}
                  title="Eliminar columna"
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <label className="field">
            <span>Primary key</span>
            <select
              className="select select--compact"
              value={primaryKey}
              onChange={(event) => setPrimaryKey(event.target.value)}
            >
              {availablePrimaryKeys.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            className="button button--primary"
            disabled={
              working ||
              !tableName.trim() ||
              !primaryKey.trim() ||
              columns.some((column) => !column.name.trim())
            }
            onClick={() => void handleCreate()}
          >
            {working ? 'Creando…' : 'Crear tabla'}
          </button>
        </div>
      )}

      {message && (
        <div className="alert alert--success">{message}</div>
      )}
      {error && (
        <div className="alert alert--error">{error}</div>
      )}
    </section>
  );
}
