# Music20 — copyright-aware 20-second music recognition for BD2

This extension does not replace the existing Part 4 SIFT/MFCC → BoAW/TF-IDF
functions. It creates a **separate one-second MFCC fingerprint index** and a
new searchable view. Normal SQL and image search remain unchanged.

## Goal and accuracy boundaries

- **Exactly 20 seconds** of licensed/authorized source music per indexed track.
- Ten genres by default: rock, pop, jazz, electronic, hiphop, classical, metal,
  folk, reggae, blues, targeting **100 unique tracks each** (when the licensed
  catalog actually provides enough eligible items).
- Popularity means **Jamendo's catalog popularity**, not Billboard/Spotify
  hits. No commercial copyrighted music is scraped without permission.
- Every clip retains source artist, title, original link, license, genre,
  source timestamp, and SHA-256 checksum.
- The audio index uses 25ms frames / 10ms hops, 20 MFCC coefficients,
  one-second segment mean+standard deviation (40 dimensions), corpus-wide
  normalization and IVF/cosine search over the project's own SQL engine.
- Segments with RMS below `max(-48dBFS, peak_level - 32dB)` are excluded.
  This avoids mistaking silence for a useful fingerprint.
- Recombine matches by consistent reference-to-query time offset; require
  at least two active matching seconds. Report confidence and coverage.
- The score indicates **acoustic similarity**, not a legal copyright finding.
  It is not a neural music-ID system; timbre changes, covers and remixes can fail.

## Step 1 — apply without overwriting existing code

On Windows PowerShell (use **Proyecto-BD2-clean**, not your original checkout):

```powershell
cd "$HOME\Documents\projects\Proyecto-BD2-clean"
$py = "$HOME\Documents\projects\Proyecto-BD2\.venv\Scripts\python.exe"
$installer = "$HOME\Downloads\BD2_Music20_Patch\apply_music20_patch.py"
& $py $installer --repo . --dry-run
# If no errors:
& $py $installer --repo .
```

This script only adds independent audio files and integrates the API/React
panel via three anchored changes. It refuses unknown conflicts and is
idempotent. It does not modify `vector/extract_features.py`, `vector/bow.py`,
`query/vector_queries.py`, or existing storage/index components.

## Step 2 — Prepare the 10 × 100 legally obtainable tracks

You need a developer account and `JAMENDO_CLIENT_ID` (not provided in this
archive). Read the [Jamendo API terms](https://devportal.jamendo.com/api_terms_of_use).
Only CC BY or CC0 tracks with `audiodownload_allowed = true` and approved
Jamendo storage URLs will be automatically retrieved. The script deliberately
rejects restricted licenses and fails if a genre cannot supply its quota.

```powershell
$env:JAMENDO_CLIENT_ID="YOUR_REGISTERED_JAMENDO_CLIENT_ID"
& $py -m tools.discover_licensed_music --per-genre 100 --output data/music20/manifest.csv
```

You can alternatively supply locally authorized music under the same manifest
schema (`id,title,artist,genre,source_url,license_url,source_page,source_id`).
Local `source_url` paths are interpreted relative to the manifest directory.

Install FFmpeg from an official distribution and verify `ffmpeg -version`.
Then download and preprocess (this may take significant time/network traffic):

```powershell
& $py -m tools.build_music20 --manifest data/music20/manifest.csv --output data/music20 --allow-download
& $py -m tools.build_music20 --verify --output data/music20 --minimum-per-genre 100
& $py -m tools.evaluate_music20 --dataset data/music20 --limit 100
```

Inspect `build_report.json` for per-genre counts, failed items, licenses,
`failures.json` and `catalog.csv`. **Do not claim 1000 completed tracks unless
all 1000 were downloaded and verified.** The ZIP contains the code only,
not music downloads or a prefilled manifest.

The evaluation measures recognition of held-out **time excerpts of indexed
tracks** (top-1, Recall@5, MRR). It does not establish performance on
unseen songs or cross-recording covers, and its offline exact-cosine
results must not be presented as SQL IVF speed/recall measurements.

## Step 3 — Load SQL IVF into a fresh, isolated BD2 database

In one PowerShell terminal:

```powershell
cd "$HOME\Documents\projects\Proyecto-BD2-clean"
$env:BD2_DATA_DIR = (Join-Path (Get-Location) "backend/data/music20_test")
& $py -m uvicorn backend.api:app --port 8000
```

In another terminal (the `--data-dir` **must match** the running backend):

```powershell
cd "$HOME\Documents\projects\Proyecto-BD2-clean"
& $py -m tools.import_music20 --dataset data/music20 --data-dir backend/data/music20_test
```

The importer validates checksums, creates `audio_canciones` and
`audio_segmentos` via the existing CSV API, creates a persisted IVF index
`idx_audio_segmentos_embedding`, checks an actual vector SQL query, and refuses
conflicting datasets/models. It can be rerun idempotently after completion.

Use the existing frontend:

```powershell
cd frontend
npm test
npm run build
npm run dev
```

Open `http://localhost:5173` → **Motor** → **Audio recognition — 20-second
clips**. Upload a music excerpt and select SQL + IVF. You can also compare
the exact-cosine baseline. The UI displays the uploaded audio, one-second
activity timeline (silent vs analyzed), matched titles, source provenance,
match confidence, timestamps and **playable 20-second excerpts**.

API: `GET /api/audio/health`, `POST /api/audio/search?mode=sql&k=5` with
`multipart/form-data` field `file`.

## Step 4 — Tests and acceptance

```powershell
& $py -m pytest -q tests/test_music20_temporal.py tests/test_music20_manifest.py tests/test_music20_pipeline.py
& $py -m pytest -q
cd frontend
npm test
npm run build
```

Tests include silence, exact timestamp alignment, false matches and
repeated-hit deduplication, CC licensing, local path traversal, 20-second
clip extraction, repeatable build, JSON API search, and offline evaluation.
For final acceptance, additionally query **the real SQL IVF index with an
actual authorized music catalog**, inspect top-ranked clips in browser and
measure top-1/Recall@5 on genuinely independent queries.

### Resource and license notes

1000 × 20 seconds of 16kHz mono PCM16 is about 640 MB before database/index
copies. Music files, API keys, generated corpora, and volume data should stay
outside version control. Review Jamendo's specific API terms and each license
before publication or redistribution. If a song is not downloadable or its
license is incompatible, skip it rather than inventing a replacement.
