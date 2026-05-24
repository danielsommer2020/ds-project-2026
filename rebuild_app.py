#!/usr/bin/env python3
"""
MovieMatch App Rebuilder
------------------------
Reads movie database JSON and writes movies.json for the app.

Array format:
  [title, year, genre, rating, director, cast, plot, poster,
   runtime, trailer, streaming, ratings]
   0      1     2      3        4         5     6     7
   8       9       10          11
   streaming = {AU:[8,337], US:[8,15]...}
   ratings   = {AU:'MA15+', US:'R', GB:'15'}

Usage:
    python3 rebuild_app.py
    python3 rebuild_app.py movie_database_streaming.json
    python3 rebuild_app.py movie_database_streaming.json index.html
"""

import json, sys, re
from pathlib import Path
from collections import Counter

# ── Resolve input/output files ────────────────────────────────────────────
if len(sys.argv) > 1:
    INPUT_JSON = sys.argv[1]
else:
    for candidate in ['movie_database_streaming.json',
                      'movie_database_full.json',
                      'movie_database.json']:
        if Path(candidate).exists():
            INPUT_JSON = candidate
            break
    else:
        print('ERROR: No database JSON found.')
        sys.exit(1)

if len(sys.argv) > 2:
    APP_HTML = sys.argv[2]
else:
    for candidate in ['index.html', 'MovieMatch13.html', 'MovieMatch.html']:
        if Path(candidate).exists():
            APP_HTML = candidate
            break
    else:
        print('ERROR: No index.html or MovieMatch HTML found.')
        sys.exit(1)

if not Path(INPUT_JSON).exists():
    print(f'ERROR: {INPUT_JSON} not found.')
    sys.exit(1)

print(f'Input:  {INPUT_JSON}')
print(f'Output: {APP_HTML}')

# ── Load and build movies array ───────────────────────────────────────────
with open(INPUT_JSON, 'r', encoding='utf-8') as f:
    movies = json.load(f)

movies_array = []
for m in movies:
    try:
        movies_array.append([
            m.get('title','').strip(),
            int(m.get('year', 0)),
            m.get('genre','').strip(),
            round(float(m.get('rating', 0.0)), 1),
            m.get('director','').strip(),
            ', '.join(m.get('cast','').split(',')[:5]).strip(),
            m.get('plot','').strip()[:220],
            m.get('poster','').strip(),
            int(m.get('runtime', 0)),       # index 8
            m.get('trailer','').strip(),    # index 9
            m.get('streaming', {}),         # index 10
            m.get('ratings', {}),           # index 11 — {AU:'MA15+', US:'R', GB:'15'}
        ])
    except Exception:
        pass

genres       = Counter(m[2] for m in movies_array)
tmdb_count   = sum(1 for m in movies_array if 'image.tmdb.org' in m[7])
stream_count = sum(1 for m in movies_array if m[10])
rating_count = sum(1 for m in movies_array if m[11])

print(f'\nMovies:      {len(movies_array):,}')
print(f'Posters:     {tmdb_count:,} TMDB')
print(f'Streaming:   {stream_count:,} with data')
print(f'Ratings:     {rating_count:,} with data')
print(f'Genres:      {dict(sorted(genres.items(), key=lambda x: -x[1]))}')

# ── Write movies.json ─────────────────────────────────────────────────────
movies_json_path = Path(APP_HTML).parent / 'movies.json'
with open(movies_json_path, 'w', encoding='utf-8') as f:
    json.dump(movies_array, f, ensure_ascii=False, separators=(',',':'))
print(f'✅ movies.json written — {movies_json_path.stat().st_size//1024} KB')

# ── Update HTML ───────────────────────────────────────────────────────────
with open(APP_HTML, 'r', encoding='utf-8') as f:
    html = f.read()

if 'LOADED_ASYNC' in html:
    print(f'✅ {APP_HTML} uses async loading — no data embedding needed')
else:
    html = re.sub(r'const MOVIES=\[.*?\];', 'const MOVIES=[];/*LOADED_ASYNC*/',
                  html, flags=re.DOTALL)
    with open(APP_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✅ {APP_HTML} converted to async loading')

size = Path(APP_HTML).stat().st_size
print(f'\n✅ Done!')
print(f'   {APP_HTML}:   {size//1024} KB')
print(f'   movies.json: {movies_json_path.stat().st_size//1024} KB')
