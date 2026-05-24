#!/usr/bin/env python3
"""
MovieMatch TV Shows Rebuilder
------------------------------
Reads tvshows.json and writes clean tvshows.json for the app.

Array format:
  [title, year, genre, rating, creator, cast, plot, poster,
   runtime, trailer, streaming, seasons, status, ratings]
   0      1     2      3        4        5     6     7
   8       9       10          11       12      13
   streaming = {AU:[8,337], US:[8,15]...}
   ratings   = {AU:'MA15+', US:'TV-14', GB:'15'}

Usage:
    python3 rebuild_tv.py
"""

import json, sys
from pathlib import Path
from collections import Counter

if not Path('tvshows.json').exists():
    print('ERROR: tvshows.json not found.')
    sys.exit(1)

with open('tvshows.json', 'r', encoding='utf-8') as f:
    shows = json.load(f)

clean = []
for s in shows:
    entry = list(s[:13])          # indices 0-12 (app fields)
    while len(entry) < 13:
        entry.append(None)
    # ratings at index 13 — present if fetch_tv_streaming ran
    ratings = s[13] if len(s) > 13 and isinstance(s[13], dict) else {}
    entry.append(ratings)
    clean.append(entry)

has_streaming = sum(1 for s in clean if s[10])
has_ratings   = sum(1 for s in clean if s[13])
genres        = Counter(s[2] for s in clean)

print(f'TV shows:      {len(clean):,}')
print(f'Has streaming: {has_streaming:,}')
print(f'Has ratings:   {has_ratings:,}')
print(f'Genres: {dict(sorted(genres.items(), key=lambda x:-x[1]))}')

with open('tvshows.json', 'w', encoding='utf-8') as f:
    json.dump(clean, f, ensure_ascii=False, separators=(',',':'))

size = Path('tvshows.json').stat().st_size
print(f'\n✅ tvshows.json rebuilt — {size//1024} KB')
print('Upload tvshows.json to GitHub.')
