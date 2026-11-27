"""Creates the two (empty) full-text index tables. See search/index.py.

The triggers that keep them current, and the first filling of the index with your existing posts,
tweets and people, happen right after `migrate` finishes (search/apps.py). If your SQLite has no
FTS5 this quietly does nothing and the search falls back to a slower plain search.
"""
from django.conf import settings
from django.db import migrations

from search import index


def build(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'sqlite':
        return
    try:
        index.create_tables(connection)
    except Exception as error:   # "no such module: fts5" and friends
        print(f'\n  search: could not build the FTS5 index ({error}). Using the slower fallback search.')


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        index.drop_all(schema_editor.connection)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('feed', '0001_initial'),       # these two create the tables and columns that are indexed
        ('accounts', '0001_initial'),
    ]
    operations = [migrations.RunPython(build, remove)]
