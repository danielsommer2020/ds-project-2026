#!/usr/bin/env python3
"""
MovieMatch — Database Deduplication Cleanup
--------------------------------------------
Removes duplicate entries from movie_database_streaming.json and tvshows.json.
Keeps the most complete entry when duplicates are found (most non-empty fields).
Dedup key: (title.lower().strip(), str(year))

Run once to clean existing duplicates:
    python3 dedupe_database.py

Then rebuild:
    python3 rebuild_app.py movie_database_streaming.json
    python3 rebuild_tv.py
"""

import json
from pathlib import Path

MOVIE_DB = 'movie_database_streaming.json'
TV_DB    = 'tvshows.json'

def completeness(entry, is_dict):
    """Score an entry by how many fields are non-empty. Higher = more complete."""
    if is_dict:
        return sum(1 for v in entry.values() if v not in (None, '', 0, {}, []))
    else:
        return sum(1 for v in entry if v not in (None, '', 0, {}, []))

def dedupe_movies(movies):
    """Deduplicate movie dicts. Key = (title_lower, year). Keep most complete."""
    seen   = {}  # key → index in output list
    output = []
    removed = 0

    for m in movies:
        title = (m.get('title') or '').lower().strip()
        year  = str(m.get('year') or '')
        if not title:
            output.append(m)
            continue

        key = (title, year)
        if key not in seen:
            seen[key] = len(output)
            output.append(m)
        else:
            # Duplicate found — keep the more complete entry
            existing_idx   = seen[key]
            existing_score = completeness(output[existing_idx], is_dict=True)
            new_score      = completeness(m, is_dict=True)
            if new_score > existing_score:
                output[existing_idx] = m  # replace with better entry
            removed += 1
            print(f"  Duplicate removed: '{m.get('title')}' ({year}) "
                  f"[kept {'new' if new_score > existing_score else 'existing'}]")

    return output, removed

def dedupe_shows(shows):
    """Deduplicate TV show arrays. Key = (title_lower, year). Keep most complete."""
    seen   = {}
    output = []
    removed = 0

    for s in shows:
        title = (s[0] or '').lower().strip() if s else ''
        year  = str(s[1] or '') if len(s) > 1 else ''
        if not title:
            output.append(s)
            continue

        key = (title, year)
        if key not in seen:
            seen[key] = len(output)
            output.append(s)
        else:
            existing_idx   = seen[key]
            existing_score = completeness(output[existing_idx], is_dict=False)
            new_score      = completeness(s, is_dict=False)
            if new_score > existing_score:
                output[existing_idx] = s
            removed += 1
            print(f"  Duplicate removed: '{s[0]}' ({year}) "
                  f"[kept {'new' if new_score > existing_score else 'existing'}]")

    return output, removed

def main():
    print('MovieMatch — Database Deduplication\n')

    # ── Movies ──────────────────────────────────────────────────────────────
    if not Path(MOVIE_DB).exists():
        print(f'ERROR: {MOVIE_DB} not found'); return

    with open(MOVIE_DB, 'r', encoding='utf-8') as f:
        movies = json.load(f)

    print(f'Movies before: {len(movies):,}')
    clean_movies, removed_m = dedupe_movies(movies)
    print(f'Movies after:  {len(clean_movies):,} ({removed_m} duplicates removed)\n')

    with open(MOVIE_DB, 'w', encoding='utf-8') as f:
        json.dump(clean_movies, f, ensure_ascii=False, indent=2)

    # ── TV Shows ─────────────────────────────────────────────────────────────
    if not Path(TV_DB).exists():
        print(f'ERROR: {TV_DB} not found'); return

    with open(TV_DB, 'r', encoding='utf-8') as f:
        shows = json.load(f)

    print(f'TV shows before: {len(shows):,}')
    clean_shows, removed_tv = dedupe_shows(shows)
    print(f'TV shows after:  {len(clean_shows):,} ({removed_tv} duplicates removed)\n')

    with open(TV_DB, 'w', encoding='utf-8') as f:
        json.dump(clean_shows, f, ensure_ascii=False, separators=(',',':'))

    print(f'✅ Done — {removed_m + removed_tv} total duplicates removed')
    if removed_m + removed_tv > 0:
        print('\nNext steps:')
        print('  python3 rebuild_app.py movie_database_streaming.json')
        print('  python3 rebuild_tv.py')

if __name__ == '__main__':
    main()
