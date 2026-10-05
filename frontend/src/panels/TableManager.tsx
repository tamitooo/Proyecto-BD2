import { useState } from 'react';
import { createTable, importCsvFile } from '../api';
import type { CreateTableColumn } from '../types';

export default function TableManager({ onChanged }: { onChanged: (preferred?: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [storage, setStorage] = useState<'heap' | 'sequential'>('heap');
  const [columnsText, setColumnsText] = useState('id INT\nnombre VARCHAR(64)');
  const [pk, setPk] = useState('id');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const parseColumns = (): CreateTableColumn[] => columnsText.split(/\n+/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [col, ...type] = line.split(/\s+/);
    return { name: col, type: type.join(' ') || 'VARCHAR(64)' };
  });

  async function handleCreate() {
    if (!name.trim()) return;
    setBusy(true); setMessage(null);
    try {
      const table = await createTable({ name: name.trim(), storage_kind: storage, primary_key: pk.trim(), columns: parseColumns() });
      setMessage(`Tabla "${table.name}" creada correctamente.`);
      await onChanged(table.name);
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function handleCsv(file: File | null) {
    if (!file || !name.trim()) return;
    setBusy(true); setMessage(null);
    try {
      const result = await importCsvFile(file, { name: name.trim(), primaryKey: pk.trim(), storageKind: storage });
      setMessage(`CSV importado en "${result.table.name}".`);
      await onChanged(result.table.name);
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return <details className="manager"><summary>Crear / importar tabla</summary>
    <div className="form-grid">
      <label className="field"><span>Nombre</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="field"><span>Almacenamiento</span><select className="select" value={storage} onChange={(e) => setStorage(e.target.value as 'heap'|'sequential')}><option value="heap">Heap</option><option value="sequential">Secuencial</option></select></label>
      <label className="field"><span>Clave primaria</span><input className="input" value={pk} onChange={(e) => setPk(e.target.value)} /></label>
      <label className="field field--wide"><span>Columnas (una por línea)</span><textarea className="input input--area" value={columnsText} onChange={(e) => setColumnsText(e.target.value)} /></label>
    </div>
    <div className="button-row"><button className="button" type="button" disabled={busy} onClick={() => void handleCreate()}>Crear tabla</button><label className="button button--ghost">Importar CSV<input hidden type="file" accept=".csv,text/csv" onChange={(e) => void handleCsv(e.target.files?.[0] ?? null)} /></label></div>
    {message && <p className="panel__hint">{message}</p>}
  </details>;
}
