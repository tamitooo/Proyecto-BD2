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

  const isRead = result.columns.length > 0;

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
        <p className="panel__hint">La mutación se aplicó correctamente sobre el almacenamiento en disco.</p>
      ) : result.rows.length === 0 ? (
        <p className="panel__hint">La consulta no devolvió registros.</p>
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