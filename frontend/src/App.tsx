import { useCallback, useEffect, useState } from 'react';
import FilesPanel from './panels/FilesPanel';
import QueryPanel from './panels/QueryPanel';
import ResultsPanel from './panels/ResultsPanel';
import PlanPanel from './panels/PlanPanel';
import MapPanel from './panels/MapPanel';
import { fetchTables, runQuery } from './api';
import type { QueryResult, TableInfo } from './types';
import './styles.css';

const DEFAULT_SQL = 'SELECT * FROM users WHERE age >= 20 ORDER BY age DESC';

/** Nombre de la tabla creada por un CREATE TABLE exitoso (rows[0].table). */
function createdTableName(result: QueryResult): string | null {
  if (!result.success || result.statement !== 'CREATE TABLE') return null;
  const name = result.rows[0]?.table;
  return typeof name === 'string' ? name : null;
}

export default function App() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);

  /** Recarga el catálogo y, si se pide, deja seleccionada la tabla indicada. */
  const loadTables = useCallback(async (select?: string) => {
    try {
      const data = await fetchTables();
      setTables(data);
      setSelectedTable((current) => {
        if (select && data.some((item) => item.name === select)) return select;
        return current ?? data[0]?.name ?? null;
      });
      setBackendError(null);
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    void loadTables();
  }, [loadTables]);

  const executeQuery = useCallback(async () => {
    if (!sql.trim()) return;
    setRunning(true);
    try {
      const executed = await runQuery(sql.trim());
      setResult(executed);
      setBackendError(null);
      // Recarga archivos y contadores tras INSERT/DELETE/DDL y, si la sentencia
      // creó una tabla, la deja seleccionada para que el siguiente CSV vaya a ella.
      await loadTables(createdTableName(executed) ?? undefined);
    } catch (error) {
      setBackendError(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  }, [sql, loadTables]);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Minigestor de Base de Datos Multimodal</h1>
        <p>Parte 1 · Almacenamiento, indexación, SQL y plan de ejecución</p>
        {backendError && (
          <div className="alert alert--error">
            No se pudo contactar al API ({backendError}). ¿Está corriendo
            <code> uvicorn backend.api:app --port 8000</code>?
          </div>
        )}
      </header>

      <main className="app__body">
        <aside className="app__side">
          <FilesPanel
            tables={tables}
            selectedTable={selectedTable}
            onSelectTable={setSelectedTable}
            onImported={loadTables}
          />
        </aside>
        <section className="app__center">
          <QueryPanel sql={sql} onChangeSql={setSql} onRun={executeQuery} running={running} />
          <ResultsPanel result={result} />
          {/* Quinto panel (Parte 2): mapa de puntos y búsquedas espaciales. */}
          <MapPanel
            tables={tables}
            selectedTable={selectedTable}
            onSelectTable={setSelectedTable}
          />
        </section>
        <aside className="app__side">
          <PlanPanel plan={result?.execution_plan ?? null} />
        </aside>
      </main>
    </div>
  );
}