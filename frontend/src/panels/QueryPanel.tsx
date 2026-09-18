//issue 21

interface Props {
  sql: string;
  onChangeSql: (sql: string) => void;
  onRun: () => void;
  running: boolean;
}

interface Example {
  label: string;
  sql: string;
}

export const EXAMPLE_GROUPS: { group: string; items: Example[] }[] = [
  {
    group: 'Búsqueda y filtros (WHERE)',
    items: [
      { label: 'Igualdad por clave (usa índice Hash)', sql: 'SELECT * FROM users WHERE id = 2' },
      { label: 'Filtro con AND', sql: "SELECT id, name FROM users WHERE age >= 20 AND dept = 'CS'" },
      { label: 'Rango con BETWEEN', sql: 'SELECT * FROM users WHERE age BETWEEN 19 AND 22' },
      { label: 'ORDER BY descendente', sql: 'SELECT id, name, age FROM users ORDER BY age DESC' },
    ],
  },
  {
    group: 'Almacenamiento secuencial e índices B+',
    items: [
      { label: 'Orden por clave (B+ agrupado)', sql: 'SELECT id, name, salary FROM employees ORDER BY salary ASC' },
      { label: 'Rango por salario', sql: 'SELECT id, name, salary FROM employees WHERE salary > 3500' },
      { label: 'GROUP BY con COUNT y AVG', sql: 'SELECT dept, COUNT(*) AS total, AVG(salary) AS promedio FROM employees GROUP BY dept' },
    ],
  },
  {
    group: 'JOIN (External Hashing)',
    items: [
      { label: 'Equi-JOIN entre dos tablas', sql: 'SELECT users.name, employees.id FROM users JOIN employees ON users.dept = employees.dept' },
      { label: 'JOIN con todas las columnas', sql: 'SELECT * FROM users JOIN employees ON users.dept = employees.dept' },
    ],
  },
  {
    group: 'Mutaciones (INSERT / DELETE)',
    items: [
      { label: 'INSERT nuevo registro', sql: "INSERT INTO users VALUES (9, 'Sofia Lazo', 27, 'CS')" },
      { label: 'DELETE con condición', sql: 'DELETE FROM users WHERE id = 9' },
    ],
  },
];

export default function QueryPanel({ sql, onChangeSql, onRun, running }: Props) {
  return (
    <div className="panel">
      <h2 className="panel__title">Panel de consultas</h2>
      <p className="panel__hint">
        SELECT / INSERT / DELETE · WHERE (=, !=, &lt;&gt;, &lt;, &lt;=, &gt;, &gt;=, BETWEEN, AND) ·
        GROUP BY · ORDER BY · JOIN ... ON. Sin OR, sin LIMIT y sin alias de tabla.
      </p>

      <select
        className="select"
        value=""
        onChange={(event) => {
          const found = EXAMPLE_GROUPS
            .flatMap((group) => group.items)
            .find((item) => item.sql === event.target.value);
          if (found) onChangeSql(found.sql);
        }}
      >
        <option value="" disabled>Cargar consulta de ejemplo…</option>
        {EXAMPLE_GROUPS.map((group) => (
          <optgroup key={group.group} label={group.group}>
            {group.items.map((item) => (
              <option key={item.label} value={item.sql}>{item.label}</option>
            ))}
          </optgroup>
        ))}
      </select>

      <textarea
        className="editor"
        value={sql}
        spellCheck={false}
        placeholder="SELECT * FROM users"
        onChange={(event) => onChangeSql(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onRun();
          }
        }}
      />

      <div className="actions">
        <button type="button" className="button button--primary" onClick={onRun} disabled={running}>
          {running ? 'Ejecutando…' : 'Ejecutar consulta'}
        </button>
        <button type="button" className="button" onClick={() => onChangeSql('')}>Limpiar</button>
        <span className="panel__hint">Ctrl + Enter</span>
      </div>
    </div>
  );
}