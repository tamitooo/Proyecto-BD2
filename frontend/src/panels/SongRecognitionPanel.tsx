import * as React from 'react';
import { useEffect, useRef, useState } from 'react';

interface Match {
  track_id: number;
  title: string;
  artist: string;
  genre: string;
  score: number;
  coverage: number;
  mean_similarity: number;
  matched_seconds: number;
  query_active_seconds: number;
  offset_seconds: number;
  reference_start_s: number;
  query_start_s: number;
  clip_start_s: number;
  license_url: string;
  source_page: string;
  audio_url: string;
}
interface AudioResult {
  status: 'ok' | 'silent_or_too_short';
  search_method: string;
  total_seconds: number;
  active_seconds: number;
  silent_seconds: number;
  seconds: Array<{ second: number; active: boolean; rms_db: number }>;
  matches: Match[];
}

function safeLink(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' ? parsed.toString() : undefined;
  } catch { return undefined; }
}

function MatchCard({ match }: { match: Match }) {
  const player = useRef<HTMLAudioElement>(null);
  const jump = () => {
    if (!player.current) return;
    player.current.currentTime = Math.min(19.9, Math.max(0, match.reference_start_s));
    void player.current.play().catch(() => undefined);
  };
  return (
    <li className="song-match">
      <div className="song-match__title">
        <strong>{match.title}</strong> — {match.artist} <small>({match.genre})</small>
      </div>
      <div className="song-match__stats">
        <span>Similitud: {(match.score * 100).toFixed(1)}%</span>
        <span>Alineados: {match.matched_seconds}/{match.query_active_seconds} segundos activos</span>
        <span>Desfase en el clip: {match.reference_start_s} s</span>
      </div>
      <div className="song-match__player">
        <audio ref={player} controls preload="none" src={match.audio_url}
               aria-label={`Reproducir fragmento de 20 s: ${match.title}`} />
        <button type="button" className="button" onClick={jump}>
          Reproducir el momento coincidente
        </button>
      </div>
      <div className="song-match__source">
        {safeLink(match.source_page) && <a href={safeLink(match.source_page)} target="_blank" rel="noreferrer">Pista original</a>}
        {safeLink(match.license_url) && <a href={safeLink(match.license_url)} target="_blank" rel="noreferrer">Licencia y atribución</a>}
      </div>
    </li>
  );
}

export default function SongRecognitionPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [localAudio, setLocalAudio] = useState<string | null>(null);
  useEffect(() => {
    if (!file) { setLocalAudio(null); return; }
    const objectUrl = URL.createObjectURL(file);
    setLocalAudio(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'sql' | 'exact'>('sql');
  const [results, setResults] = useState<AudioResult | null>(null);
  const [error, setError] = useState('');
  const [instalado, setInstalado] = useState<boolean | null>(null);
  useEffect(() => {
    let vigente = true;
    fetch('/api/audio/health')
      .then(r => (r.ok ? r.json() : null))
      .then((b: { installed?: boolean; sql_ivf_ready?: boolean } | null) => {
        if (vigente) setInstalado(b ? Boolean(b.installed && b.sql_ivf_ready) : false);
      })
      .catch(() => { if (vigente) setInstalado(null); });
    return () => { vigente = false; };
  }, []);
  const search = async () => {
    if (!file || loading) return;
    setLoading(true); setError(''); setResults(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(`/api/audio/search?mode=${mode}&k=5&candidates=40`, {
        method: 'POST', body: form,
      });
      const body: unknown = await response.json();
      if (!response.ok) {
        const detail = (body as { detail?: unknown })?.detail;
        throw new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`);
      }
      setResults(body as AudioResult);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setLoading(false); }
  };
  return (
    <section className="panel song-recognition" aria-label="Reconocer una canción por un fragmento">
      <h2 className="panel__title">Reconocimiento de canciones (clips de 20 s)</h2>
      <p className="panel__hint">Compara cada segundo con sonido usando MFCC, ignora el silencio y
        alinea los instantes que coinciden. Los resultados incluyen fragmentos con licencia para escuchar.</p>
      {instalado === false && <div className="alert" role="status">
        El dataset de música no está instalado en este backend. Para usar este panel hay que correr
        {' '}<code>python -m tools.import_music20</code> (ver <code>docs/INTEGRACION_MUSIC20.md</code>).
      </div>}
      <div className="form-grid">
        <label className="field field--wide"><span>Sube un fragmento de música (WAV o MP3; se procesan hasta 25 s)</span>
          <input className="input" type="file" accept="audio/wav,audio/mpeg,audio/ogg,audio/flac,audio/mp4,.wav,.mp3,.ogg,.flac,.m4a"
            disabled={loading} onChange={event => { setFile(event.target.files?.[0] ?? null); setResults(null); setError(''); }} />
        </label>
        <label className="field"><span>Método de búsqueda</span>
          <select className="select" value={mode} disabled={loading} onChange={e => setMode(e.target.value as 'sql' | 'exact')}>
            <option value="sql">SQL del motor + IVF</option>
            <option value="exact">Coseno exacto (línea base)</option>
          </select>
        </label>
      </div>
      {localAudio && <div className="song-match__player">
        <strong>Fragmento subido:</strong>
        <audio controls preload="metadata" src={localAudio} aria-label="Reproducir el fragmento subido" />
      </div>}
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!file || loading || instalado === false} onClick={() => void search()}>
          {loading ? 'Analizando segundos…' : 'Buscar canciones parecidas'}
        </button>
      </div>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {results && <>
        <p className="panel__hint">Analizados {results.total_seconds} s: {results.active_seconds} con sonido, {results.silent_seconds} ignorados por silencio.
          {' '}Método: {results.search_method}.</p>
        <div className="song-timeline" aria-label="Actividad del audio por segundo">
          {(results.seconds ?? []).map(s =>
            <span key={s.second} className={s.active ? 'song-timeline__second song-timeline__second--active' : 'song-timeline__second'}
                  title={`Segundo ${s.second}–${s.second + 1}: ${s.rms_db} dBFS (${s.active ? 'analizado' : 'silencio ignorado'})`}>
              {s.second + 1}
            </span>
          )}
        </div>
        {results.status !== 'ok' && <p role="status">No hay suficiente sonido para identificar una canción. Prueba con un fragmento más largo.</p>}
        {results.status === 'ok' && results.matches.length === 0 && <p role="status">No se encontró una coincidencia confiable alineada en el tiempo.</p>}
        <ol className="song-matches">{results.matches.map(m => <MatchCard key={m.track_id} match={m}/>)}</ol>
        <p className="panel__hint">Mide parecido acústico; no prueba una infracción de derechos de autor ni garantiza que sea la misma canción.</p>
      </>}
    </section>
  );
}
