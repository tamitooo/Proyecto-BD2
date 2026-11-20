"""Guarded, idempotent audio-recognition extension installer for Proyecto-BD2.

Run from any location, with --repo pointing to the clean BD2 feature checkout.
Does not reset Git, touch the original checkout, or overwrite unrelated files.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = (
    "audio_recognition/__init__.py",
    "audio_recognition/temporal.py",
    "backend/audio_routes.py",
    "frontend/src/panels/SongRecognitionPanel.tsx",
    "frontend/src/panels/SongRecognitionPanel.test.ts",
    "frontend/src/panels/song-recognition.css",
    "tools/apply_music20_patch.py",
    "tools/discover_licensed_music.py",
    "tools/build_music20.py",
    "tools/import_music20.py",
    "tools/evaluate_music20.py",
    "tests/test_music20_temporal.py",
    "tests/test_music20_manifest.py",
    "tests/test_music20_pipeline.py",
    "docs/INTEGRACION_MUSIC20.md",
)


def splice(text: str, before: str, after: str, file: str) -> str:
    if after in text:
        return text
    if text.count(before) != 1:
        raise ValueError(f"{file}: expected one anchor {before!r}; merge manually, no files changed")
    return text.replace(before, after, 1)


def modified_files(repo: Path) -> dict[Path, bytes]:
    result = {}
    for path in NEW:
        source, dest = ROOT / path, repo / path
        if not source.is_file():
            raise ValueError(f"patch missing source file: {source}")
        data = source.read_bytes()
        if dest.is_file() and dest.read_bytes() != data:
            raise ValueError(f"existing {dest} differs from this patch; merge manually")
        if not dest.exists():
            result[dest] = data

    # Backend: register dedicated API route. Avoid touching existing media and SQL endpoints.
    target = repo / "backend/api.py"
    if not target.is_file():
        raise ValueError("missing backend/api.py")
    old = target.read_bytes()
    text = old.decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    text = splice(text, "from backend.engine import DemoEngine" + nl,
                  "from backend.engine import DemoEngine" + nl +
                  "from backend.audio_routes import router as music20_router" + nl,
                  "backend/api.py")
    if "app.include_router(music20_router)" not in text:
        lines = text.splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines) if line.startswith("app=FastAPI(") or line.startswith("app = FastAPI(")]
        if len(matches) != 1:
            raise ValueError("backend/api.py: unable to locate FastAPI app initialization")
        lines.insert(matches[0]+1, "app.include_router(music20_router)"+nl)
        text="".join(lines)
    if text.encode("utf-8") != old:
        result[target] = text.encode("utf-8")

    # Frontend: render an independent panel directly after MultimediaPanel.
    target = repo / "frontend/src/App.tsx"
    if not target.is_file():
        raise ValueError("missing frontend/src/App.tsx")
    old = target.read_bytes()
    text = old.decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    text = splice(text, "import MultimediaPanel from './panels/MultimediaPanel';"+nl,
                  "import MultimediaPanel from './panels/MultimediaPanel';"+nl+
                  "import SongRecognitionPanel from './panels/SongRecognitionPanel';"+nl,
                  "frontend/src/App.tsx")
    marker = '<MultimediaPanel tables={tables} selectedTable={selectedTable} onSelectTable={setSelectedTable} onRun={executeQuery} running={running}/>'
    text=splice(text, marker, marker+'<SongRecognitionPanel/>', "frontend/src/App.tsx")
    if text.encode("utf-8") != old:
        result[target] = text.encode("utf-8")

    # Main CSS entry: test runner cannot import CSS directly through tsx.
    target = repo / "frontend/src/main.tsx"
    if not target.is_file():
        raise ValueError("missing frontend/src/main.tsx")
    old = target.read_bytes()
    text = old.decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    css = "import './panels/song-recognition.css';"
    if css not in text:
        text=splice(text, "import './styles.css';"+nl,
                    "import './styles.css';"+nl+css+nl,
                    "frontend/src/main.tsx")
    if text.encode("utf-8") != old:
        result[target] = text.encode("utf-8")
    return result


def main(argv=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args(argv)
    repo=args.repo.resolve()
    if not (repo/'.git').exists() or not (repo/'frontend/src/App.tsx').exists():
        print('ERROR: --repo must be the root of Proyecto-BD2 (Git worktrees supported)', file=sys.stderr)
        return 2
    try:
        changes=modified_files(repo)
    except (ValueError,OSError,UnicodeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    for path,data in changes.items():
        print(('would update: ' if args.dry_run else 'update: ')+str(path.relative_to(repo))+
              f' ({len(data)} bytes)')
    if args.dry_run:
        print(f'{len(changes)} changes planned; no files changed')
        return 0
    if not changes:
        print('Audio extension already applied; no changes')
        return 0
    backup=Path(tempfile.mkdtemp(prefix='BD2_Music20_Backup_'))
    try:
        for path in changes:
            if path.exists():
                dest=backup/path.relative_to(repo)
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,dest)
        for path,data in changes.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(data)
        print(f'Applied {len(changes)} changes. Backups of updated files: {backup}')
    except OSError as exc:
        print(f'ERROR applying changes: {exc}. Backups at {backup}',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
