//issue 22
import { useState } from 'react';
import type { CellValue, QueryResult } from '../types';

interface Props {
  result: QueryResult | null;
}

function renderValue(value: CellValue): string {
  if (value === null || value === undefined) return '—';
  return String(value);
}

//: Sentencias que devuelven filas (leen). El resto mutan el almacenamiento.
const READ_STATEMENTS = new Set(['SELECT', 'EXPLAIN', 'ROLLBACK']);

function isReadStatement(statement: string): boolean {
  return READ_STATEMENTS.has(statement.trim().toUpperCase());
}

export default function ResultsPanel({ result }: Props) {
  const [showJson, setShowJson] = useState(false);

  if (!result) {
    return (
      <div className="panel">
        <h2 className="panel__title">Panel de resultados</h2>
        <p className="panel__hint">Ejecuta una consulta para ver los registros devueltos.</p>
      </div>
    );
  }

  if (!result.success) {
    return (
      <div className="panel">
        <h2 className="panel__title">Panel de resultados</h2>
        <div className="alert alert--error">
          <strong>{result.statement}:</strong> {result.error}
        </div>
      </div>
    );
  }

  // Una lectura con 0 filas devuelve columns = []; por eso el tipo de sentencia
  // decide si son filas devueltas o filas afectadas.
  const isRead = isReadStatement(result.statement);

  return (
    <div className="panel">
      <h2 className="panel__title">Panel de resultados</h2>

      <div className="metrics">
        <div className="metric"><span>Sentencia</span><strong>{result.statement}</strong></div>
        {isRead ? (
          <div className="metric"><span>Filas devueltas</span><strong>{result.rows.length}</strong></div>
        ) : (
          <div className="metric"><span>Filas afectadas</span><strong>{result.affected_rows}</strong></div>
        )}
        <div className="metric"><span>Tiempo</span><strong>{result.execution_time_ms.toFixed(3)} ms</strong></div>
      </div>

      {!isRead ? (
        <p className="panel__hint">
          La sentencia se aplicó correctamente sobre el almacenamiento en disco
          {result.affected_rows > 0 ? ` (${result.affected_rows} filas afectadas).` : '.'}
        </p>
      ) : result.rows.length === 0 ? (
        <p className="panel__hint">
          La consulta no devolvió registros. El panel de plan muestra la ruta de
          acceso que se usó.
        </p>
      ) : (
        <>
          <div className="actions">
            <button type="button" className="button" onClick={() => setShowJson((value) => !value)}>
              {showJson ? 'Ver tabla' : 'Ver JSON crudo'}
            </button>
          </div>

          {showJson ? (
            <pre className="code">{JSON.stringify(result.rows, null, 2)}</pre>
          ) : (
            <div className="scroll">
              <table className="grid">
                <thead>
                  <tr>{result.columns.map((column) => <th key={column}>{column}</th>)}</tr>
                </thead>
                <tbody>
                  {result.rows.map((row, index) => (
                    <tr key={index}>
                      {result.columns.map((column) => (
                        <td key={column}>{renderValue(row[column])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}