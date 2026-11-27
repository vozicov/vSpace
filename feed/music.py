"""Music search for posts, using Apple's free iTunes Search API (no key, no login, no user limit).

Members search a song by name. The browser asks OUR server (music_search below), which asks Apple,
so the browser never talks to Apple directly and the answers can be cached. When a post is
published, the form only receives the song's id and asks Apple again (lookup), so nobody can
save made-up titles or links.
"""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

API_URL = 'https://itunes.apple.com'
TIMEOUT = 6                    # seconds
SEARCH_LIMIT = 8               # songs shown under the search box
MIN_QUERY = 2
MAX_QUERY = 100
SEARCHES_PER_MINUTE = 30       # per member. Apple itself allows about 20 a minute per server.
SEARCH_CACHE_SECONDS = 600
LOOKUP_CACHE_SECONDS = 3600
STORE = 'US'                   # the Apple store searched (the US one has the most songs)

# Links and pictures saved on a post must come from Apple, over https
ALLOWED_HOSTS = ('apple.com', 'mzstatic.com')
ID_RE = re.compile(r'^\d{1,15}\Z')


class MusicError(Exception):
    """Apple could not be reached or said no. The message is safe to show to members."""


def _fetch(path, params):
    url = f'{API_URL}{path}?{urllib.parse.urlencode(params)}'
    request = urllib.request.Request(url, headers={'User-Agent': 'space-app/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise MusicError('Music search is busy. Try again in a moment.')
        raise MusicError('Music search is not available right now.')
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise MusicError('Music search is not available right now.')


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return ''
    parts = urllib.parse.urlparse(value)
    host = (parts.hostname or '').lower()
    ok = parts.scheme == 'https' and any(host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS)
    return value if ok else ''


def _normalize(item, art_size):
    """One song from Apple's answer, cut down to what we keep. None if it is not a usable song."""
    if not isinstance(item, dict) or item.get('kind') != 'song':
        return None
    track_id = str(item.get('trackId', ''))
    title = str(item.get('trackName') or '').strip()
    artist = str(item.get('artistName') or '').strip()
    if not ID_RE.match(track_id) or not title or not artist:
        return None
    art = str(item.get('artworkUrl100') or '')
    art = _safe_url(art.replace('100x100bb', f'{art_size}x{art_size}bb'))
    return {
        'id': track_id,
        'title': title[:200],
        'artist': artist[:200],
        'album': str(item.get('collectionName') or '')[:200],
        'art': art,
        'preview': _safe_url(item.get('previewUrl')),     # a 30 second clip
        'url': _safe_url(item.get('trackViewUrl')),       # the song on Apple Music
    }


def search(term):
    term = ' '.join(term.split())[:MAX_QUERY]
    key = 'itunes-search:' + hashlib.sha1(term.lower().encode('utf-8')).hexdigest()
    found = cache.get(key)
    if found is not None:
        return found
    data = _fetch('/search', {
        'term': term, 'media': 'music', 'entity': 'song',
        'limit': SEARCH_LIMIT, 'country': STORE,
    })
    results = [s for s in (_normalize(i, 100) for i in data.get('results') or []) if s]
    cache.set(key, results, SEARCH_CACHE_SECONDS)
    return results


def lookup(track_id):
    """The song with this id, or None if there is no such song. Raises MusicError if Apple is down."""
    track_id = str(track_id or '').strip()
    if not ID_RE.match(track_id):
        return None
    key = 'itunes-song:' + track_id
    found = cache.get(key)
    if found is not None:
        return found or None
    data = _fetch('/lookup', {'id': track_id, 'country': STORE})
    song = None
    for item in data.get('results') or []:
        song = _normalize(item, 300)
        if song:
            break
    cache.set(key, song or {}, LOOKUP_CACHE_SECONDS)
    return song


def _throttled(user_id):
    key = f'itunes-rate:{user_id}'
    cache.add(key, 0, 60)
    try:
        count = cache.incr(key)
    except ValueError:        # the counter expired between the two calls
        cache.set(key, 1, 60)
        count = 1
    return count > SEARCHES_PER_MINUTE


@login_required
@require_GET
def music_search(request):
    term = ' '.join(request.GET.get('q', '').split())
    if len(term) < MIN_QUERY:
        return JsonResponse({'results': []})
    if _throttled(request.user.pk):
        return JsonResponse({'error': 'Slow down a little, then search again.'}, status=429)
    try:
        songs = search(term)
    except MusicError as exc:
        return JsonResponse({'error': str(exc)}, status=502)
    keep = ('id', 'title', 'artist', 'album', 'art', 'preview')
    return JsonResponse({'results': [{k: s[k] for k in keep} for s in songs]})
