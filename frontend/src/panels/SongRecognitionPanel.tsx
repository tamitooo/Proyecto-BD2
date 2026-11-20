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
        <span>Similarity: {(match.score * 100).toFixed(1)}%</span>
        <span>Aligned: {match.matched_seconds}/{match.query_active_seconds} active seconds</span>
        <span>Clip offset: {match.reference_start_s}s</span>
      </div>
      <div className="song-match__player">
        <audio ref={player} controls preload="none" src={match.audio_url}
               aria-label={`Play 20-second excerpt: ${match.title}`} />
        <button type="button" className="button" onClick={jump}>
          Play matched moment
        </button>
      </div>
      <div className="song-match__source">
        {safeLink(match.source_page) && <a href={safeLink(match.source_page)} target="_blank" rel="noreferrer">Original track</a>}
        {safeLink(match.license_url) && <a href={safeLink(match.license_url)} target="_blank" rel="noreferrer">License and attribution</a>}
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
    <section className="panel song-recognition" aria-label="Recognize a song by excerpt">
      <h2 className="panel__title">Audio recognition — 20-second clips</h2>
      <p className="panel__hint">The system compares each active second using MFCC features, ignores silence,
        and aligns matching timestamps. The results include playable previews of licensed tracks.</p>
      <div className="form-grid">
        <label className="field field--wide"><span>Upload a music excerpt (WAV or MP3, up to 25 s processed)</span>
          <input className="input" type="file" accept="audio/wav,audio/mpeg,audio/ogg,audio/flac,audio/mp4,.wav,.mp3,.ogg,.flac,.m4a"
            disabled={loading} onChange={event => { setFile(event.target.files?.[0] ?? null); setResults(null); setError(''); }} />
        </label>
        <label className="field"><span>Retrieval method</span>
          <select className="select" value={mode} disabled={loading} onChange={e => setMode(e.target.value as 'sql' | 'exact')}>
            <option value="sql">Database SQL + IVF</option>
            <option value="exact">Exact cosine baseline</option>
          </select>
        </label>
      </div>
      {localAudio && <div className="song-match__player">
        <strong>Uploaded comparison clip:</strong>
        <audio controls preload="metadata" src={localAudio} aria-label="Play uploaded comparison clip" />
      </div>}
      <div className="button-row">
        <button className="button button--primary" type="button" disabled={!file || loading} onClick={() => void search()}>
          {loading ? 'Analyzing seconds…' : 'Find matching songs'}
        </button>
      </div>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {results && <>
        <p className="panel__hint">Analyzed {results.total_seconds}s: {results.active_seconds} active, {results.silent_seconds} ignored as silence.
          {' '}Method: {results.search_method}.</p>
        <div className="song-timeline" aria-label="One-second audio activity timeline">
          {(results.seconds ?? []).map(s =>
            <span key={s.second} className={s.active ? 'song-timeline__second song-timeline__second--active' : 'song-timeline__second'}
                  title={`Second ${s.second}–${s.second + 1}: ${s.rms_db} dBFS (${s.active ? 'analyzed' : 'ignored silence'})`}>
              {s.second + 1}
            </span>
          )}
        </div>
        {results.status !== 'ok' && <p role="status">Not enough audible material to identify a song. Try a longer excerpt.</p>}
        {results.status === 'ok' && results.matches.length === 0 && <p role="status">No reliable time-aligned match found.</p>}
        <ol className="song-matches">{results.matches.map(m => <MatchCard key={m.track_id} match={m}/>)}</ol>
        <p className="panel__hint">This measures acoustic similarity, not legal copyright infringement or guaranteed identity.</p>
      </>}
    </section>
  );
}
