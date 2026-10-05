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
    group: 'Mutaciones (INSERT / UPDATE / DELETE)',
    items: [
      { label: 'INSERT nuevo registro', sql: "INSERT INTO users VALUES (9, 'Sofia Lazo', 27, 'CS')" },
      { label: 'UPDATE con condición', sql: "UPDATE users SET age = 21 WHERE id = 3" },
      { label: 'DELETE con condición', sql: 'DELETE FROM users WHERE id = 9' },
    ],
  },
  {
    group: 'DDL: crear y borrar tablas (con carga de CSV)',
    items: [
      {
        label: 'CREATE TABLE alumnos (igual que el script del curso)',
        sql:
          'CREATE TABLE alumnos (\n' +
          '    id INT PRIMARY KEY,\n' +
          '    nombre VARCHAR(100),\n' +
          '    carrera_id INT,\n' +
          '    nota INT\n' +
          ')',
      },
      { label: 'Consultar la tabla nueva', sql: 'SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id' },
      { label: 'DROP TABLE IF EXISTS alumnos (evita el error si ya existía)', sql: 'DROP TABLE IF EXISTS alumnos' },
      { label: 'DROP TABLE alumnos', sql: 'DROP TABLE alumnos' },
    ],
  },
  {
    group: 'Índices: crear y eliminar (CREATE INDEX / DROP INDEX)',
    items: [
      {
        label: 'CREATE INDEX B+ no agrupado sobre users.age',
        sql: 'CREATE INDEX idx_users_age_bpu ON users (age) USING BPLUS_UNCLUSTERED',
      },
      {
        label: 'CREATE UNIQUE INDEX Hash sobre users.name',
        sql: 'CREATE UNIQUE INDEX idx_users_name_hash ON users (name) USING HASH',
      },
      {
        label: 'CREATE INDEX B+ agrupado sobre departments.city (columna libre)',
        sql: 'CREATE INDEX idx_dept_city_bpc ON departments (city) USING BPLUS_CLUSTERED',
      },
      {
        label: 'DROP INDEX del índice creado (IF EXISTS: no falla si no existe)',
        sql: 'DROP INDEX IF EXISTS idx_users_age_bpu ON users',
      },
      {
        label: 'DROP INDEX sin IF EXISTS (falla si el índice no existe)',
        sql: 'DROP INDEX idx_dept_city_bpc ON departments',
      },
    ],
  },
  {
    group: 'Transacciones (BEGIN TRANSACTION / END TRANSACTION / ROLLBACK)',
    items: [
      { label: '1. BEGIN TRANSACTION (abre la transacción)', sql: 'BEGIN TRANSACTION' },
      {
        label: '2. INSERT dentro de la transacción',
        sql: "INSERT INTO users VALUES (99, 'Transitorio Rollback', 20, 'CS')",
      },
      { label: '3. SELECT: el cambio pendiente ya se ve', sql: 'SELECT * FROM users WHERE id = 99' },
      { label: '4a. ROLLBACK (deshace el INSERT pendiente)', sql: 'ROLLBACK' },
      {
        label: '4b. END TRANSACTION (confirma; alternativa a 4a tras el paso 3)',
        sql: 'END TRANSACTION',
      },
      {
        label: '5. Limpieza opcional del registro de prueba',
        sql: 'DELETE FROM users WHERE id = 99',
      },
    ],
  },
  {
    group: 'EXPLAIN: plan lógico y ejecución real',
    items: [
      {
        label: 'EXPLAIN de una consulta',
        sql: 'EXPLAIN SELECT * FROM employees WHERE salary >= 4000 ORDER BY salary',
      },
      {
        label: 'EXPLAIN ANALYZE (con tiempos por operador)',
        sql: 'EXPLAIN ANALYZE SELECT * FROM employees WHERE salary >= 4000 ORDER BY salary',
      },
      { label: 'EXPLAIN de un INSERT', sql: "EXPLAIN INSERT INTO users VALUES (77, 'Test', 20, 'CS')" },
    ],
  },
  {
    group: 'OR, LIMIT y alias de columnas',
    items: [
      { label: 'WHERE con OR', sql: "SELECT * FROM users WHERE age >= 24 OR dept = 'CS'" },
      { label: 'ORDER BY + LIMIT', sql: 'SELECT id, name, salary FROM employees ORDER BY salary DESC LIMIT 2' },
    ],
  },
  {
    // Parte 2 (2.2.3): las dos consultas del enunciado se aceptan TAL CUAL.
    // `ubicacion` es el punto (lat, lon) del índice R-Tree y `mi_ubicacion` es
    // el punto fijado con un clic en el panel de mapa (o con SET).
    group: 'Datos espaciales (Parte 2 · enunciado 2.2.3)',
    items: [
      {
        label: '1) Crear índice R-Tree (ajusta «tiendas» a tu tabla)',
        sql: 'CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE',
      },
      {
        label: '2) Enunciado: tiendas en un radio de 5 km',
        sql: 'SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000',
      },
      {
        label: '3) Enunciado: 10 más cercanos a mi_ubicacion (clic en el mapa)',
        sql: 'SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10',
      },
      {
        label: '4) Fijar mi_ubicacion por SQL',
        sql: 'SET mi_ubicacion = POINT(-12.0464, -77.0428)',
      },
      {
        label: '5) Intersección con polígono',
        sql:
          'SELECT * FROM tiendas WHERE dentro_de(ubicacion, POLYGON((-12.10 -77.10, ' +
          '-12.10 -77.00, -12.00 -77.00, -12.00 -77.10)))',
      },
      {
        label: '6) Métrica Euclidiana (radio en grados)',
        sql: 'SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), EUCLIDEAN) < 0.05',
      },
      {
        label: '7) Plan del k-NN (EXPLAIN ANALYZE)',
        sql: 'EXPLAIN ANALYZE SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10',
      },
    ],
  },
];

export default function QueryPanel({ sql, onChangeSql, onRun, running }: Props) {
  return (
    <div className="panel">
      <h2 className="panel__title">Panel de consultas</h2>
      <p className="panel__hint">
        SELECT / INSERT / UPDATE / DELETE / CREATE TABLE / DROP TABLE / CREATE INDEX /
        DROP INDEX / BEGIN TRANSACTION / END TRANSACTION / ROLLBACK / EXPLAIN / SET ·
        WHERE (=, !=, &lt;&gt;, &lt;, &lt;=, &gt;, &gt;=, BETWEEN, AND, OR) · GROUP BY ·
        ORDER BY · LIMIT · JOIN ... ON · distancia(ubicacion, POINT(...) | mi_ubicacion) ·
        dentro_de(ubicacion, POLYGON(...))
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