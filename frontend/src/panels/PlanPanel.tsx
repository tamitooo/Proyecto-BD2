//issue 23
import type { ExecutionPlan } from '../types';

interface Props {
  plan: ExecutionPlan | null;
}

export default function PlanPanel({ plan }: Props) {
  if (!plan) {
    return (
      <div className="panel">
        <h2 className="panel__title">Panel de plan de ejecución</h2>
        <p className="panel__hint">
          Ejecuta un SELECT para ver qué ruta de acceso eligió el optimizador y en qué orden
          trabajaron los operadores.
        </p>
      </div>
    );
  }

  const total = plan.total_execution_time_ms ?? 0;

  return (
    <div className="panel">
      <h2 className="panel__title">Panel de plan de ejecución</h2>

      <div className="metrics">
        <div className="metric"><span>Tabla</span><strong>{plan.table}</strong></div>
        <div className="metric"><span>Ruta de acceso</span><strong>{plan.access_path}</strong></div>
        <div className="metric"><span>Optimizador</span><strong>{plan.planner_type}</strong></div>
        <div className="metric"><span>Tiempo total</span><strong>{total.toFixed(3)} ms</strong></div>
      </div>

      <h3 className="panel__subtitle">Índices utilizados</h3>
      {plan.used_indexes.length === 0 ? (
        <p className="panel__hint">Ninguno: se resolvió con escaneo secuencial.</p>
      ) : (
        <ul className="chips">
          {plan.used_indexes.map((index) => <li key={index} className="chip">{index}</li>)}
        </ul>
      )}

      <h3 className="panel__subtitle">Plan lógico (reglas del optimizador)</h3>
      <table className="grid">
        <thead>
          <tr><th>#</th><th>Operador</th><th>Tabla</th><th>Índice</th><th>Justificación</th></tr>
        </thead>
        <tbody>
          {plan.steps.map((step, index) => (
            <tr key={`${step.operator}-${index}`}>
              <td>{index + 1}</td>
              <td className="mono">{step.operator}</td>
              <td>{step.table ?? '—'}</td>
              <td className="mono">{step.index ?? '—'}</td>
              <td>{step.reason || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="panel__subtitle">Ejecución real (instrumentación)</h3>
      <table className="grid">
        <thead>
          <tr><th>#</th><th>Operador</th><th>Tiempo</th><th>Entrada</th><th>Salida</th></tr>
        </thead>
        <tbody>
          {plan.runtime_steps.map((step, index) => (
            <tr key={`${step.operator}-${index}`}>
              <td>{index + 1}</td>
              <td className="mono">{step.operator}</td>
              <td>{step.elapsed_ms !== undefined ? `${step.elapsed_ms.toFixed(3)} ms` : '—'}</td>
              <td>{step.rows_in ?? '—'}</td>
              <td>{step.rows_out ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}