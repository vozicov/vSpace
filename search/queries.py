"""The search itself.

Fast path: SQLite FTS5 (a real full-text index, see migrations/0001_initial.py). A search looks
words up in the index instead of scanning every row, matches the beginnings of words ("voz" finds
"vozi"), ranks by relevance (bm25: a hit in a post title or a username counts more than one in a
body or bio), and only then loads the few rows that won.

Slow path: if the index is missing (SQLite without FTS5) the same results come from plain
`icontains` filters, so search never breaks, it is just slower on big tables.
"""
import re

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.db.models import Q
from django.utils.html import escape
from django.utils.safestring import mark_safe

from accounts.models import Profile
from feed.models import Entry

MIN_CHARS = 2          # shorter than this matches half the database
MAX_WORDS = 6
WORD = re.compile(r'\w+', re.UNICODE)

_indexed = False


def words(q):
    """The searchable words in what was typed. Only letters and digits survive, so nothing a
    person types can be read as search-syntax (quotes, NEAR, OR, *, -, :)."""
    found = [w for w in WORD.findall(q or '') if any(c.isalnum() for c in w)]
    return found[:MAX_WORDS]


def too_short(q):
    return sum(len(w) for w in words(q)) < MIN_CHARS


def indexed():
    """True when the FTS tables exist (checked once, then remembered)."""
    global _indexed
    if not _indexed and connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM sqlite_master WHERE name IN ('feed_entry_fts', 'accounts_profile_fts')")
            _indexed = cursor.fetchone()[0] == 2
    return _indexed


def match_expression(ws):
    # every word must appear (AND); the last one may be unfinished, and so may the others
    return ' '.join(f'"{w}"*' for w in ws)


def highlight(text, ws, width=None):
    """HTML-safe text with the typed words wrapped in <mark>, shortened around the first hit."""
    text = ' '.join((text or '').split())
    pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(w) for w in ws) + ')', re.I | re.U) if ws else None
    if width and len(text) > width:
        hit = pattern.search(text) if pattern else None
        start = max(0, hit.start() - width // 3) if hit else 0
        end = start + width
        text = ('…' if start else '') + text[start:end].strip() + ('…' if end < len(text) else '')
    if not pattern:
        return escape(text)
    out, last = [], 0
    for m in pattern.finditer(text):
        out.append(escape(text[last:m.start()]))
        out.append('<mark>' + escape(m.group()) + '</mark>')
        last = m.end()
    out.append(escape(text[last:]))
    return mark_safe(''.join(out))


def _ids(sql, params):
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [row[0] for row in cursor.fetchall()]
    except OperationalError:       # a syntax problem in the index query: show nothing, never a 500
        return []


def _in_order(queryset, ids):
    found = {obj.pk: obj for obj in queryset.filter(pk__in=ids)}
    return [found[i] for i in ids if i in found]


def find_profiles(ws, limit):
    base = Profile.objects.select_related('user')
    if indexed():
        ids = _ids(
            'SELECT rowid FROM accounts_profile_fts WHERE accounts_profile_fts MATCH %s '
            'ORDER BY bm25(accounts_profile_fts, 10.0, 5.0, 1.0), rowid LIMIT %s',
            [match_expression(ws), limit])
        rows = _in_order(base, ids)
    else:
        cond = Q()
        for w in ws:
            cond &= Q(user__username__icontains=w) | Q(display_name__icontains=w) | Q(bio__icontains=w)
        rows = list(base.filter(cond).order_by('-id')[:limit])
    for p in rows:
        p.username_html = highlight(p.user.username, ws)
        p.name_html = highlight(p.name, ws)
        p.bio_html = highlight(p.bio, ws, 90) if p.bio else ''
    return rows


def find_entries(ws, kind, limit):
    base = Entry.objects.select_related('author__profile')
    if indexed():
        ids = _ids(
            'SELECT e.id FROM feed_entry_fts JOIN feed_entry e ON e.id = feed_entry_fts.rowid '
            'WHERE feed_entry_fts MATCH %s AND e.kind = %s '
            'ORDER BY bm25(feed_entry_fts, 6.0, 1.0), e.id DESC LIMIT %s',
            [match_expression(ws), kind, limit])
        rows = _in_order(base, ids)
    else:
        cond = Q(kind=kind)
        for w in ws:
            cond &= Q(title__icontains=w) | Q(body__icontains=w)
        rows = list(base.filter(cond).order_by('-id')[:limit])
    for e in rows:
        e.title_html = highlight(e.title, ws)
        e.snippet_html = highlight(e.body, ws, 130)
    return rows


TYPES = ('all', 'profiles', 'posts', 'tweets')


def run(q, kind='all'):
    """{'profiles': [...], 'posts': [...], 'tweets': [...]} for what was typed.
    'all' gives a few of each (the drawer); one type gives a longer list of just that."""
    out = {'profiles': [], 'posts': [], 'tweets': []}
    ws = words(q)
    if too_short(q):
        return out
    few, many = 4, 20
    if kind in ('all', 'profiles'):
        out['profiles'] = find_profiles(ws, few if kind == 'all' else many)
    if kind in ('all', 'posts'):
        out['posts'] = find_entries(ws, Entry.Kind.POST, few if kind == 'all' else many)
    if kind in ('all', 'tweets'):
        out['tweets'] = find_entries(ws, Entry.Kind.TWEET, few if kind == 'all' else many)
    return out
