"""Puts the post/tweet search triggers back after feed.0004 (music columns).

SQLite cannot add a column in place, so Django rebuilds the whole feed_entry table, and dropping
the old table also drops the triggers that keep the search index up to date. Without this, posts
made after that migration would never show up in search. Safe to run twice (IF NOT EXISTS).
If the FTS5 index was never built (no FTS5 in this SQLite) it does nothing.
"""
from django.db import migrations

STATEMENTS = [
    """CREATE TRIGGER IF NOT EXISTS feed_entry_fts_ai AFTER INSERT ON feed_entry BEGIN
           INSERT INTO feed_entry_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
       END""",
    """CREATE TRIGGER IF NOT EXISTS feed_entry_fts_ad AFTER DELETE ON feed_entry BEGIN
           INSERT INTO feed_entry_fts(feed_entry_fts, rowid, title, body)
           VALUES ('delete', old.id, old.title, old.body);
       END""",
    """CREATE TRIGGER IF NOT EXISTS feed_entry_fts_au AFTER UPDATE OF title, body ON feed_entry BEGIN
           INSERT INTO feed_entry_fts(feed_entry_fts, rowid, title, body)
           VALUES ('delete', old.id, old.title, old.body);
           INSERT INTO feed_entry_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
       END""",
    # re-read every post, in case any were saved while the triggers were missing
    "INSERT INTO feed_entry_fts(feed_entry_fts) VALUES('rebuild')",
]


def restore(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feed_entry_fts'")
        if not cursor.fetchone():
            return
        for sql in STATEMENTS:
            cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [
        ('search', '0001_initial'),
        ('feed', '0004_entry_music'),
    ]
    operations = [migrations.RunPython(restore, migrations.RunPython.noop)]
