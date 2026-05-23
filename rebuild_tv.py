#!/usr/bin/env python3
"""
MovieMatch TV Shows Rebuilder
------------------------------
Reads tvshows.json and writes a clean tvshows.json
ready for GitHub (removes internal fields like tmdb_id, streaming_updated).

Run from your MovieMatch folder:
    python3 rebuild_tv.py

Reads:  tvshows.json  (with streaming data + internal fields)
Writes: tvshows.json  (clean version for the app)
"""

import json, sys
from pathlib import Path
from collections import Counter

if not Path('tvshows.json').exists():
    print('ERROR: tvshows.json not found.')
    sys.exit(1)

with open('tvshows.json', 'r', encoding='utf-8') as f:
    shows = json.load(f)

# Keep only indices 0-12 (strip tmdb_id at 14 and streaming_updated at 13)
# Array: [title, year, genre, rating, creator, cast, plot, poster,
#         runtime, trailer, streaming, seasons, status]
clean = []
for s in shows:
    entry = s[:13]  # keep 0-12
    while len(entry) < 13: entry.append(None)
    clean.append(entry)

has_streaming = sum(1 for s in clean if s[10])
genres = Counter(s[2] for s in clean)

print(f'TV shows:      {len(clean):,}')
print(f'Has streaming: {has_streaming:,}')
print(f'Genres: {dict(sorted(genres.items(), key=lambda x:-x[1]))}')

with open('tvshows.json', 'w', encoding='utf-8') as f:
    json.dump(clean, f, ensure_ascii=False, separators=(',',':'))

size = Path('tvshows.json').stat().st_size
print(f'\n✅ tvshows.json rebuilt — {size//1024} KB')
print('Upload tvshows.json to GitHub.')
