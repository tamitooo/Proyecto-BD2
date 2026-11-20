"""Discover popular, redistributable tracks on Jamendo by genre.

NO audio is downloaded. A registered JAMENDO_CLIENT_ID is needed. Selection
uses Jamendo popularity_total, not mainstream Spotify/Billboard charts.
Only CC BY / CC0 tracks that artists explicitly allow downloading are kept.
API results are variable: insufficient valid tracks is an error, not fabricated.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

GENRES = ("rock", "pop", "jazz", "electronic", "hiphop", "classical",
          "metal", "folk", "reggae", "blues")
FIELDS = ("id", "title", "artist", "genre", "source_url", "license_url", "source_page", "source_id")
API = "https://api.jamendo.com/v3.0/tracks/"


def permitted_track(track: dict) -> bool:
    """Conservative automatic license filter: CC0 or CC BY only."""
    license_url = str(track.get("license_ccurl", "")).lower().replace("http:", "https:")
    parsed = urlparse(license_url)
    if parsed.hostname != "creativecommons.org":
        return False
    path = parsed.path.rstrip("/") + "/"
    licensed = path.startswith("/licenses/by/") or path.startswith("/publicdomain/zero/")
    src = str(track.get("audiodownload", ""))
    host = urlparse(src)
    # Jamendo's API returns download URLs such as
    # https://prod-1.storage.jamendo.com/download/track/... . Only trust
    # Jamendo's storage CDN, not arbitrary hosts or user-provided redirects.
    hostname = (host.hostname or "").lower()
    trusted_download = (hostname == "storage.jamendo.com"
                        or hostname.endswith(".storage.jamendo.com"))
    return (licensed and track.get("audiodownload_allowed") is True
            and host.scheme == "https" and trusted_download
            and int(track.get("duration") or 0) >= 20)


def fetch_page(client_id: str, genre: str, offset: int, limit: int = 200) -> list[dict]:
    if not client_id or genre not in GENRES or not 0 <= offset <= 10000:
        raise ValueError("invalid credentials/genre/offset")
    params = urlencode({"client_id": client_id, "format": "json", "limit": limit,
                        "offset": offset, "tags": genre, "order": "popularity_total",
                        "include": "licenses musicinfo stats"})
    request = Request(f"{API}?{params}", headers={"User-Agent": "BD2-Academic-CC-Audio/1.0"})
    with urlopen(request, timeout=25) as response:
        payload = json.load(response)
    if payload.get("headers", {}).get("status") != "success":
        raise RuntimeError(f"Jamendo API error: {payload.get('headers')}")
    return payload.get("results", [])


def discover(client_id: str, *, per_genre: int = 100, page_fetcher=fetch_page,
             pause: float = 0.3) -> list[dict]:
    if not 1 <= per_genre <= 200:
        raise ValueError("per_genre must be 1..200")
    selected, seen = [], set()
    for genre in GENRES:
        hits = 0
        for offset in range(0, 4000, 200):
            page = page_fetcher(client_id, genre, offset, 200)
            for track in page:
                identifier = str(track.get("id") or "")
                # Requested genre must actually appear in source classification,
                # when Jamendo provides the musicinfo tag list.
                declared_genres = (track.get("musicinfo") or {}).get("tags", {}).get("genres", [])
                if declared_genres and genre not in [str(g).lower() for g in declared_genres]:
                    continue
                if identifier in seen or not permitted_track(track):
                    continue
                seen.add(identifier)
                selected.append({"id": str(len(selected)+1), "title": str(track.get("name") or ""),
                                 "artist": str(track.get("artist_name") or ""), "genre": genre,
                                 "source_url": str(track["audiodownload"]),
                                 "license_url": str(track["license_ccurl"]),
                                 "source_page": str(track.get("shareurl") or track.get("shorturl") or ""),
                                 "source_id": identifier})
                hits += 1
                if hits >= per_genre:
                    break
            if hits >= per_genre or len(page) < 200:
                break
            if pause:
                time.sleep(pause)
        if hits < per_genre:
            raise RuntimeError(f"genre {genre} has only {hits}/{per_genre} eligible tracks; "
                               "choose licensed local data or reduce --per-genre; no synthetic fillers added")
    return selected


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--client-id", default=os.getenv("JAMENDO_CLIENT_ID", ""))
    p.add_argument("--per-genre", type=int, default=100)
    p.add_argument("--output", type=Path, default=Path("data/music20/manifest.csv"))
    args = p.parse_args(argv)
    if not args.client_id:
        p.error("register a Jamendo developer client id and set JAMENDO_CLIENT_ID")
    rows = discover(args.client_id, per_genre=args.per_genre)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} downloadable CC BY/CC0 tracks in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
