-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);



-- 1
SELECT * FROM alumnos
WHERE nombre = 'Pérez, Juan';

-- 2
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;

-- 3
SELECT * FROM alumnos
WHERE id = 999;

-- 4
EXPLAIN
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;

-- 5
EXPLAIN ANALYZE
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
