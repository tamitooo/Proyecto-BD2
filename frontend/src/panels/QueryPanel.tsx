interface Props {
  sql: string;
  onChangeSql: (sql: string) => void;
  onRun: () => void;
  running: boolean;
}

const EXAMPLES = [
  ['Igualdad por Hash', 'SELECT * FROM users WHERE id = 2'],
  ['Rango B+', 'SELECT id, name, salary FROM employees WHERE salary >= 3500 ORDER BY salary'],
  ['JOIN', "SELECT users.name, employees.salary FROM users JOIN employees ON users.dept = employees.dept"],
  ['EXPLAIN ANALYZE', 'EXPLAIN ANALYZE SELECT * FROM employees WHERE salary >= 3500 ORDER BY salary'],
];

export default function QueryPanel({ sql, onChangeSql, onRun, running }: Props) {
  return (
    <div className="panel">
      <h2 className="panel__title">Panel de consultas</h2>
      <p className="panel__hint">Ejecuta SQL contra el motor y observa la ruta de acceso elegida.</p>
      <textarea className="sql-editor" value={sql} onChange={(e) => onChangeSql(e.target.value)} />
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={running} onClick={onRun}>
          {running ? 'Ejecutando…' : 'Ejecutar'}
        </button>
        <select className="select" defaultValue="" onChange={(e) => { if (e.target.value) onChangeSql(e.target.value); e.target.value = ''; }}>
          <option value="">Cargar ejemplo…</option>
          {EXAMPLES.map(([label, value]) => <option key={label} value={value}>{label}</option>)}
        </select>
      </div>
    </div>
  );
}
