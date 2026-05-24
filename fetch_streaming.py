#!/usr/bin/env python3
"""
MovieMatch — Fast Incremental Streaming + Ratings Fetcher (Movies)
------------------------------------------------------------------
Fetches streaming availability AND age ratings (AU/US/GB) per movie.
Uses async/parallel requests — 10x faster than sequential.

First run:  ~5-8 minutes
Re-runs:    ~1-2 minutes (skips fresh data)

Usage:
    python3 fetch_streaming.py
"""

import asyncio, aiohttp, json, time, sys, os
from pathlib import Path
from datetime import datetime, timezone

API_KEY    = os.environ.get('TMDB_API_KEY', '12fcc24f6de2c9f3ddeec1aad8ba2146')
BASE       = 'https://api.themoviedb.org/3'
REGIONS    = ['AU','US','GB','NZ','CA']
RATING_REGIONS = ['AU','US','GB']
STALE_DAYS = 6
CONCURRENT = 10
SAVE_EVERY = 200

INPUT_JSON  = 'movie_database_streaming.json' \
              if Path('movie_database_streaming.json').exists() \
              else 'movie_database_full.json' \
              if Path('movie_database_full.json').exists() \
              else 'movie_database.json'
OUTPUT_JSON = 'movie_database_streaming.json'

def is_stale(movie):
    if 'streaming' not in movie: return True
    updated = movie.get('streaming_updated', 0)
    if not updated: return True
    return (time.time() - updated) / 86400 >= STALE_DAYS

async def fetch(session, url, params, retries=4):
    p = {'api_key': API_KEY, 'language': 'en-US'}
    if params: p.update(params)
    for attempt in range(retries):
        try:
            async with session.get(url, params=p,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 429:
                    wait = int(r.headers.get('Retry-After', 10))
                    await asyncio.sleep(wait); continue
                if r.ok: return await r.json()
        except asyncio.TimeoutError:
            await asyncio.sleep(2 * (attempt + 1))
        except Exception:
            await asyncio.sleep(1)
    return {}

async def process_movie(session, movie, semaphore):
    async with semaphore:
        title = movie.get('title', '')
        year  = movie.get('year', 0)

        # Search for TMDB ID
        data = await fetch(session, f'{BASE}/search/movie',
                           {'query': title, 'year': year})
        results = data.get('results', [])
        if not results:
            data = await fetch(session, f'{BASE}/search/movie', {'query': title})
            results = data.get('results', [])

        if not results:
            movie['streaming']         = {}
            movie['ratings']           = {}
            movie['streaming_updated'] = time.time()
            return False

        tmdb_id = results[0]['id']

        # Fetch streaming + release_dates (ratings) in parallel
        stream_task = fetch(session, f'{BASE}/movie/{tmdb_id}/watch/providers', {})
        ratings_task = fetch(session, f'{BASE}/movie/{tmdb_id}/release_dates', {})
        stream_data, ratings_data = await asyncio.gather(stream_task, ratings_task)

        # Streaming
        res = stream_data.get('results', {})
        streaming = {}
        for region in REGIONS:
            flatrate = res.get(region, {}).get('flatrate', [])
            if flatrate:
                streaming[region] = [p['provider_id'] for p in flatrate]

        # Ratings — pick the certification for each region
        ratings = {}
        for entry in ratings_data.get('results', []):
            country = entry.get('iso_3166_1','')
            if country not in RATING_REGIONS: continue
            certs = entry.get('release_dates', [])
            # Find the first non-empty certification
            for c in certs:
                cert = c.get('certification','').strip()
                if cert:
                    ratings[country] = cert
                    break

        movie['streaming']         = streaming
        movie['ratings']           = ratings
        movie['streaming_updated'] = time.time()
        return True

async def main():
    if not Path(INPUT_JSON).exists():
        print(f'ERROR: {INPUT_JSON} not found.'); sys.exit(1)

    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        movies = json.load(f)

    stale   = [m for m in movies if is_stale(m)]
    fresh   = len(movies) - len(stale)
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    print(f'Database:   {len(movies):,} movies')
    print(f'Up to date: {fresh:,} (skipping)')
    print(f'To update:  {len(stale):,}')
    est = max(1, len(stale) * 2 // (CONCURRENT * 60))
    print(f'Est. time:  ~{est} minutes\n')

    if not stale:
        print('✅ All streaming data is fresh.')
        sys.exit(0)

    semaphore = asyncio.Semaphore(CONCURRENT)
    updated = 0; not_found = 0; done = 0
    start = time.time()

    connector = aiohttp.TCPConnector(limit=CONCURRENT*2)
    async with aiohttp.ClientSession(connector=connector) as session:
        for i in range(0, len(stale), SAVE_EVERY):
            batch = stale[i:i+SAVE_EVERY]
            results = await asyncio.gather(*[process_movie(session, m, semaphore) for m in batch])
            for found in results:
                done += 1
                if found: updated += 1
                else: not_found += 1
            with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
                json.dump(movies, f, ensure_ascii=False, indent=2)
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(stale) - done) / rate / 60 if rate > 0 else 0
            print(f'  {done:,}/{len(stale):,} ({done/len(stale)*100:.0f}%) — '
                  f'{updated:,} updated — {remaining:.1f} min remaining — saved ✓')

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)

    has_ratings = sum(1 for m in movies if m.get('ratings'))
    print(f'\n✅ Done! [{now_str}]')
    print(f'   Time:        {(time.time()-start)/60:.1f} minutes')
    print(f'   Updated:     {updated:,}')
    print(f'   Has ratings: {has_ratings:,}/{len(movies):,}')
    print(f'   Saved to:    {OUTPUT_JSON}')
    print(f'\nNext: python3 rebuild_app.py {OUTPUT_JSON}')

if __name__ == '__main__':
    asyncio.run(main())
