import { useCallback, useEffect, useState } from 'react';
import FilesPanel from './panels/FilesPanel';
import QueryPanel from './panels/QueryPanel';
import ResultsPanel from './panels/ResultsPanel';
import PlanPanel from './panels/PlanPanel';
import { fetchTables, runQuery } from './api';
import type { QueryResult, TableInfo } from './types';
import './styles.css';

const DEFAULT_SQL =
  'SELECT * FROM users WHERE age >= 20 ORDER BY age DESC';

export default function App() {
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [sql, setSql] = useState(DEFAULT_SQL);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [running, setRunning] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);

  const loadTables = useCallback(
    async (preferredTable?: string) => {
      try {
        const data = await fetchTables();
        setTables(data);

        setSelectedTable((current) => {
          if (
            preferredTable &&
            data.some((table) => table.name === preferredTable)
          ) {
            return preferredTable;
          }

          if (
            current &&
            data.some((table) => table.name === current)
          ) {
            return current;
          }

          return data[0]?.name ?? null;
        });

        setBackendError(null);
      } catch (error) {
        setBackendError(
          error instanceof Error ? error.message : String(error),
        );
      }
    },
    [],
  );

  useEffect(() => {
    void loadTables();
  }, [loadTables]);

  const executeQuery = useCallback(async () => {
    if (!sql.trim()) return;

    setRunning(true);

    try {
      setResult(await runQuery(sql.trim()));
      setBackendError(null);

      // Refresca archivos, tamaños y contadores después de INSERT/DELETE.
      void loadTables();
    } catch (error) {
      setBackendError(
        error instanceof Error ? error.message : String(error),
      );
    } finally {
      setRunning(false);
    }
  }, [sql, loadTables]);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Minigestor de Base de Datos Multimodal</h1>
        <p>
          Parte 1 · Almacenamiento, indexación, SQL, CSV y plan de ejecución
        </p>

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
            onTablesChanged={loadTables}
          />
        </aside>

        <section className="app__center">
          <QueryPanel
            sql={sql}
            onChangeSql={setSql}
            onRun={executeQuery}
            running={running}
          />
          <ResultsPanel result={result} />
        </section>

        <aside className="app__side">
          <PlanPanel plan={result?.execution_plan ?? null} />
        </aside>
      </main>
    </div>
  );
}
