#!/usr/bin/env python3
"""
MovieMatch — Fast Incremental Streaming Fetcher (TV Shows)
-----------------------------------------------------------
Uses async/parallel requests — 10x faster than sequential.

First run:  ~2-3 minutes  (was 15+ min)
Re-runs:    ~30 seconds   (skips fresh data)

Usage:
    python3 fetch_tv_streaming.py
"""

import asyncio, aiohttp, json, time, sys, os
from pathlib import Path
from datetime import datetime, timezone

API_KEY    = os.environ.get('TMDB_API_KEY', '12fcc24f6de2c9f3ddeec1aad8ba2146')
BASE       = 'https://api.themoviedb.org/3'
REGIONS    = ['AU','US','GB','NZ','CA']
STALE_DAYS = 6
CONCURRENT = 10
SAVE_EVERY = 200
INPUT_JSON = 'tvshows.json'

def is_stale(show):
    streaming = show[10] if len(show) > 10 else {}
    updated   = show[13] if len(show) > 13 else 0
    if not streaming and not updated: return True
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
                    print(f'  Rate limited — waiting {wait}s...')
                    await asyncio.sleep(wait)
                    continue
                if r.ok:
                    return await r.json()
        except asyncio.TimeoutError:
            await asyncio.sleep(2 * (attempt + 1))
        except Exception:
            await asyncio.sleep(1)
    return {}

async def process_show(session, show, semaphore):
    async with semaphore:
        # Ensure array is long enough
        while len(show) < 13: show.append(None)
        if len(show) == 13: show.append(0)   # streaming_updated at 13
        if len(show) == 14: show.append(None) # tmdb_id at 14

        title = show[0]
        year  = show[1]

        # Use cached TMDB ID if available
        tmdb_id = show[14] if len(show) > 14 else None

        if not tmdb_id:
            data = await fetch(session, f'{BASE}/search/tv',
                               {'query': title, 'first_air_date_year': year})
            results = data.get('results', [])
            if not results:
                data = await fetch(session, f'{BASE}/search/tv', {'query': title})
                results = data.get('results', [])
            if results:
                tmdb_id = results[0]['id']
                while len(show) < 15: show.append(None)
                show[14] = tmdb_id

        if not tmdb_id:
            show[10] = {}
            show[13] = time.time()
            return False

        data = await fetch(session, f'{BASE}/tv/{tmdb_id}/watch/providers', {})
        res  = data.get('results', {})

        streaming = {}
        for region in REGIONS:
            flatrate = res.get(region, {}).get('flatrate', [])
            if flatrate:
                streaming[region] = [p['provider_id'] for p in flatrate]

        show[10] = streaming
        show[13] = time.time()
        return True

async def main():
    if not Path(INPUT_JSON).exists():
        print(f'ERROR: {INPUT_JSON} not found.')
        sys.exit(1)

    with open(INPUT_JSON, 'r', encoding='utf-8') as f:
        shows = json.load(f)

    stale   = [s for s in shows if is_stale(s)]
    fresh   = len(shows) - len(stale)
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    print(f'TV Shows:   {len(shows):,}')
    print(f'Up to date: {fresh:,} (skipping)')
    print(f'To update:  {len(stale):,}')
    est = max(1, len(stale) * 2 // (CONCURRENT * 60))
    print(f'Est. time:  ~{est} minutes\n')

    if not stale:
        print('✅ All TV streaming data is fresh.')
        sys.exit(0)

    semaphore = asyncio.Semaphore(CONCURRENT)
    updated = 0
    not_found = 0
    done = 0
    start = time.time()

    connector = aiohttp.TCPConnector(limit=CONCURRENT*2)
    async with aiohttp.ClientSession(connector=connector) as session:
        batch_size = SAVE_EVERY
        for i in range(0, len(stale), batch_size):
            batch = stale[i:i+batch_size]
            tasks = [process_show(session, s, semaphore) for s in batch]
            results = await asyncio.gather(*tasks)

            for found in results:
                done += 1
                if found: updated += 1
                else:     not_found += 1

            # Strip internal fields (13=updated, 14=tmdb_id) before saving
            clean = [s[:13] for s in shows]
            with open(INPUT_JSON, 'w', encoding='utf-8') as f:
                json.dump(clean, f, ensure_ascii=False, separators=(',',':'))

            elapsed = time.time() - start
            pct = done / len(stale) * 100
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(stale) - done) / rate / 60 if rate > 0 else 0
            print(f'  {done:,}/{len(stale):,} ({pct:.0f}%) — '
                  f'{updated:,} updated, {not_found:,} not found — '
                  f'{remaining:.1f} min remaining — saved ✓')

    # Final save — strip internal fields
    clean = [s[:13] for s in shows]
    with open(INPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, separators=(',',':'))

    has_streaming = sum(1 for s in clean if s[10])
    elapsed_total = (time.time() - start) / 60
    print(f'\n✅ Done! [{now_str}]')
    print(f'   Time taken:    {elapsed_total:.1f} minutes')
    print(f'   Updated:       {updated:,}')
    print(f'   Not found:     {not_found:,}')
    print(f'   Has streaming: {has_streaming:,}/{len(shows):,}')
    print(f'   Saved to:      {INPUT_JSON}')
    print(f'\nNext: python3 rebuild_tv.py')

if __name__ == '__main__':
    asyncio.run(main())
