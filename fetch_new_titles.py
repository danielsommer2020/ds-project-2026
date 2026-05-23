#!/usr/bin/env python3
"""
MovieMatch — Weekly New Titles Fetcher
---------------------------------------
Fetches 40 new movies + 40 new TV shows from TMDB each week.
Sources: Now Playing, Popular, Top Rated — newest first.
Filters: 7.0+ rating, English/Spanish/French/Korean/Japanese only.
Deduplication: skips any title already in the database (by title + year).
Also fetches streaming data for every new title in the same pass.

Runtime: ~3-4 minutes total
Run:     python3 fetch_new_titles.py
Outputs: movie_database_streaming.json (updated)
         tvshows.json (updated)
Then:    python3 rebuild_app.py movie_database_streaming.json
         python3 rebuild_tv.py
"""

import asyncio, aiohttp, json, time, sys, os
from pathlib import Path
from datetime import datetime, timezone

API_KEY    = os.environ.get('TMDB_API_KEY', '12fcc24f6de2c9f3ddeec1aad8ba2146')
BASE       = 'https://api.themoviedb.org/3'
REGIONS    = ['AU','US','GB','NZ','CA']
LANGUAGES  = {'en','es','fr','ko','ja'}   # English, Spanish, French, Korean, Japanese
MIN_RATING = 7.0
NEW_MOVIES = 40
NEW_SHOWS  = 40
CONCURRENT = 10

MOVIE_DB   = 'movie_database_streaming.json' \
             if Path('movie_database_streaming.json').exists() \
             else 'movie_database_full.json'
TV_DB      = 'tvshows.json'

GENRE_MAP = {
    28:'Action', 12:'Adventure', 16:'Animation', 35:'Comedy',
    80:'Thriller', 99:'Documentary', 18:'Drama', 10751:'Family',
    14:'Fantasy', 36:'History', 27:'Horror', 10402:'Comedy',
    9648:'Thriller', 10749:'Romance', 878:'Sci-Fi', 10770:'Drama',
    53:'Thriller', 10752:'Action', 37:'Action'
}
TV_GENRE_MAP = {
    10759:'Action', 16:'Animation', 35:'Comedy', 80:'Thriller',
    99:'Documentary', 18:'Drama', 10751:'Family', 10762:'Family',
    9648:'Thriller', 10763:'Documentary', 10764:'Reality',
    10765:'Sci-Fi', 10766:'Drama', 10767:'Comedy', 10768:'Drama',
    37:'Action'
}

# ── Helpers ────────────────────────────────────────────────────────────────
async def fetch(session, path, params=None, retries=4):
    p = {'api_key': API_KEY, 'language': 'en-US'}
    if params: p.update(params)
    for attempt in range(retries):
        try:
            async with session.get(f'{BASE}{path}', params=p,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 429:
                    wait = int(r.headers.get('Retry-After', 10))
                    await asyncio.sleep(wait); continue
                if r.ok: return await r.json()
        except asyncio.TimeoutError:
            await asyncio.sleep(2*(attempt+1))
        except Exception:
            await asyncio.sleep(1)
    return {}

def map_genre(genre_ids, genre_map):
    PRIORITY = ['Sci-Fi','Action','Thriller','Drama','Animation',
                'Documentary','Family','Reality','Romance','Comedy','Adventure','Horror']
    mapped = [genre_map.get(gid) for gid in genre_ids if genre_map.get(gid)]
    for p in PRIORITY:
        if p in mapped: return p
    return mapped[0] if mapped else 'Drama'

def make_duplicate_set(movies_list, is_dict=True):
    """Build a set of (title_lower, year) for fast duplicate checking."""
    dupes = set()
    for m in movies_list:
        if is_dict:
            title = (m.get('title') or '').lower().strip()
            year  = str(m.get('year',''))
        else:
            title = (m[0] or '').lower().strip()
            year  = str(m[1] or '')
        if title: dupes.add((title, year))
    return dupes

# ── Streaming fetch ────────────────────────────────────────────────────────
async def get_streaming(session, tmdb_id, media_type, semaphore):
    async with semaphore:
        endpoint = '/movie/' if media_type == 'movie' else '/tv/'
        data = await fetch(session, f'{endpoint}{tmdb_id}/watch/providers')
        res  = data.get('results', {})
        streaming = {}
        for region in REGIONS:
            flatrate = res.get(region, {}).get('flatrate', [])
            if flatrate:
                streaming[region] = [p['provider_id'] for p in flatrate]
        return streaming

# ── Movie fetcher ──────────────────────────────────────────────────────────
async def fetch_new_movies(session, existing_dupes, semaphore):
    endpoints = [
        ('/movie/now_playing',  {'region': 'AU'}),
        ('/movie/popular',      {'region': 'AU'}),
        ('/movie/top_rated',    {'region': 'AU'}),
    ]

    candidates = {}  # tmdb_id → movie data

    for endpoint, extra_params in endpoints:
        for page in range(1, 4):  # 3 pages × 20 = 60 per source
            params = {'page': page, **extra_params}
            data   = await fetch(session, endpoint, params)
            for m in data.get('results', []):
                tid   = m.get('id')
                lang  = m.get('original_language','')
                rating= m.get('vote_average', 0)
                votes = m.get('vote_count', 0)
                if not tid: continue
                if lang not in LANGUAGES: continue
                if rating < MIN_RATING: continue
                if votes < 50: continue
                if tid not in candidates:
                    candidates[tid] = m

    # Sort newest first
    sorted_candidates = sorted(
        candidates.values(),
        key=lambda m: m.get('release_date','') or '',
        reverse=True
    )

    new_movies = []
    for m in sorted_candidates:
        if len(new_movies) >= NEW_MOVIES: break

        title = (m.get('title') or '').strip()
        date  = m.get('release_date','') or ''
        year  = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else 0
        if not title or not year: continue

        # Duplicate check
        if (title.lower(), str(year)) in existing_dupes: continue

        # Fetch full details for poster, runtime, genres, trailer
        details = await fetch(session, f'/movie/{m["id"]}',
                              {'append_to_response': 'credits,videos'})
        await asyncio.sleep(0.05)

        genre_ids = [g['id'] for g in m.get('genre_ids',[]) or []]
        genre     = map_genre(genre_ids, GENRE_MAP)
        poster    = f"https://image.tmdb.org/t/p/w500{m['poster_path']}" \
                    if m.get('poster_path') else ''
        runtime   = details.get('runtime') or 0
        plot      = (m.get('overview') or '').strip()[:220]
        director  = ''
        cast_list = []
        if 'credits' in details:
            for c in details['credits'].get('crew',[]):
                if c.get('job') == 'Director':
                    director = c.get('name',''); break
            cast_list = [c['name'] for c in details['credits'].get('cast',[])[:5]]
        trailer = ''
        for v in (details.get('videos',{}).get('results') or []):
            if v.get('type')=='Trailer' and v.get('site')=='YouTube':
                trailer = v.get('key',''); break

        streaming = await get_streaming(session, m['id'], 'movie', semaphore)

        movie_entry = {
            'title':   title,
            'year':    year,
            'genre':   genre,
            'rating':  round(float(m.get('vote_average',0)), 1),
            'director': director,
            'cast':    ', '.join(cast_list),
            'plot':    plot,
            'poster':  poster,
            'runtime': runtime,
            'trailer': trailer,
            'streaming': streaming,
            'streaming_updated': time.time(),
        }
        new_movies.append(movie_entry)
        existing_dupes.add((title.lower(), str(year)))  # prevent within-batch dupes

    return new_movies

# ── TV Show fetcher ────────────────────────────────────────────────────────
async def fetch_new_shows(session, existing_dupes, semaphore):
    endpoints = [
        ('/tv/on_the_air',  {}),
        ('/tv/popular',     {}),
        ('/tv/top_rated',   {}),
    ]

    candidates = {}
    for endpoint, extra_params in endpoints:
        for page in range(1, 4):
            params = {'page': page, **extra_params}
            data   = await fetch(session, endpoint, params)
            for s in data.get('results', []):
                tid   = s.get('id')
                lang  = s.get('original_language','')
                rating= s.get('vote_average', 0)
                votes = s.get('vote_count', 0)
                if not tid: continue
                if lang not in LANGUAGES: continue
                if rating < MIN_RATING: continue
                if votes < 50: continue
                if tid not in candidates:
                    candidates[tid] = s

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda s: s.get('first_air_date','') or '',
        reverse=True
    )

    new_shows = []
    for s in sorted_candidates:
        if len(new_shows) >= NEW_SHOWS: break

        title = (s.get('name') or '').strip()
        date  = s.get('first_air_date','') or ''
        year  = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else 0
        if not title or not year: continue

        if (title.lower(), str(year)) in existing_dupes: continue

        # Fetch full details
        details = await fetch(session, f'/tv/{s["id"]}',
                              {'append_to_response': 'credits,videos'})
        await asyncio.sleep(0.05)

        genre_ids = [g['id'] for g in s.get('genre_ids',[]) or []]
        genre     = map_genre(genre_ids, TV_GENRE_MAP)
        poster    = f"https://image.tmdb.org/t/p/w500{s['poster_path']}" \
                    if s.get('poster_path') else ''
        plot      = (s.get('overview') or '').strip()[:220]
        seasons   = details.get('number_of_seasons') or 0
        status    = details.get('status') or ''
        cast_list = []
        if 'credits' in details:
            cast_list = [c['name'] for c in details['credits'].get('cast',[])[:5]]
        trailer = ''
        for v in (details.get('videos',{}).get('results') or []):
            if v.get('type')=='Trailer' and v.get('site')=='YouTube':
                trailer = v.get('key',''); break

        # Episode runtime
        runtimes = details.get('episode_run_time') or []
        runtime  = runtimes[0] if runtimes else 0

        streaming = await get_streaming(session, s['id'], 'tv', semaphore)

        # TV array format: [title, year, genre, rating, creator, cast, plot,
        #                   poster, runtime, trailer, streaming, seasons, status]
        show_entry = [
            title, year, genre,
            round(float(s.get('vote_average',0)), 1),
            '',          # creator (not fetched — TMDB doesn't return reliably)
            ', '.join(cast_list),
            plot, poster, runtime, trailer,
            streaming, seasons, status
        ]
        new_shows.append(show_entry)
        existing_dupes.add((title.lower(), str(year)))

    return new_shows

# ── Main ───────────────────────────────────────────────────────────────────
async def main():
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    start   = time.time()
    print(f'MovieMatch — Weekly New Titles Fetch [{now_str}]\n')

    # Load existing databases
    if not Path(MOVIE_DB).exists():
        print(f'ERROR: {MOVIE_DB} not found.'); sys.exit(1)
    if not Path(TV_DB).exists():
        print(f'ERROR: {TV_DB} not found.'); sys.exit(1)

    with open(MOVIE_DB, 'r', encoding='utf-8') as f: movies = json.load(f)
    with open(TV_DB,    'r', encoding='utf-8') as f: shows  = json.load(f)

    print(f'Existing: {len(movies):,} movies, {len(shows):,} TV shows')

    # Build duplicate sets
    movie_dupes = make_duplicate_set(movies, is_dict=True)
    show_dupes  = make_duplicate_set(shows,  is_dict=False)

    print(f'Duplicate check ready: {len(movie_dupes):,} movie keys, '
          f'{len(show_dupes):,} show keys\n')

    semaphore = asyncio.Semaphore(CONCURRENT)
    connector = aiohttp.TCPConnector(limit=CONCURRENT*2)

    async with aiohttp.ClientSession(connector=connector) as session:
        print('Fetching new movies...')
        new_movies = await fetch_new_movies(session, movie_dupes, semaphore)
        print(f'  Found {len(new_movies)} new movies\n')

        print('Fetching new TV shows...')
        new_shows = await fetch_new_shows(session, show_dupes, semaphore)
        print(f'  Found {len(new_shows)} new TV shows\n')

    # Append to databases
    movies.extend(new_movies)
    shows.extend(new_shows)

    # Save movie database
    with open(MOVIE_DB, 'w', encoding='utf-8') as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)

    # Save TV database (strip to 13 fields)
    clean_shows = [s[:13] for s in shows]
    with open(TV_DB, 'w', encoding='utf-8') as f:
        json.dump(clean_shows, f, ensure_ascii=False, separators=(',',':'))

    elapsed = (time.time() - start) / 60
    print(f'✅ Done! [{now_str}]')
    print(f'   Time:        {elapsed:.1f} minutes')
    print(f'   New movies:  {len(new_movies)} added → total {len(movies):,}')
    print(f'   New shows:   {len(new_shows)} added → total {len(shows):,}')
    print(f'   Duplicates:  0 (all checked)')
    print(f'\nNext:')
    print(f'   python3 rebuild_app.py {MOVIE_DB}')
    print(f'   python3 rebuild_tv.py')

if __name__ == '__main__':
    asyncio.run(main())
