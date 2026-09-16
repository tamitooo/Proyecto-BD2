# Guía de trabajo con GitHub Issues y entregables de la Parte 1

Esta guía responde a dos preguntas concretas:

1. **¿Cómo se trabaja un issue en GitHub?** (flujo completo, con comandos)
2. **¿Qué falta y qué ya está listo para el avance de la Parte 1?**

---

## 1. Cómo funciona el flujo de issues

Un *issue* es una tarea. Nadie trabaja directamente sobre `main`: cada
issue se resuelve en una rama (*branch*) y se integra con un *Pull Request*
(PR). El issue se cierra solo cuando el PR se fusiona y el texto del PR
incluye una palabra clave de cierre (`Closes #29`).

```
issue #29  ->  rama  ->  commits  ->  PR ("Closes #29")  ->  revisión  ->  merge  ->  issue cerrado
```

### Paso a paso

```bash
# 0) Partir siempre de main actualizado
git checkout main
git pull origin main

# 1) Crear una rama por issue (nombre corto y descriptivo)
git checkout -b feat/benchmark-heap-vs-secuencial

# 2) Trabajar: agregar/modificar archivos
git status
git add benchmarks/benchmark_heap_vs_sequential.py

# 3) Commit con mensaje tipo "conventional commit" + número de issue
git commit -m "feat(benchmark): comparar Heap File vs Archivo Secuencial (#29)"

# 4) Subir la rama
git push -u origin feat/benchmark-heap-vs-secuencial

# 5) Abrir el Pull Request (la primera vez pide el enlace que imprime git)
#    Título:  feat(benchmark): comparar Heap File vs Archivo Secuencial
#    Cuerpo:  Closes #29
#             - Qué se hizo
#             - Cómo se prueba

# 6) Cuando el PR se fusiona (merge), GitHub cierra el issue automáticamente.
```

### Reglas prácticas

- **Una rama por issue.** Ramas largas con muchos issues se vuelven
  conflictivas.
- **Commits pequeños** y con el número del issue al final: `(#29)`.
- **Palabras que cierran issues**: `Closes #29`, `Fixes #29`, `Resolves #29`.
  Si solo escribes `#29`, GitHub lo enlaza pero **no** lo cierra.
- **Antes de pedir revisión**: correr la suite de pruebas (ver sección 3).
- Si el issue no tiene descripción (nuestro caso), el enunciado del
  proyecto define el entregable: cada issue corresponde a una sección de
  la especificación.

---

## 2. Issues asignados y su entregable

| Issue | Título | Entregable en el repositorio |
|---|---|---|
| #29 | Benchmark Heap vs Sequential | `benchmarks/benchmark_heap_vs_sequential.py`, `benchmark_results/storage_benchmark.{csv,json}` |
| #31 | Generación de gráficas | `benchmarks/generate_charts.py`, `benchmark_results/plots/*.png` |
| #32 | Tabla ventajas/desventajas | `docs/comparacion_ventajas_desventajas.md` |
| #33 | Conclusiones experimentales | `docs/conclusiones_experimentales.md` |
| #34 | Tests unitarios/integración | `tests/test_record.py`, `tests/test_storage_integration.py`, `tests/test_benchmark_heap_vs_sequential.py` |
| #37 | End-to-end integration test | `query/executor.py`, `tests/test_end_to_end.py`, `examples/demo_parte1.py` |

---

## 3. Cómo ejecutar todo

```bash
# Dependencias (solo pruebas y gráficas; el motor usa solo la stdlib)
pip install -r requirements.txt

# Suite completa
python -m pytest -q

# La misma suite sin pytest (módulos basados en unittest)
python -m unittest discover -s tests -t . -v

# Benchmarks
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000
python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000

# Gráficas comparativas
python -m benchmarks.generate_charts

# Demo end-to-end de la Parte 1
python examples/demo_parte1.py
```

---

## 4. Checklist del avance: Parte 1

### 2.1.1 Gestión de archivos y almacenamiento

- [x] Heap File con páginas de disco y reutilización de espacio libre
      (`storage/heap_file.py`, free-list en `.free`)
- [x] Archivo Secuencial Paginado con inserción ordenada, eliminación lazy
      y reorganización al superar el 30 % de desperdicio
      (`storage/sequential_file.py`)
- [x] Esquema/serialización de registros de tamaño fijo (`storage/record.py`)

### 2.1.2 Estructuras de indexación y algoritmos externos

- [x] B+ agrupado (`indexes/clustered_bplus.py`)
- [x] B+ no agrupado (`indexes/unclustered_bplus.py`)
- [x] Hash extendible (`indexes/extendible_hash.py`)
- [x] External Sort k-way merge para `ORDER BY` (`operators/external_sort.py`)
- [x] External Hashing para `GROUP BY` y `JOIN` (`operators/external_hashing.py`)

### 2.1.3 Procesamiento de consultas SQL

- [x] Parser de `SELECT` / `INSERT` / `DELETE` (`query/sql_parser.py`)
- [x] Query Planner basado en reglas con plan de ejecución (`query/query_planner.py`)
- [x] Ejecutor que une parser + planner + storage + índices + algoritmos
      externos (`query/executor.py`)

### 2.1.4 Transacciones y concurrencia

- [ ] `BEGIN/END TRANSACTION`, locks y demostración con hilos
      (**issue #18 y #19, de otro integrante**)

### 2.1.5 Interfaz de usuario (frontend)

- [ ] Paneles de archivos, consultas, resultados y plan de ejecución
      (**issues #20, #21 y #22, de otro integrante**)

### 2.1.6 Comparación experimental

- [x] Benchmark de gestión de archivos (#29)
- [x] Benchmark de índices (existente, regenerado a 1 000 / 10 000 / 100 000)
- [x] Gráficas comparativas (#31)
- [x] Tabla de ventajas/desventajas (#32)
- [x] Conclusiones experimentales (#33)

> Para el avance de la semana 6 el profesor pide **toda la Parte 1**. Los
> bloques de transacciones/concurrencia e interfaz gráfica están asignados
> a otros integrantes: conviene acordar con ellos la fecha de entrega y
> avisar en el issue correspondiente qué falta.

---

## 5. Detalle importante del diseño (contrato de integración)

La reorganización del Archivo Secuencial reescribe `.main` completo, por lo
que **todos los RID cambian**. Cualquier índice construido antes de una
reorganización queda apuntando a posiciones inválidas. Después de
`reorganizar()` hay que reconstruir los índices
(`TableDefinition.rebuild_indexes()`).

Las pruebas `tests/test_storage_integration.py::TestSecuencialConIndices::test_los_rid_cambian_al_reorganizar`
y `tests/test_end_to_end.py::...::test_reorganizacion_no_rompe_las_consultas`
documentan y verifican este comportamiento.
