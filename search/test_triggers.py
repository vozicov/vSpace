from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from feed.models import Entry


class EntrySearchTriggerTests(TestCase):
    """Guards against a feed migration rebuilding feed_entry and dropping the search triggers."""

    def test_triggers_exist_after_all_migrations(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM sqlite_master WHERE name='feed_entry_fts'")
            if not cursor.fetchone():
                self.skipTest('this SQLite has no FTS5')
            cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='feed_entry'")
            names = {row[0] for row in cursor.fetchall()}
        self.assertEqual(names, {'feed_entry_fts_ai', 'feed_entry_fts_ad', 'feed_entry_fts_au'})

    def test_new_post_is_indexed(self):
        user = get_user_model().objects.create_user('ann', password='pw')
        Entry.objects.create(author=user, kind='post', title='Zebrafish', body='stripes')
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM sqlite_master WHERE name='feed_entry_fts'")
            if not cursor.fetchone():
                self.skipTest('this SQLite has no FTS5')
            cursor.execute("SELECT rowid FROM feed_entry_fts WHERE feed_entry_fts MATCH 'zebrafish'")
            self.assertEqual(len(cursor.fetchall()), 1)
