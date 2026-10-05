import type { ExecutionPlan } from '../types';

export default function PlanPanel({ plan }: { plan: ExecutionPlan | null }) {
  if (!plan) return <div className="panel"><h2 className="panel__title">Plan de ejecución</h2><p className="panel__hint">Ejecuta una consulta para ver el plan.</p></div>;
  const steps = plan.steps ?? [];
  const indexes = plan.used_indexes ?? [];
  const runtime = plan.runtime_steps ?? [];
  return (
    <div className="panel">
      <h2 className="panel__title">Plan de ejecución</h2>
      <dl className="kv kv--single">
        <div><dt>Ruta de acceso</dt><dd className="mono">{plan.access_path ?? '—'}</dd></div>
        <div><dt>Planner</dt><dd>{plan.planner_type ?? '—'}</dd></div>
      </dl>
      <h3 className="panel__subtitle">Índices usados</h3>
      {indexes.length ? <div className="chips">{indexes.map((index) => <span className="chip" key={index}>{index}</span>)}</div> : <p className="panel__hint">Ninguno.</p>}
      <h3 className="panel__subtitle">Plan lógico</h3>
      {steps.length ? steps.map((step, i) => (
        <div className="plan-step" key={`${step.operator}-${i}`}>
          <strong>{i + 1}. {step.operator}</strong>
          {step.index && <span className="chip">{step.index}</span>}
          {step.reason && <p>{step.reason}</p>}
        </div>
      )) : <p className="panel__hint">Sin pasos detallados.</p>}
      {runtime.length > 0 && <>
        <h3 className="panel__subtitle">Ejecución real</h3>
        <div className="table-scroll"><table className="grid"><thead><tr><th>Operador</th><th>Tiempo</th><th>In</th><th>Out</th></tr></thead><tbody>
          {runtime.map((step, i) => <tr key={i}><td className="mono">{String(step.operator ?? '—')}</td><td>{typeof step.elapsed_ms === 'number' ? `${step.elapsed_ms.toFixed(3)} ms` : '—'}</td><td>{step.rows_in ?? '—'}</td><td>{step.rows_out ?? '—'}</td></tr>)}
        </tbody></table></div>
      </>}
    </div>
  );
}
