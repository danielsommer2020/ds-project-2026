#!/usr/bin/env python3
"""
MovieMatch — Incremental Streaming Data Fetcher
-------------------------------------------------
Skips movies with streaming data updated within the last 6 days.
Weekly runs take ~3-5 minutes (only stale/new movies re-fetched).
First run takes ~25 minutes.

Usage:
    python3 fetch_streaming.py                          # local run
    TMDB_API_KEY=xxx python3 fetch_streaming.py         # CI/GitHub Actions

Reads:  movie_database_streaming.json (or movie_database_full.json on first run)
Writes: movie_database_streaming.json
"""

import requests, json, time, sys, os
from pathlib import Path
from datetime import datetime, timezone

# API key from env var (GitHub Actions) or hardcoded fallback (local)
API_KEY     = os.environ.get('TMDB_API_KEY', '12fcc24f6de2c9f3ddeec1aad8ba2146')
BASE        = 'https://api.themoviedb.org/3'
REGIONS     = ['AU','US','GB','NZ','CA']
DELAY       = 0.15
SAVE_EVERY  = 150
STALE_DAYS  = 6     # re-fetch data older than this many days

# Use streaming JSON if it exists, else fall back to full database
INPUT_JSON  = 'movie_database_streaming.json' \
              if Path('movie_database_streaming.json').exists() \
              else 'movie_database_full.json' \
              if Path('movie_database_full.json').exists() \
              else 'movie_database.json'
OUTPUT_JSON = 'movie_database_streaming.json'

def api(path, params=None, retries=4):
    url = f'{BASE}{path}'
    p   = {'api_key': API_KEY, 'language': 'en-US'}
    if params: p.update(params)
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=15)
            if r.status_code == 429:
                wait = int(r.headers.get('Retry-After', 15))
                print(f'  Rate limited — waiting {wait}s...')
                time.sleep(wait); continue
            if r.ok: return r.json()
        except requests.exceptions.Timeout:
            time.sleep(5 * (attempt+1))
        except Exception:
            time.sleep(3)
    return {}

def is_stale(movie):
    """Return True if streaming data needs refreshing."""
    if 'streaming' not in movie: return True
    updated = movie.get('streaming_updated', 0)
    if not updated: return True
    age_days = (time.time() - updated) / 86400
    return age_days >= STALE_DAYS

# ── Load provider directory ───────────────────────────────────────────────
print('Fetching provider directory...')
provider_map = {}
for region in REGIONS:
    data = api('/watch/providers/movie', {'watch_region': region})
    for p in data.get('results', []):
        pid = p['provider_id']
        if pid not in provider_map:
            provider_map[pid] = {
                'name':      p['provider_name'],
                'logo_path': p.get('logo_path', '')
            }
    time.sleep(DELAY)
print(f'Loaded {len(provider_map)} providers\n')

with open('providers.json', 'w', encoding='utf-8') as f:
    json.dump(provider_map, f, ensure_ascii=False, indent=2)

# ── Load database ─────────────────────────────────────────────────────────
if not Path(INPUT_JSON).exists():
    print(f'ERROR: No database file found. Run tmdb_fetch.py first.')
    sys.exit(1)

with open(INPUT_JSON, 'r', encoding='utf-8') as f:
    movies = json.load(f)

stale    = [m for m in movies if is_stale(m)]
fresh    = len(movies) - len(stale)
now_str  = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

print(f'Database:   {len(movies)} movies')
print(f'Up to date: {fresh} (skipping)')
print(f'To update:  {len(stale)}')
print(f'Run time:   ~{max(1, len(stale)//200)} minutes\n')

if not stale:
    print('✅ All streaming data is fresh — nothing to do.')
    sys.exit(0)

updated   = 0
not_found = 0
tmdb_cache = {}

for i, movie in enumerate(movies):
    if not is_stale(movie):
        continue

    title = movie.get('title', '')
    year  = movie.get('year', 0)
    key   = f"{title.lower()}-{year}"

    # Get TMDB ID
    tmdb_id = tmdb_cache.get(key)
    if not tmdb_id:
        data = api('/search/movie', {'query': title, 'year': year})
        results = data.get('results', [])
        if not results:
            data = api('/search/movie', {'query': title})
            results = data.get('results', [])
        if results:
            tmdb_id = results[0]['id']
            tmdb_cache[key] = tmdb_id
        time.sleep(DELAY)

    if not tmdb_id:
        movie['streaming']         = {}
        movie['streaming_updated'] = time.time()
        not_found += 1
        continue

    # Fetch all regions at once
    data    = api(f'/movie/{tmdb_id}/watch/providers')
    results = data.get('results', {})

    streaming = {}
    for region in REGIONS:
        flatrate = results.get(region, {}).get('flatrate', [])
        if flatrate:
            streaming[region] = [p['provider_id'] for p in flatrate]

    movie['streaming']         = streaming
    movie['streaming_updated'] = time.time()
    updated += 1
    time.sleep(DELAY)

    done = updated + not_found
    if done % SAVE_EVERY == 0:
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(movies, f, ensure_ascii=False, indent=2)
        pct = done / len(stale) * 100
        print(f'  {done}/{len(stale)} ({pct:.0f}%) — {updated} updated, {not_found} not found — saved ✓')

# Final save
with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(movies, f, ensure_ascii=False, indent=2)

has_streaming = sum(1 for m in movies if m.get('streaming'))
print(f'\n✅ Done! [{now_str}]')
print(f'   Updated:  {updated:,}')
print(f'   Skipped:  {fresh:,} (fresh)')
print(f'   No data:  {not_found:,}')
print(f'   Total with streaming: {has_streaming:,}')
print(f'   Saved to: {OUTPUT_JSON}')
