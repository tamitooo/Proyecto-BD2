# Revisión del frontend (React + Vite + TS), del puente REST y del recorrido end-to-end del GUI

**Proyecto:** Minigestor de Base de Datos Multimodal — Parte 1
**Alcance revisado:** `frontend/src/**` (App, api, types, 4 paneles, styles.css), `frontend/vite.config.ts`, `frontend/package.json`, `frontend/index.html`, `frontend/README.md`, `backend/api.py`, `backend/engine.py`, y el camino real GUI → REST → motor.
**Estado del árbol:** los cambios del equipo están **sin commitear** (`git status`: `frontend/src/{App,api,styles}.tsx/css` y `frontend/src/panels/{FilesPanel,QueryPanel}.tsx` modificados; `backend/{api,engine}.py` modificados; `query/csv_loader.py` y `tests/test_profesor_script.py` **nuevos y sin trackear**).
**Revisor:** solo lectura. No se modificó ningún archivo del repo; los archivos de trabajo están en `.review_tmp/`.

---

## 1. Resumen ejecutivo y veredicto

**Veredicto: NO está listo para la demo tal como está hoy en esta máquina.**

El requisito funcional nuevo (*"un minigestor más dinámico: aceptar CSV, CREATE TABLE / DROP TABLE desde la interfaz"*) **sí está implementado y funciona de verdad**: probé el recorrido completo contra el API real (`CREATE TABLE → subir CSV → SELECT → EXPLAIN`) y el caso que hizo fracasar la demo del profesor, un CSV con comas dentro de comillas (`3,"Pérez, Juan",1,14`), **se importa correctamente** (12/12 filas, `nombre = "Pérez, Juan"`). El requisito de UI **"el fondo debe ser blanco" NO está implementado en absoluto**: `styles.css` sigue siendo un tema oscuro completo y los cambios sin commitear solo añadieron estilos para el bloque de importación (`.import`, `styles.css:108-113`), **ni una sola regla de fondo claro**.

Los tres riesgos más graves para la demo, en orden:

1. **Fondo oscuro** (`styles.css:2`, `styles.css:17`): el profesor lo pidió explícitamente y no se tocó. Cambiarlo mal (poner `body { background: #fff }` sin migrar la paleta) deja **texto casi blanco sobre blanco** en toda la aplicación, porque `--text: #e2e8f0` (`styles.css:6`) es un color pensado para fondo oscuro.
2. **El template `CREATE TABLE alumnos` del panel de consultas falla en esta máquina**: `backend/data/catalog.json` (ignorado por git, `.gitignore:22`) **ya contiene la tabla `alumnos` con las 12 filas del CSV del profesor**. Al ejecutar el ejemplo tal cual: `success: false — "la tabla ya existe: alumnos"`. Y si se salta el CREATE e importa el CSV, las 12 filas se rechazan por PK duplicada. En vivo, eso se ve como un fracaso, igual que la vez pasada.
3. **El CSV del profesor puede venir separado por `;`** (Excel en español): `api.ts:45` **hardcodea `delimiter: ','`** y la UI no tiene control alguno; con `;` el import devuelve `inserted: 0, failed: N`. La API sí soporta el delimitador (`backend/api.py:44`), pero el frontend nunca lo expone. Además, `api.ts:40` fija `has_header = true` sin control en la UI: un CSV sin cabecera **pierde la primera fila en silencio** (`csv_loader.py:111-118`).

A favor: `tsc -b` compila sin errores, `vite build` genera el bundle correctamente, `oxlint` da 0 errores, los 4 paneles existen y están alimentados con datos reales, el plan de ejecución **sí muestra índices usados, ruta de acceso, orden de operaciones y tiempos**, y no hay XSS ni desajustes de tipos entre `types.ts` y el JSON real.

Con ~2–3 horas de trabajo (paleta clara + selector de delimitador/cabecera + auto-selección de tabla nueva + guarda `DROP TABLE IF EXISTS` en los ejemplos) la demo pasa de "arriesgada" a "sólida".

---

## 2. Tema / fondo blanco: cumplimiento punto por punto

**Conclusión: INCUMPLIDO al 100 %.** Todo el tema es oscuro, no hay ninguna contribución del cambio de última hora hacia fondo claro, y **no existe ninguna `@media (prefers-color-scheme: ...)` ni `color-scheme` en el CSS de la aplicación**.

### 2.1 Paleta base y fondo global — OSCURO

`frontend/src/styles.css:1-11` (todo el tema sale de aquí):

```css
1  :root {
2    --bg: #0f172a;        /* azul noche: fondo de la página */
3    --surface: #1e293b;   /* paneles */
4    --surface-2: #273449; /* inputs, botones, métricas */
5    --border: #334155;
6    --text: #e2e8f0;      /* casi blanco: pensado para fondo oscuro */
7    --muted: #94a3b8;
8    --accent: #38bdf8;
9    --ok: #34d399;
10   --error: #f87171;
11 }
```

`frontend/src/styles.css:15-20`:

```css
15 body {
16   margin: 0;
17   background: var(--bg);   /* ← #0f172a, NO es blanco */
18   color: var(--text);
19   font-family: 'Segoe UI', system-ui, sans-serif;
20 }
```

`frontend/index.html:1-13` **no aporta ningún estilo**: no hay atributo `style`, ni `<style>` embebido, ni meta `color-scheme`, ni clase en `<body>`; solo `<div id="root">` en la línea 10. Es decir, el único origen del color de fondo es `styles.css:17`.

### 2.2 Elemento por elemento (todos oscuros)

| Elemento / zona | Archivo:línea | Valor actual | ¿Fondo claro? |
|---|---|---|---|
| Fondo de página (`body`) | `styles.css:17` | `background: var(--bg)` = `#0f172a` | ❌ oscuro |
| Paneles (4 paneles del enunciado) | `styles.css:36-41` → `37` | `background: var(--surface)` = `#1e293b` | ❌ oscuro |
| Header/título | `styles.css:22-24` | sin fondo propio → hereda `#0f172a` | ❌ oscuro |
| Botones de la lista de tablas | `styles.css:49-53` → `51` | `background: var(--surface-2)` = `#273449` | ❌ oscuro |
| Badge de tipo de almacenamiento | `styles.css:56` | `background: #0b1220` (casi negro) | ❌ oscuro |
| `dl.kv` (registros, PK, tamaño) | `styles.css:59-61` | sin fondo → panel oscuro | ❌ oscuro |
| Tablas `.grid` (`th`, `td`) | `styles.css:63-65` → `64` | sin fondo; borde `#334155`, texto `#e2e8f0` | ❌ oscuro |
| **Editor SQL (`textarea`)** | `styles.css:69-73` → `71` | `background: #0b1220; color: #e2e8f0` | ❌ oscuro |
| `<select>` de ejemplos | `styles.css:75-78` → `76` | `background: var(--surface-2)` | ❌ oscuro |
| Botones (`.button`) | `styles.css:82-85` → `83` | `background: var(--surface-2)` | ❌ oscuro |
| Botón primario "Ejecutar consulta" | `styles.css:87` | `background: var(--accent) #38bdf8; color: #0b1220` | ⚠️ es un botón azul; el texto **sí** es oscuro (correcto para fondo claro) |
| Métricas (sentencia/tiempo/ruta) | `styles.css:89-95` → `91` | `background: var(--surface-2)` | ❌ oscuro |
| Chips de índices usados | `styles.css:98` | `background: #0b1220` | ❌ oscuro |
| Alerta de error | `styles.css:101` | `background: #431a1a` (rojo oscuro) + `color: #f87171` | ❌ oscuro |
| Bloque "Ver JSON crudo" (`.code`) | `styles.css:103-106` → `104` | `background: #0b1220` | ❌ oscuro |
| Bloque de importación CSV | `styles.css:108-113` | **sin fondo propio** → oscuro del panel | ❌ oscuro |
| Texto del `<input type="file">` | `styles.css:112` | `color: var(--text)` = `#e2e8f0` (claro) | ❌ **texto claro sobre el botón nativo claro** (ver D6) |

**Texto claro sobre fondo oscuro que habría que invertir** (todos los anteriores, en particular): `--text: #e2e8f0` (`styles.css:6`) usado en `body:18`, botones `:51`, `:83`, editor `:71`, `<select>:77`; `--muted: #94a3b8` (`:7`) en `:24, :45, :60, :65, :94`; `--border: #334155` (`:5`) en `:22, :38, :51, :64, :71, :77, :83, :91, :98, :101, :104, :109`; y los cuatro fondos casi negros `#0b1220` (`:56, :71, :98, :104`) más `#431a1a` (`:101`).

### 2.3 ¿Hay alguna regla que voltee el tema (dark mode)?

- **No** en el CSS de la aplicación: no existe `prefers-color-scheme` ni `color-scheme` en `frontend/src/styles.css` (búsqueda sobre todo `frontend/src`: la única aparición está en `frontend/src/assets/vite.svg:1`, un logo de Vite con `@media (prefers-color-scheme:dark)` que **no se importa ni se referencia en ninguna parte** — los assets reales del proyecto son `public/favicon.svg` y `public/icons.svg`, referenciados solo en `index.html:5`).
- No hay estilos en línea en ningún `.tsx`: `style=` no aparece ni una vez en `frontend/src/**/*.tsx`. El tema es 100 % CSS.
- Consecuencia práctica: el tema **no** cambia con el sistema operativo; siempre se ve oscuro. Y si alguien añade `background: #fff` solo a `body`, se rompe el contraste en todos los elementos de la tabla de arriba.
- Efecto secundario no deseado hoy: los controles nativos (el `<input type="file">`, la lista desplegable del `<select>`) no declaran `color-scheme`, así que su apariencia depende del tema del sistema operativo mientras el resto de la app es oscuro fijo → inconsistencia visible.

### 2.4 Corrección propuesta (mínima y verificable, para que "el fondo sea blanco" de verdad)

Sustituir `styles.css:1-11` por una paleta clara y ajustar los 6 valores oscuros literales:

```css
:root {
  color-scheme: light;          /* fuerza controles nativos claros */
  --bg: #ffffff;                /* fondo de página BLANCO */
  --surface: #ffffff;           /* paneles blancos */
  --surface-2: #f1f5f9;         /* inputs/botones/métricas */
  --border: #cbd5e1;
  --text: #0f172a;              /* texto oscuro sobre blanco */
  --muted: #475569;
  --accent: #0369a1;
  --ok: #047857;
  --error: #b91c1c;
}
```

Y estos reemplazos puntuales:
`styles.css:38` (`.panel`) añadir `box-shadow: 0 1px 2px rgba(15,23,42,.06);` para que los paneles blancos se distingan del fondo blanco; `styles.css:56` `.badge` → `background:#e2e8f0`; `styles.css:71` `.editor` → `background:#ffffff`; `styles.css:87` `.button--primary` → `color:#ffffff`; `styles.css:98` `.chip` → `background:#ecfdf5`; `styles.css:101` `.alert--error` → `background:#fef2f2; border:1px solid #fca5a5`; `styles.css:104` `.code` → `background:#f8fafc`. Con eso, `styles.css:112` (`color: var(--text)`) pasa a ser oscuro automáticamente y el selector de archivo se vuelve legible.

---

## 3. Flujo CSV: qué hay, qué falta, cómo debe verse la demo

### 3.1 Qué hay implementado (y funciona)

- **Sí hay selección de archivo real desde el navegador**: `<input id="csv-input" type="file" accept=".csv,text/csv">` en `FilesPanel.tsx:102-109`, con `onChange` → `handleFile(event.target.files?.[0])` (`:108`). **No hay** drag & drop ni pegado de texto en un `<textarea>`: solo selector de archivo. Para la demo alcanza.
- **Lectura y envío**: `FilesPanel.tsx:57-58`
  ```ts
  57  const text = await file.text();
  58  const report = await importCsv(selectedTable, text);
  ```
  `api.ts:37-48` hace `POST /api/tables/{tabla}/import` con `{ csv_text, has_header, delimiter }` (`api.ts:42-46`).
- **Endpoint**: `backend/api.py:71-83` → `engine.import_csv` (`engine.py:114-124`) → `query/csv_loader.py:85-146`, que reutiliza el mismo camino que `INSERT` (respeta PK, mantiene índices y reconstruye el archivo secuencial).
- **Éxito**: mensaje `"archivo.csv": 12 filas insertadas en alumnos` (`FilesPanel.tsx:59-62`), contador de rechazadas y hasta 3 errores por fila (`:63-65`).
- **Error de red/servidor**: `catch` → `setImportError(...)` (`FilesPanel.tsx:67-69`) y se pinta en `.import__error` (`:116`, `styles.css:113`). No se traga errores.
- **Refresco posterior**: `await onImported?.()` (`FilesPanel.tsx:66`) → `App.tsx:68 onImported={loadTables}` → `GET /api/tables` y `setTables` (`App.tsx:20-29`). **Sí se refresca el panel de archivos** (contador de registros y tamaños de archivo). Probado: tras importar, `row_count` pasa a 12.
- **El input se limpia** tras cada import (`FilesPanel.tsx:71`), por lo que se puede volver a elegir el mismo archivo.

### 3.2 Qué falta / dónde se rompe

| # | Problema | Evidencia | Impacto en la demo |
|---|---|---|---|
| C1 | **Delimitador fijo a `,`** — Excel en español exporta con `;` | `api.ts:45` (`delimiter: ','`); la API sí acepta `delimiter` (`api.py:44`) pero ningún control de UI lo cambia | Probado: CSV con `;` ⇒ `inserted: 0, failed: 2`, errores `could not convert string to float: '1;Ana;15'`. **Falla total**, igual que la demo anterior |
| C2 | **`has_header` fijo a `true`** | `api.ts:40` (`hasHeader = true`), `FilesPanel.tsx:58` no lo pasa | Un CSV **sin** cabecera pierde la primera fila **en silencio** (probado: `1,Ana,15` desaparece; quedan id 2 y 3). `csv_loader.py:111-118` siempre descarta `rows[0]` y solo cae a "por posición" |
| C3 | **Codificación asumida UTF-8** | `FilesPanel.tsx:57` (`file.text()` siempre decodifica UTF-8) | Un CSV guardado como "CSV (delimitado por comas)" de Excel en Windows-1252 llega con `�` (`Pérez` → `P�rez`). No hay selector de codificación ni fallback |
| C4 | **Destino del import poco visible y persistente** | El input está deshabilitado si no hay tabla (`FilesPanel.tsx:107`), pero el destino es "la tabla seleccionada" y la única señal es `border-color: var(--accent)` (`styles.css:54`) | Riesgo real: tras `CREATE TABLE`, la tabla nueva **no** queda seleccionada (ver D5) y el CSV entra en `users` sin que nadie lo note |
| C5 | **Solo 3 errores** y sin motivo agregado | `FilesPanel.tsx:63-65` (`.slice(0, 3)`) | Reimportar el CSV del profesor muestra "12 rechazadas" y como texto `fila 1: duplicate hash key: 8 · fila 2: ...`, sin decir "claves primarias duplicadas" |
| C6 | Mensaje / error **no se limpian al cambiar de tabla** | `FilesPanel.tsx:48-49` solo se resetean al iniciar otro import | Se queda pegado `"alumnos.csv": 12 filas insertadas en alumnos` mientras se mira otra tabla |
| C7 | No hay vista previa del CSV ni mapeo de columnas | no existe código | Si el CSV tiene otras columnas, se importa **por posición** (`csv_loader.py:116-117`) sin avisar; una fila corta se rellena con `""`/`0` y se cuenta como insertada (probado: `5,Y,2` ⇒ insertada con `nota = 0`) |
| C8 | `VARCHAR(n)` se trunca en silencio | `storage/record.py:62` (`s[:f.size]`) | Nota del motor, no del frontend: 60 caracteres en `VARCHAR(50)` se guardan cortados. Útil mencionarlo si el profesor mira celdas largas |
| C9 | CSV vacío ⇒ error crudo de Pydantic | `api.py:42` (`min_length=1`) ⇒ HTTP 422; `api.ts:6-9` lo pinta como `HTTP 422: {"detail":[{"type":"string_too_short"...}]}` | Feo pero no bloqueante |

### 3.3 Cómo debe verse la demo del CSV (y cumpliría con el profesor)

El caso exacto que pidió —`3,"Pérez, Juan",1,14`— **ya funciona en el código actual**. Secuencia que recomiendo (probada contra el API real):

1. Panel de consultas → elegir en el desplegable **"DDL: crear y borrar tablas (con carga de CSV)" → `DROP TABLE IF EXISTS alumnos`** y ejecutar (evita el fallo D2).
2. Ejecutar `CREATE TABLE alumnos (...)` (el template existente, `QueryPanel.tsx:51-60`).
3. **Clic en `alumnos` en el panel de archivos** (paso imprescindible y hoy poco evidente).
4. Panel de archivos → "Cargar CSV en la tabla seleccionada" → elegir `alumnos_prueba_bd2.csv`.
5. La pantalla debe mostrar: `"alumnos_prueba_bd2.csv": 12 filas insertadas en alumnos` y, en la tabla de arriba, `Registros = 12` + tamaño de `alumnos.dat` actualizado (refresco automático vía `App.tsx:41`/`:68`).
6. `SELECT * FROM alumnos WHERE nombre = 'Pérez, Juan'` ⇒ 1 fila con `Pérez, Juan` completo (esto demuestra el manejo de comas entre comillas, el punto que falló antes).

**Mejoras de UI imprescindibles para que esto sea robusto** (5 líneas de código, ver D3/D4/D5):
- `<select>` de delimitador `,` / `;` / `\t` y `<checkbox>` "el archivo tiene encabezado", pasados a `importCsv` (firma ya lo permite: `api.ts:37-41`).
- Etiqueta con el destino explícito: `Cargar CSV en la tabla seleccionada: {table?.name}` (`FilesPanel.tsx:99-101`).
- Botón grande "Importar CSV" (hoy es el control nativo diminuto del navegador) + `aria-live` en el mensaje.

---

## 4. Flujo DDL dinámico: qué hay, qué falta, affordances recomendadas

### 4.1 Qué hay

- **Sí se puede ejecutar DDL desde el GUI**, escribiendo SQL en el editor (`QueryPanel.tsx:118-130`) y pulsando "Ejecutar consulta" (`:133-135`) o `Ctrl+Enter` (`:124-129`). Verificado end-to-end:
  - `CREATE TABLE alumnos2 (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT)` ⇒ `success: true`, `statement: "CREATE TABLE"`, plan `access_path: CREATE_TABLE`, `used_indexes: ["idx_alumnos2_id_hash"]` (el PK crea un Hash único), y **la tabla aparece en el panel de archivos** porque `App.tsx:41` llama `loadTables()` tras cada sentencia.
  - `DROP TABLE alumnos2` ⇒ `success: true`, `affected_rows: 1`, y desaparece del panel de archivos.
  - `CREATE TABLE ... USING SEQUENTIAL` ⇒ funciona (`storage_kind: sequential`, archivos `.main`/`.aux` visibles en el panel).
  - Persistencia: las tablas creadas por el usuario sobreviven al reinicio (`catalog.json`, `engine.py:145-186`).
- **Sí hay "templates" textuales**: el grupo de ejemplos `'DDL: crear y borrar tablas (con carga de CSV)'` (`QueryPanel.tsx:48-64`) con `CREATE TABLE alumnos`, `SELECT ... alumnos` y `DROP TABLE alumnos`; y el grupo `'EXPLAIN: plan lógico y ejecución real'` (`:65-78`) con `EXPLAIN`, `EXPLAIN ANALYZE` y `EXPLAIN INSERT`.
- La ayuda del panel anuncia el subconjunto soportado (`QueryPanel.tsx:92-96`): `SELECT / INSERT / UPDATE / DELETE / CREATE TABLE / DROP TABLE / EXPLAIN`.

### 4.2 Qué falta (esto es lo que el profesor llamó "más dinámico")

| # | Falta | Evidencia | Veredicto para la demo |
|---|---|---|---|
| D-a | **No hay ningún formulario ni botón dedicado** para crear/borrar tablas o índices: todo es SQL crudo escrito a mano | no existe ningún `onClick` de DDL en `QueryPanel.tsx` (solo el desplegable de ejemplos `:98-116` y el botón ejecutar `:133`) | Se ve "un editor SQL", no un gestor dinámico. Es exactamente lo que el profesor observó. **Recomiendo añadir 3 botones** (abajo) |
| D-b | **`CREATE INDEX` no existe**: ni el parser ni la API lo soportan | `query/sql_parser.py` solo implementa `CREATE TABLE` (`:443-531`) y `DROP TABLE` (`:544`); no hay rama para `CREATE INDEX`. Probado: `CREATE INDEX idx ON t (col)` ⇒ `success:false, statement:"UNKNOWN", error:"Syntax error: se esperaba CREATE TABLE nombre (columna TIPO, ...)"` | Hoy **no se puede demostrar creación de índices desde la UI**. Ojo: no está en el enunciado (§2.1.2 pide las estructuras, no el DDL de índices), así que es opcional; si se quiere mostrar, hay que añadirlo al parser o exponer un endpoint |
| D-c | **No hay selector de tabla activa en el panel de consultas** ni autocompletado de columnas | `QueryPanel.tsx` recibe solo `sql`, `onChangeSql`, `onRun`, `running` (`:3-8`); no recibe `selectedTable` | El usuario teclea `FROM users` a ciegas; en la demo se ve menos "dinámico" |
| D-d | `aplicar el DDL` no cambia la tabla seleccionada en el panel de archivos | `App.tsx:24` (`current ?? data[0]?.name`) mantiene la selección anterior | Tras crear una tabla, el panel sigue mostrando otra; el usuario no ve la tabla nueva "activa" (ver D5) |
| D-e | Los DDL no muestran un resumen de éxito destacado | `ResultsPanel.tsx:53-56`: para CREATE/DROP `columns.length > 0`, así que se pinta la tabla `table/storage/primary_key/columns/indexes` (`query_executor.py:546-557`) | Está bien, pero es una tabla de 1 fila sin mensaje "Tabla alumnos creada" en verde |
| D-f | `UPDATE` no está en el enunciado pero sí en el parser y en los ejemplos (`QueryPanel.tsx:44`) | — | Bien, es un plus |

### 4.3 Affordances recomendadas (con el SQL exacto que enviarían)

Todas se pueden implementar **sin tocar el backend**, porque son atajos que rellenan el editor o llaman a `runQuery` con SQL ya probado.

1. **Botón "Nueva tabla…"** en `QueryPanel` (o en `FilesPanel`), que abra un mini formulario (nombre + 1–4 columnas `nombre:TIPO` + PK + almacenamiento) y envíe, verbatim:
   ```sql
   CREATE TABLE alumnos_demo (
       id INT PRIMARY KEY,
       nombre VARCHAR(100),
       carrera_id INT,
       nota INT
   )
   ```
   (con `USING SEQUENTIAL` opcional; probado: crea `.main`/`.aux` y aparece en el panel de archivos).

2. **Botón "Eliminar tabla seleccionada"** (con confirmación) que envíe:
   ```sql
   DROP TABLE IF EXISTS alumnos
   ```
   `IF EXISTS` (`sql_parser.py:544`) evita el error rojo si ya no existe; probado: `success:true`.

3. **Botón "Cargar CSV" dentro del propio asistente de tabla nueva**: al crear la tabla, **auto-seleccionarla** y dejar el input de archivo listo en el mismo flujo:
   `CREATE TABLE <t> (...)`, después `selectTable(<t>)`, después `POST /api/tables/<t>/import`.

4. **Botón "Ver plan (EXPLAIN)"** junto a "Ejecutar consulta", que envuelva el SQL actual:
   ```sql
   EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id
   ```
   probado: devuelve `execution_plan` con `runtime_steps` y el campo `analyze`.

5. **(Opcional, si se quiere impresionar) `CREATE INDEX`**: requiere implementarlo (parser + catálogo ya tiene `register_index`, `query/catalog.py:322`). El SQL objetivo sería:
   ```sql
   CREATE INDEX idx_alumnos_nota_bplus ON alumnos (nota) USING BPLUS
   ```
   Hoy ese SQL devuelve error de sintaxis (D-b). Alternativa barata para la demo: mostrar la creación de índices desde la API de índice ya existente en el código, o dejar claro en la demo que la PK genera automáticamente el hash (`idx_alumnos_id_hash`) y que ese índice **sí** se usa (ruta `HASH_INDEX_LOOKUP`, ver §5.4).

---

## 5. Los 4 paneles del enunciado (§2.1.5): estado y brechas

### 5.1 Panel de Archivos — ✅ existe, incompleto

`FilesPanel.tsx` (título en `:77`). Muestra: lista de tablas con badge Heap/Secuencial (`:80-96`), nº de registros, tamaño de registro y PK (`:121-125`), **archivos físicos con ruta y tamaño** (`:127-141`), **esquema columna/tipo/clave** (`:143-157`) e **índices secundarios con técnica y unicidad** (`:159-178`). Datos reales de `engine._table_info` (`engine.py:200-221`); probado contra `/api/tables`.

Brechas: (a) solo se ve la estructura de **la tabla seleccionada**, sin resumen global (nº de tablas, tamaño total); (b) no muestra nº de páginas/bloques ni ocupación (el enunciado habla de páginas y 30 % de desperdicio; sería el sitio natural para un indicador); (c) no hay botón "Nueva tabla"/"Refrescar"; (d) no hay vista previa de filas ("ver datos"); (e) el destino del CSV es ambiguo (C4); (f) el nombre del archivo se limpia con `cleanPath` (`:30-37`) que corta en `backend/data`; con el `BD2_DATA_DIR` de pruebas muestra la ruta completa (cosmético).

### 5.2 Panel de Consultas — ✅ existe, es un editor SQL "pelado"

`QueryPanel.tsx`: `+` desplegable con 6 grupos de ejemplos (`:15-86`), editor `textarea` (`:118-130`), botón ejecutar con estado `Ejecutando…` (`:133-135`), botón limpiar (`:136`), ayuda del subconjunto SQL (`:92-96`), `Ctrl+Enter` (`:124-129`). Cobertura funcional buena.

Brechas: sin formularios de DDL (§4.2), sin autocompletado/contexto de tabla, sin "ejecutar selección", sin historial, sin resaltado de sintaxis, y el `<select>` vuelve siempre al placeholder (`value=""` en `:100`) — correcto pero no indica "estás usando el ejemplo X".

### 5.3 Panel de Resultados — ✅ existe y es correcto

`ResultsPanel.tsx`: métricas de sentencia / filas devueltas o afectadas / tiempo (`:43-51`), tabla dinámica de resultados (`:68-83`), vista JSON cruda (`:59-66`), estado sin resultados (`:55-56`), y **error del motor pintado en rojo** con la sentencia (`:26-35`). `renderValue` convierte `null` en `—` (`:9-12`). Los tres formatos (SELECT, mutación, DDL) se ven bien porque `isRead = columns.length > 0` (`:37`) cubre CREATE/DROP, que devuelven columnas (`query_executor.py:546`, `:595`).

Brechas: sin paginación (solo scroll con `max-height: 300px`, `styles.css:67`), sin exportar CSV/JSON, sin ordenar por columna, sin ejecución multi-sentencia, y **la columna `plan` de un `EXPLAIN` sale en una sola línea ilegible** porque `styles.css:64` no define `white-space` (el plan de `query_executor.py:698-737` es multilínea).

### 5.4 Panel de Plan de Ejecución — ✅ existe y **sí muestra índices, orden y tiempos**

`PlanPanel.tsx`: métricas Tabla / **Ruta de acceso** / Optimizador / **Tiempo total** (`:27-32`); **"Índices utilizados"** como chips, con mensaje explícito si no hay ninguno (`:34-41`); **plan lógico** con operador, tabla, índice y justificación (`:43-59`); **ejecución real** con tiempo por operador y filas entrada/salida (`:61-77`). Los datos vienen de `execution_plan` (`types.ts:48-56` ↔ `query_planner.QueryPlan.to_dict()` `query_planner.py:91-98` + `runtime_steps` añadido en `query_executor.py:233-234`, y `total_execution_time_ms` en `:111-114`). Verificado con respuestas reales:
- `EXPLAIN SELECT * FROM alumnos WHERE id = 3` ⇒ `access_path: HASH_INDEX_LOOKUP`, `used_indexes: ["idx_alumnos_id_hash"]` (chip visible).
- `EXPLAIN ANALYZE SELECT * FROM employees WHERE salary >= 4000 ORDER BY salary` ⇒ `BPLUS_CLUSTERED_RANGE_SCAN`, `used_indexes: ["idx_emp_salary_bplus"]`, `runtime_steps` con `elapsed_ms`/`rows_in`/`rows_out`, y `total_execution_time_ms`.
- `EXPLAIN ... WHERE nota >= 14 ORDER BY id` ⇒ `HEAP_SCAN → FILTER → EXTERNAL_SORT` (orden de operaciones visible).

Brechas (ver D9): para **INSERT/DELETE/UPDATE/DROP** el backend devuelve `steps: []` (`query_executor.py:399` para DELETE) y `used_indexes: []`, así que el panel pinta una **tabla de plan lógico con solo encabezados** y el texto *"Ninguno: se resolvió con escaneo secuencial."* (`PlanPanel.tsx:36`), que es incorrecto para un INSERT/DDL; además el resumen `analyze` (`query_executor.py:643-646`) **no se muestra en ninguna parte**, y `details`/`passes`/`partitions_created` de los `runtime_steps` se ignoran (no hay columna "detalle"). Tampoco hay ningún diferenciador visual de "índice usado" frente a "índice mantenido".

---

## 6. Defectos concretos encontrados

Severidad: **CRÍTICO** (bloquea el requisito explícito) · **ALTO** (puede arruinar la demo en vivo) · **MEDIO** (visible / dato incorrecto) · **BAJO** (cosmético / deuda).

| ID | Sev. | Defecto | Evidencia (archivo:línea) | Corrección propuesta |
|---|---|---|---|---|
| **D1** | **CRÍTICO** | **El fondo NO es blanco**: tema oscuro en toda la app | `styles.css:2` (`--bg: #0f172a`), `:17` (`body{background:var(--bg)}`), `:3` (`--surface:#1e293b`), `:37`, `:56`, `:71`, `:98`, `:101`, `:104`; sin `prefers-color-scheme` en ningún `.css`/`.tsx` | Migrar la paleta a claro (§2.4) **completo**: si solo se cambia `body`, el texto `#e2e8f0` (`:6`) queda invisible sobre blanco |
| **D2** | **ALTO** | **El ejemplo `CREATE TABLE alumnos` del panel falla en esta máquina**: `backend/data/catalog.json` ya contiene `alumnos` con 12 filas (dato ignorado por git, `.gitignore:22`) | Probado contra el API: `success:false, error:"la tabla ya existe: alumnos"` (viene de `query/catalog.py:132`); el template está en `QueryPanel.tsx:51-60` | Añadir al template `DROP TABLE IF EXISTS alumnos` como primera sentencia (probado: funciona) o usar `CREATE TABLE alumnos_demo …`; alternativamente borrar `backend/data/` antes de la demo (es data generada, no versionada) |
| **D3** | **ALTO** | **CSV con `;` (Excel español) importa 0 filas** porque el delimitador está fijo | `api.ts:45` (`delimiter: ','`); UI sin control (`FilesPanel.tsx:98-117`) | Añadir `<select>` `,` / `;` / `\t` y pasarlo: `importCsv(table, text, hasHeader, delimiter)` (`api.ts:37-41` ya tiene el parámetro de cabecera, añadir el 4.º) |
| **D4** | **ALTO** | **CSV sin cabecera pierde la primera fila en silencio** | `api.ts:40` (`hasHeader = true` por defecto) + `FilesPanel.tsx:58` (no lo pasa) + `query/csv_loader.py:111-118` (descarta `rows[0]`) | `<input type="checkbox" defaultChecked> "El archivo tiene encabezado"` y pasarlo; si no tiene encabezado, mapear por posición desde la fila 0 |
| **D5** | **ALTO** | **Tras `CREATE TABLE` la tabla nueva no queda seleccionada** y el CSV puede caer en la tabla equivocada | `App.tsx:24` (`setSelectedTable(current => current ?? data[0]?.name ?? null)` no cambia si ya había selección); destino solo señalado por `styles.css:54` | Al detectar un DDL exitoso, seleccionar la tabla nueva (deducir el nombre del `result.rows[0].table`) y mostrar el destino en la etiqueta del import (`FilesPanel.tsx:99-101`) |
| **D6** | **MEDIO** | **El texto del selector de archivo es claro** (`#e2e8f0`) mientras el botón nativo es claro ⇒ casi ilegible en tema claro (y hoy ya es el control menos visible de la demo) | `styles.css:112` (`.import input[type='file'] { color: var(--text) }`), `styles.css:6` | Con la paleta clara de §2.4 se arregla solo; además conviene `input[type=file]{font-size:.8rem}` y un botón propio "Elegir CSV…" |
| **D7** | **MEDIO** | Mensajes de import **pegados** al cambiar de tabla y solo 3 errores mostrados | `FilesPanel.tsx:48-49` (no se resetean al cambiar `selectedTable`), `:63-65` (`.slice(0,3)`) | Limpiar `message`/`importError` en un `useEffect` sobre `selectedTable`; mostrar `errors.length` total y un `<details>` con todas |
| **D8** | **MEDIO** | **El API puede no arrancar**: si `users` queda vacío y `employees` no (p. ej. tras `DROP TABLE users`, alcanzable desde el GUI), el seeding revienta | `engine.py:105-106` (`if seed and self._count(self.users) == 0: self._seed()`) y `engine.py:223-227` (`raise RuntimeError(f"seed falló: {sql} -> {result.error}")`) | Reproducido: `RuntimeError: seed falló: INSERT INTO employees VALUES (10, ...) -> Clave primaria duplicada: 10` y **uvicorn no levanta** (solo se recupera al segundo intento). Sembrar por tabla con su propio `_count(...) == 0`, o envolver cada INSERT en try/except |
| **D9** | **MEDIO** | Plan de ejecución **vacío/mentiroso** en mutaciones y DDL, y el resumen `analyze` no se muestra | `query_executor.py:399` (`"steps": []` en DELETE), `:305-313` (INSERT), `:507-523` (UPDATE), `:608-616` (DROP) con 1 solo paso y `used_indexes` engañoso, `PlanPanel.tsx:36` (mensaje "escaneo secuencial" para cualquier caso), `PlanPanel.tsx:43-59` (tabla sin filas si `steps=[]`), `types.ts:48-56` (no declara `analyze`) | Ocultar la tabla si `steps.length === 0`; mensaje por tipo (DDL/mutación); añadir tarjeta "EXPLAIN ANALYZE" con `execution_plan.analyze.rows`/`execution_time_ms`; añadir columna "detalle" para `passes`/`partitions_created` |
| **D10** | **MEDIO** | **Sin ErrorBoundary ni estados de carga**: un fallo de render o una respuesta inesperada deja **pantalla en blanco**; solo el botón muestra "Ejecutando…" | `main.tsx:5-9` (sin boundary), `App.tsx:73-77` (paneles sin prop de carga), `ResultsPanel.tsx:50` (`result.execution_time_ms.toFixed(3)` sin guarda), `App.tsx:23` (`setTables(data)` sin validar `Array.isArray`) | Envolver `<App/>` en un ErrorBoundary; `Array.isArray(data.tables) ? data.tables : []`; añadir `loading` a Results/Plan con skeleton |
| **D11** | **BAJO** | Un error **borra el plan anterior**: `result.execution_plan` es `null` cuando `success=false`, y el panel vuelve al placeholder | `App.tsx:76` (`result?.execution_plan ?? null`), `ResultsPanel.tsx:26-35` (no pasa plan), `query_result.py:52-57` (fallo sin plan) | Mantener el último plan válido en un estado aparte, o mostrar "sin plan (la sentencia falló)" |
| **D12** | **BAJO** | `index.html` sin identidad del proyecto | `index.html:7` (`<title>frontend</title>`), `:2` (`lang="en"`) | `Minigestor de BD Multimodal`, `lang="es"`, y un `color-scheme: light` meta/`:root` |
| **D13** | **BAJO** | El README del frontend es la plantilla de Vite (no dice cómo levantar la app ni el proxy) | `frontend/README.md:1-32` | Enlazar el README raíz §8 y documentar "2 terminales" |
| **D14** | **BAJO** | `npm run preview`/`dist` **no proxya `/api`** ⇒ la app mostraría "No se pudo contactar al API" | `vite.config.ts:6-11` (proxy solo en `server`, no en `preview`) | Añadir `preview: { proxy: {...} }` o prohibir `preview` en el guion de demo |
| **D15** | **INFO** | `VARCHAR(n)` trunca en silencio al importar CSV | `storage/record.py:62` (`s[:f.size]`) | Nota de motor: avisar/validar longitud en `csv_loader._coerce` (`query/csv_loader.py:69-75`) |

### 6.1 Cosas que revisé y **están bien** (para no perder tiempo)

- **XSS: ninguno.** No hay `dangerouslySetInnerHTML`, ni `innerHTML`, ni `eval` en `frontend/src` (búsqueda exhaustiva); todo se renderiza como texto JSX (`FilesPanel.tsx:136`, `PlanPanel.tsx:55`, `ResultsPanel.tsx:77`). El contenido del CSV nunca se interpola como HTML; los mensajes de error se pintan como texto (`FilesPanel.tsx:116`).
- **Tipos: sin desajustes.** Comparé `types.ts` campo a campo contra el JSON real: `TableInfo` ↔ `engine._table_info` (`engine.py:200-221`) y `Schema.to_dict` (`storage/record.py:78-82`): `name/storage_kind/schema{columnas,primary_key}/indexes{name,column,kind,unique}/files{label,path,size_bytes}/row_count/record_size` — todos coinciden, incluidos los `unique` y los `kind` (`hash|bplus_clustered|bplus_unclustered`). `QueryResult` ↔ `query_result.QueryResult.to_dict()` (`query_result.py:59-68`): idéntico. `ExecutionPlan`/`PlanStep`/`RuntimeStep` ↔ `query_planner.py:73-98` + `query_executor.py:1211-1219`: idéntico (solo falta el extra opcional `analyze`, que no se usa → D9). `CsvImportReport` (`api.ts:27-35`) ↔ `csv_loader.py:37-46`: idéntico.
- **Proxy/CORS bien**: `vite.config.ts:9` `'/api' → http://127.0.0.1:8000` con `changeOrigin`, `api.ts:3` `BASE = '/api'` (relativo, **sin** `localhost:8000` hardcodeado en ninguna llamada — el único `8000` del frontend es el texto de ayuda de `App.tsx:57`), y todas las rutas del API cuelgan de `/api` (`api.py:47, 52, 57, 63, 71, 86`). CORS (`api.py:22-27`) permite `localhost:5173`/`127.0.0.1:5173` aunque el proxy lo hace innecesario.
- **Estados que sí refrescan**: lista de tablas tras *cualquier* sentencia (`App.tsx:41`) y tras importar (`FilesPanel.tsx:66` → `App.tsx:68`); el input de archivo se limpia (`FilesPanel.tsx:71`).
- **Errores no silenciados**: `api.ts:5-11` lanza con el cuerpo de la respuesta no-2xx; `App.tsx:26-28/:42-44` y `FilesPanel.tsx:67-69` los muestran (header y bloque de import respectivamente). El backend nunca lanza en `/api/query` (`api.py:86-89`), así que los errores de SQL llegan como `success:false` y `ResultsPanel.tsx:26-35` los pinta.

---

## 7. Guion de demo de 5 minutos (paso a paso)

**Preparación (5 min antes, fuera del guion; en la máquina del equipo):**

```powershell
# Terminal 1 (raíz del repo)
python -m uvicorn backend.api:app --reload --port 8000     # http://127.0.0.1:8000/docs
# Terminal 2
cd frontend
npm run dev                                               # http://localhost:5173
```
Comprobar `curl.exe http://127.0.0.1:8000/api/health` (README §8.3-8.4). **Antes de exponer**: aplicar D1 (paleta clara) y, si no se alcanza a tocar la UI, sustituir el 1.er paso del guion por `DROP TABLE IF EXISTS alumnos` para no chocar con D2. Tener a mano `tests/fixtures/alumnos_prueba_bd2.csv` (el CSV del profesor, con `3,"Pérez, Juan",1,14`).

| T | Acción en pantalla | SQL que se pega / clic | Qué debe mostrar la pantalla |
|---|---|---|---|
| 0:00–0:20 | Arranque: abrir `http://localhost:5173` | — | Fondo **blanco**, 3 columnas: Panel de archivos (izq.), Consultas + Resultados (centro), Plan de ejecución (der.). Lista con `alumnos`, `departments`, `employees`, `users` y su badge Heap/Secuencial |
| 0:20–0:45 | Panel de archivos: clic en `employees` | — | Esquema `id INT / name VARCHAR(32) / dept VARCHAR(16) / salary FLOAT`, PK `id`, y **índices** `idx_emp_salary_bplus` (B+ Tree agrupado) e `idx_emp_dept_bplus` (B+ Tree no agrupado), con `.main`/`.aux` y sus tamaños |
| 0:45–1:30 | Panel de consultas: cargar ejemplo de índice Hash y ejecutar | Desplegable → "Igualdad por clave (usa índice Hash)": `SELECT * FROM users WHERE id = 2` | Resultados: 1 fila (`Luis Paredes`), tiempo; **Plan de ejecución**: Ruta de acceso `HASH_INDEX_LOOKUP`, chip `idx_users_id_hash`, plan lógico de 1 paso, ejecución real con `elapsed_ms` |
| 1:30–2:15 | Igual con B+ agrupado y un rango | Ejemplo "Rango por salario": `SELECT id, name, salary FROM employees WHERE salary > 3500` | Ruta `BPLUS_CLUSTERED_RANGE_SCAN`, chip `idx_emp_salary_bplus`, 2 filas |
| 2:15–3:00 | **DDL en vivo** (el requisito del profesor) | Pegar y ejecutar: `DROP TABLE IF EXISTS alumnos` y luego el template **DDL: crear y borrar tablas** → `CREATE TABLE alumnos (...)` | `Resultados` con la fila del DDL (`table: alumnos`, `storage: heap`, `primary_key: id`, `indexes: idx_alumnos_id_hash`); **Plan**: `CREATE_TABLE`; y **`alumnos` aparece en el panel de archivos con 0 registros** |
| 3:00–3:45 | **Carga del CSV** (el punto que falló la vez pasada) | Panel de archivos → clic en `alumnos` (¡paso clave!) → "Cargar CSV en la tabla seleccionada" → `alumnos_prueba_bd2.csv` | Mensaje `"alumnos_prueba_bd2.csv": 12 filas insertadas en alumnos` + `Registros: 12` y el tamaño de `alumnos.dat` actualizado |
| 3:45–4:15 | Verificar el caso de las comas entre comillas | `SELECT * FROM alumnos WHERE nombre = 'Pérez, Juan'` | 1 fila con `Pérez, Juan` completo y `nota = 14` (demuestra el parseo correcto del CSV del curso) |
| 4:15–4:45 | Plan sobre la tabla nueva + `EXPLAIN ANALYZE` | `EXPLAIN SELECT * FROM alumnos WHERE id = 3` → luego `EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id` | 1.º: `HASH_INDEX_LOOKUP` + `idx_alumnos_id_hash`. 2.º: `HEAP_SCAN → FILTER → EXTERNAL_SORT` con tiempos y filas por operador, y "Ruta de acceso" en la tarjeta superior |
| 4:45–5:00 | Cierre con `DROP TABLE` | Ejemplo DDL → `DROP TABLE alumnos` | `success`, `affected_rows: 1`, y `alumnos` desaparece del panel de archivos (refresco automático) |

**Frases de seguridad para el profesor** (si pregunta): el import reutiliza el camino de `INSERT` (`csv_loader.py:1-11`), respeta la PK (los duplicados se rechazan y se reportan por fila) y mantiene los índices; `EXPLAIN` devuelve el plan sin ejecutar y `EXPLAIN ANALYZE` añade la traza real con tiempos por operador (`query_executor.py:625-695`).

**Si algo falla en vivo**: (a) excepción de PK duplicada al importar ⇒ la tabla ya tenía datos: hacer `DROP TABLE IF EXISTS <t>` y repetir; (b) "No se pudo contactar al API" ⇒ revisar que uvicorn siga vivo en el 8000 (`App.tsx:54-59` lo dice explícitamente); (c) tabla nueva no seleccionada ⇒ recordar el clic en la lista antes de importar (D5).

---

## Anexo A. Cómo se verificó (y qué no se pudo verificar)

**Verificado ejecutando de verdad:**
- `npx tsc -b --force` en `frontend/` ⇒ **exit 0**, sin errores de tipos (TypeScript 6.0.2, `tsconfig.app.json:1-26` con `noUnusedLocals`/`noUnusedParameters`).
- **Build de producción**: `npm run build` falla *en este entorno* porque el sandbox bloquea el `exec` con el que Vite resuelve `vite.config.ts` en Windows (`spawn EPERM` en `optimizeSafeRealPathSync`), no por un error del código. Repetí el build por la API JS de Vite con `configFile: false` y el mismo plugin React: **`✓ 21 modules transformed`, `dist/index.html` + `assets/index-*.css` (3.61 kB) + `assets/index-*.js` (234.88 kB)**, en 1.18 s. Es decir: **el proyecto compila y empaqueta**.
- `npx oxlint` ⇒ **0 errores, 3 warnings** estructurales (`react/only-export-components` en `QueryPanel.tsx:15` y `FilesPanel.tsx:24`; `react/set-state-in-effect` en `App.tsx:32`). `package.json` es coherente (`react`/`react-dom` `^19.2.8` con `@types/react` `^19.2.18`, `vite ^8.3.0` con `@vitejs/plugin-react ^6.1.1`, `node_modules/` presente con `vite 8.3.0` y `plugin-react 6.1.1`).
- **API real** levantada con `BD2_DATA_DIR` apuntando a una **copia** de `backend/data` (`.review_tmp/data`, para no tocar la data de la demo) y ~40 peticiones: `/api/health`, `/api/tables`, `/api/query` (SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/EXPLAIN/EXPLAIN ANALYZE/errores) y `/api/tables/{t}/import` con los casos límite (comas entre comillas, `;`, sin cabecera, PK duplicada, fila corta, `VARCHAR` desbordado, CSV vacío, tabla inexistente). `backend/data` quedó intacto (mtime de `catalog.json`, `alumnos.dat`, `users.dat` sin cambios: 18/09/2026).

**No se pudo verificar (limitación del entorno, no del código):**
- **Render visual / captura de pantalla**: los navegadores headless (Chrome y Edge) no arrancan dentro del sandbox (`mojo platform_channel: Acceso denegado`, `crashpad` no puede lanzar su servidor). Por eso la sección 2 es un análisis **estático pero exhaustivo** del CSS: todos los colores de la app salen de los 13 valores citados de `styles.css`, así que la conclusión "el fondo es oscuro" es determinista. La única incertidumbre es el color exacto del botón nativo del `<input type="file">`, que depende del tema del SO (D6); conviene una comprobación visual de 30 segundos.
- `npm run dev` (servidor Vite) por la misma causa (Vite necesita `exec` en Windows). El bundle sí se generó y se sirvió en `http://127.0.0.1:8099` con un proxy `/api` propio, sobre el que hice las pruebas de API equivalentes.
- `pytest tests/test_profesor_script.py`: los 15 casos terminan en *error* **solo** por el `teardownClass` (`TemporaryDirectory.cleanup()` → `PermissionError [WinError 5]` al borrar en `%TEMP%` bajo el sandbox). Reproduje a mano, vía API, **todo** lo que ese test cubre (CREATE TABLE → import del CSV real de `tests/fixtures/alumnos_prueba_bd2.csv` → 12/12 insertadas → `WHERE nombre = 'Pérez, Juan'` → 6 filas con `nota >= 14` → `EXPLAIN`/`EXPLAIN ANALYZE` con `HASH_INDEX_LOOKUP`), y **pasa**. En una máquina normal los tests deberían correr; conviene confirmarlo (`python -m pytest tests/test_profesor_script.py -q`) antes de la entrega.

**Archivos de trabajo (fuera del repo de entrega):** `.review_tmp/probe_api.py`, `.review_tmp/probe_api2.py`, `.review_tmp/probe_demo.py`, `.review_tmp/serve.py`, `.review_tmp/verify_build.mjs`, `.review_tmp/data/` (copia), `.review_tmp/dist/` (bundle de la revisión).
