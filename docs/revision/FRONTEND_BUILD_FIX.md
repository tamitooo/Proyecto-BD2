# Corrección de build del frontend

Se corrigió la incompatibilidad entre `MapPanel.tsx`, `api.ts`, `types.ts`, `TableManager.tsx` y `PlanPanel.tsx` que provocaba errores TypeScript en `npm run build`.

Cambios principales:

- `vite.config.ts` corregido y formateado.
- `tsconfig.app.json` incluye `vite/client` y soporte de imports CSS.
- `tsconfig.node.json` usa `noEmit`, evitando TS5096.
- Contratos espaciales unificados: `SpatialQueryRequest`, `SpatialQueryResult`, `SpatialPoints.label_column`.
- Cliente API unificado: `fetchTables`, `runSpatialQuery`, `importCsvFile`, `importCsvIntoTable`.
- `PlanPanel` tolera planes parciales y tipa correctamente `runtime_steps`.
- `TableManager` usa el contrato real de creación/importación de tablas.
- Panel de índices con scroll horizontal y ancho mínimo para evitar que nombres largos salgan del recuadro.
- Se eliminó el subtítulo “Parte 1 …” del encabezado.
- Panel espacial basado en Leaflet + OpenStreetMap, con rango, k-NN y polígono.

Validación disponible en este entorno:

- `python -m pytest -q` → 27 passed.
- Parseo TypeScript sin errores de sintaxis; los únicos errores del `tsc` del contenedor son módulos React ausentes porque este entorno no tiene `node_modules`.

En la PC de entrega, ejecutar `npm install && npm run build && npm run lint` dentro de `frontend/`.
