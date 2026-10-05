import type { QueryResult } from '../types';

export default function ResultsPanel({ result }: { result: QueryResult | null }) {
  if (!result) return <div className="panel"><h2 className="panel__title">Resultados</h2><p className="panel__hint">Aún no hay una consulta ejecutada.</p></div>;
  return (
    <div className="panel">
      <h2 className="panel__title">Resultados</h2>
      {!result.success ? <div className="alert alert--error">{result.error ?? 'Error desconocido'}</div> : (
        <>
          <div className="metrics"><span>{result.statement}</span><span>{result.affected_rows} filas</span><span>{result.execution_time_ms.toFixed(3)} ms</span></div>
          {result.rows.length > 0 && (
            <div className="table-scroll"><table className="grid"><thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>
              {result.rows.map((row, i) => <tr key={i}>{result.columns.map((c) => <td key={c}>{String(row[c] ?? '')}</td>)}</tr>)}
            </tbody></table></div>
          )}
        </>
      )}
    </div>
  );
}
