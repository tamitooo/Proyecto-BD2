import * as React from 'react';
import type { CellValue, QueryResult } from '../types';
import { resultMediaUrl } from '../mediaUrls';

const formatValue = (column: string, value: CellValue): string => {
  if (typeof value === 'number' && /score|relevancia|similitud/i.test(column)) return value.toFixed(4);
  return String(value ?? '');
};

/** Image previews and audio players belong to the actual search-result cells. */
function ResultCell({ column, value }: { column: string; value: CellValue }) {
  const media = resultMediaUrl(column, value);
  if (!media) return <>{formatValue(column, value)}</>;
  if (media.kind === 'audio') {
    return (
      <div className="result-media-cell">
        <audio controls preload="none" src={media.url} aria-label={`Reproducir ${value}`} />
        <span>{value}</span>
      </div>
    );
  }
  return (
    <a className="result-image-link" href={media.url} target="_blank" rel="noopener noreferrer"
       aria-label={`Abrir ${value}`}>
      <img className="result-thumbnail" src={media.url} alt={`Miniatura de ${value}`}
           width={58} height={58} loading="lazy" />
      <span>{value}</span>
    </a>
  );
}

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
              {result.rows.map((row, i) => <tr key={i}>{result.columns.map((c) => <td key={c}><ResultCell column={c} value={row[c]} /></td>)}</tr>)}
            </tbody></table></div>
          )}
        </>
      )}
    </div>
  );
}
