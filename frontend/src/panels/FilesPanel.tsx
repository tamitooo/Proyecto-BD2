import { useMemo, useState } from 'react';
import { importCsvIntoTable, runQuery } from '../api';
import type { TableInfo } from '../types';
import TableManager from './TableManager';

interface Props { tables: TableInfo[]; selectedTable: string | null; onSelectTable: (name: string) => void; onTablesChanged: (preferred?: string) => Promise<void>; }
const INDEX_TECHNIQUES = [
  ['HASH', 'Hash Extendible'], ['BPLUS_CLUSTERED', 'B+ agrupado'], ['BPLUS_UNCLUSTERED', 'B+ no agrupado'],
] as const;
type Technique = typeof INDEX_TECHNIQUES[number][0];
const LABEL: Record<string,string> = { hash:'Hash Extendible', bplus_clustered:'B+ agrupado', bplus_unclustered:'B+ no agrupado', rtree:'R-Tree espacial' };
function fmt(bytes:number){ if(bytes<1024)return `${bytes} B`; if(bytes<1048576)return `${(bytes/1024).toFixed(1)} KB`; return `${(bytes/1048576).toFixed(2)} MB`; }

export default function FilesPanel({ tables, selectedTable, onSelectTable, onTablesChanged }: Props) {
  const table = tables.find((t) => t.name === selectedTable) ?? null;
  const [column,setColumn]=useState(''); const [technique,setTechnique]=useState<Technique>('HASH'); const [unique,setUnique]=useState(false); const [busy,setBusy]=useState(false); const [feedback,setFeedback]=useState<string|null>(null);
  const indexed = useMemo(() => new Set(table?.indexes.map(i=>i.column) ?? []), [table]);
  const freeColumns = table?.schema.columnas.filter(([c])=>!indexed.has(c)) ?? [];
  async function createIndex(){ if(!table||!column)return; setBusy(true);setFeedback(null); try{ const suffix={HASH:'hash',BPLUS_CLUSTERED:'bpc',BPLUS_UNCLUSTERED:'bpu'}[technique]; const sql=`CREATE ${unique&&technique==='HASH'?'UNIQUE ':''}INDEX idx_${table.name}_${column}_${suffix} ON ${table.name} (${column}) USING ${technique}`; const r=await runQuery(sql); if(!r.success) throw new Error(r.error??'CREATE INDEX falló'); setFeedback('Índice creado correctamente.'); setColumn(''); await onTablesChanged(table.name);}catch(e){setFeedback(e instanceof Error?e.message:String(e));}finally{setBusy(false);} }
  async function dropIndex(name:string){ if(!table)return; setBusy(true); try{const r=await runQuery(`DROP INDEX ${name} ON ${table.name}`);if(!r.success)throw new Error(r.error??'DROP INDEX falló');await onTablesChanged(table.name);}catch(e){setFeedback(e instanceof Error?e.message:String(e));}finally{setBusy(false);} }
  async function importCsv(file:File|null){if(!table||!file)return;setBusy(true);try{const r=await importCsvIntoTable(table.name,file);setFeedback(`CSV cargado: ${r.inserted ?? 0} filas insertadas.`);await onTablesChanged(table.name);}catch(e){setFeedback(e instanceof Error?e.message:String(e));}finally{setBusy(false);} }
  return <div className="panel files-panel"><h2 className="panel__title">Panel de archivos</h2><p className="panel__hint">Tablas, almacenamiento, esquema e índices.</p>
    <TableManager onChanged={onTablesChanged}/>
    <h3 className="panel__subtitle">Tablas registradas</h3><div className="table-list">{tables.map(t=><button type="button" key={t.name} className={`table-list__item ${t.name===selectedTable?'is-active':''}`} onClick={()=>onSelectTable(t.name)}><span>{t.name}</span><span className="badge">{t.storage_kind}</span></button>)}</div>
    {table&&<><dl className="kv"><div><dt>Registros</dt><dd>{table.row_count}</dd></div><div><dt>Registro</dt><dd>{table.record_size} B</dd></div><div><dt>PK</dt><dd>{table.schema.primary_key}</dd></div></dl>
      <h3 className="panel__subtitle">Esquema</h3><div className="table-scroll"><table className="grid"><thead><tr><th>Columna</th><th>Tipo</th><th>Clave</th></tr></thead><tbody>{table.schema.columnas.map(([c,t])=><tr key={c}><td>{c}</td><td className="mono">{t}</td><td>{c===table.schema.primary_key?'PK':'—'}</td></tr>)}</tbody></table></div>
      <h3 className="panel__subtitle">Índices secundarios</h3><div className="table-scroll table-scroll--indexes"><table className="grid grid--indexes"><thead><tr><th>Nombre</th><th>Columna</th><th>Técnica</th><th>Único</th><th></th></tr></thead><tbody>{table.indexes.map(i=><tr key={i.name}><td className="mono index-name">{i.name}</td><td>{i.column}{i.lon_column?`, ${i.lon_column}`:''}</td><td>{LABEL[i.kind]??i.kind}</td><td>{i.unique?'Sí':'No'}</td><td><button className="button button--small button--danger" disabled={busy||i.column===table.schema.primary_key} onClick={()=>void dropIndex(i.name)}>Eliminar</button></td></tr>)}</tbody></table></div>
      <h3 className="panel__subtitle">Crear índice</h3><div className="form-grid"><label className="field"><span>Columna</span><select className="select" value={column} onChange={e=>setColumn(e.target.value)}><option value="">— seleccionar —</option>{freeColumns.map(([c,t])=><option key={c} value={c}>{c} ({t})</option>)}</select></label><label className="field"><span>Técnica</span><select className="select" value={technique} onChange={e=>setTechnique(e.target.value as Technique)}>{INDEX_TECHNIQUES.map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></label><label className="field field--check"><input type="checkbox" checked={unique} disabled={technique!=='HASH'} onChange={e=>setUnique(e.target.checked)}/><span>Único</span></label></div><button className="button button--primary" type="button" disabled={!column||busy} onClick={()=>void createIndex()}>Crear índice</button>
      <h3 className="panel__subtitle">Archivos en disco</h3>{table.files.map(f=><p key={f.path} className="panel__hint"><span className="mono">{f.label}</span> · {fmt(f.size_bytes)}</p>)}
      <label className="button button--ghost csv-button">Cargar CSV en {table.name}<input hidden type="file" accept=".csv,text/csv" onChange={e=>void importCsv(e.target.files?.[0]??null)}/></label>{feedback&&<div className="alert">{feedback}</div>}</>}
  </div>;
}
