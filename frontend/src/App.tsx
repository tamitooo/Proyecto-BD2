import { useCallback, useEffect, useState } from 'react';
import FilesPanel from './panels/FilesPanel';
import MapPanel from './panels/MapPanel';
import PlanPanel from './panels/PlanPanel';
import QueryPanel from './panels/QueryPanel';
import ResultsPanel from './panels/ResultsPanel';
import TextPanel from './panels/TextPanel';
import MultimediaPanel from './panels/MultimediaPanel';
import Tienda from './tienda/Tienda';
import { fetchTables, runQuery } from './api';
import type { QueryResult, TableInfo } from './types';
import './styles.css';

const DEFAULT_SQL='SELECT * FROM users WHERE age >= 20 ORDER BY age DESC';
type Vista='motor'|'tienda';
const vistaDelHash=():Vista=>window.location.hash.startsWith('#tienda')?'tienda':'motor';
export default function App(){
  const [vista,setVista]=useState<Vista>(vistaDelHash);
  useEffect(()=>{const alCambiar=()=>setVista(vistaDelHash());window.addEventListener('hashchange',alCambiar);return()=>window.removeEventListener('hashchange',alCambiar);},[]);
  const [tables,setTables]=useState<TableInfo[]>([]);const[selectedTable,setSelectedTable]=useState<string|null>(null);const[sql,setSql]=useState(DEFAULT_SQL);const[result,setResult]=useState<QueryResult|null>(null);const[running,setRunning]=useState(false);const[backendError,setBackendError]=useState<string|null>(null);
  const loadTables=useCallback(async(preferred?:string)=>{try{const data=await fetchTables();setTables(data);setSelectedTable(current=>preferred&&data.some(t=>t.name===preferred)?preferred:(current&&data.some(t=>t.name===current)?current:data[0]?.name??null));setBackendError(null);}catch(e){setBackendError(e instanceof Error?e.message:String(e));}},[]);
  useEffect(()=>{void loadTables();},[loadTables]);
  const executeQuery=useCallback(async(text?:string)=>{const query=(typeof text==='string'?text:sql).trim();if(!query)return;setRunning(true);try{const r=await runQuery(query);setSql(query);setResult(r);setBackendError(null);await loadTables();}catch(e){setBackendError(e instanceof Error?e.message:String(e));}finally{setRunning(false);}},[sql,loadTables]);
  return <div className="app"><header className="app__header"><h1>Minigestor de Base de Datos Multimodal</h1><nav className="tabs" aria-label="Vistas"><a className="tabs__link" href="#motor" aria-current={vista==='motor'?'page':undefined}>Motor</a><a className="tabs__link" href="#tienda" aria-current={vista==='tienda'?'page':undefined}>Tienda</a></nav>{backendError&&<div className="alert alert--error">API: {backendError}</div>}</header>{vista==='tienda'?<Tienda/>:<main className="app__body"><aside className="app__side app__side--files"><FilesPanel tables={tables} selectedTable={selectedTable} onSelectTable={setSelectedTable} onTablesChanged={loadTables}/></aside><section className="app__center"><QueryPanel sql={sql} onChangeSql={setSql} onRun={executeQuery} running={running}/><TextPanel tables={tables} selectedTable={selectedTable} onSelectTable={setSelectedTable} onRun={executeQuery} running={running}/><MultimediaPanel tables={tables} selectedTable={selectedTable} onSelectTable={setSelectedTable} onRun={executeQuery} running={running}/><ResultsPanel result={result}/><MapPanel tables={tables} selectedTable={selectedTable} onSelectTable={setSelectedTable}/></section><aside className="app__side"><PlanPanel plan={result?.execution_plan??null}/></aside></main>}</div>;
}
