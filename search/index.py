"""The search index (SQLite FTS5): its tables, and the triggers that keep it up to date.

  feed_entry_fts        posts + tweets (title, body). It stores no text of its own: it points at
                        feed_entry ("external content"), so it adds little disk space.
  accounts_profile_fts  people (username, display name, bio).

TRIGGERS are created after every `migrate` and taken down before one (see apps.py). SQLite rebuilds
a table (copy, drop, rename) for many schema changes, and it refuses to do that while a trigger
refers to the table. Handled here, no future migration has to know the search exists.
"""
from django.contrib.auth import get_user_model

TOKENIZER = "tokenize='unicode61 remove_diacritics 1', prefix='2 3'"
TABLES = ('feed_entry_fts', 'accounts_profile_fts')


def _user_table(connection):
    return connection.ops.quote_name(get_user_model()._meta.db_table)


def table_sql():
    return [
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS feed_entry_fts USING fts5(
                title, body, content='feed_entry', content_rowid='id', {TOKENIZER})""",
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS accounts_profile_fts USING fts5(
                username, display_name, bio, {TOKENIZER})""",
    ]


def trigger_sql(user_table):
    return {
        'feed_entry_fts_ai': """CREATE TRIGGER feed_entry_fts_ai AFTER INSERT ON feed_entry BEGIN
            INSERT INTO feed_entry_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
        END""",
        'feed_entry_fts_ad': """CREATE TRIGGER feed_entry_fts_ad AFTER DELETE ON feed_entry BEGIN
            INSERT INTO feed_entry_fts(feed_entry_fts, rowid, title, body)
            VALUES ('delete', old.id, old.title, old.body);
        END""",
        'feed_entry_fts_au': """CREATE TRIGGER feed_entry_fts_au AFTER UPDATE OF title, body ON feed_entry BEGIN
            INSERT INTO feed_entry_fts(feed_entry_fts, rowid, title, body)
            VALUES ('delete', old.id, old.title, old.body);
            INSERT INTO feed_entry_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
        END""",
        'accounts_profile_fts_ai': f"""CREATE TRIGGER accounts_profile_fts_ai AFTER INSERT ON accounts_profile BEGIN
            INSERT INTO accounts_profile_fts(rowid, username, display_name, bio)
            SELECT new.id, u.username, new.display_name, new.bio FROM {user_table} u WHERE u.id = new.user_id;
        END""",
        'accounts_profile_fts_au': """CREATE TRIGGER accounts_profile_fts_au AFTER UPDATE OF display_name, bio ON accounts_profile BEGIN
            UPDATE accounts_profile_fts SET display_name = new.display_name, bio = new.bio WHERE rowid = new.id;
        END""",
        'accounts_profile_fts_ad': """CREATE TRIGGER accounts_profile_fts_ad AFTER DELETE ON accounts_profile BEGIN
            DELETE FROM accounts_profile_fts WHERE rowid = old.id;
        END""",
        'accounts_user_fts_au': f"""CREATE TRIGGER accounts_user_fts_au AFTER UPDATE OF username ON {user_table} BEGIN
            UPDATE accounts_profile_fts SET username = new.username
            WHERE rowid = (SELECT id FROM accounts_profile WHERE user_id = new.id);
        END""",
    }


TRIGGER_NAMES = tuple(trigger_sql('x'))


def _names(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")
    return {row[0] for row in cursor.fetchall()}


def create_tables(connection):
    with connection.cursor() as cursor:
        for sql in table_sql():
            cursor.execute(sql)


def drop_triggers(connection):
    with connection.cursor() as cursor:
        for name in TRIGGER_NAMES:
            cursor.execute(f'DROP TRIGGER IF EXISTS {name}')


def drop_all(connection):
    drop_triggers(connection)
    with connection.cursor() as cursor:
        for name in TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS {name}')


def ensure(connection):
    """Make sure every trigger exists. If any had to be (re)made, the index may have missed
    changes, so it is refilled from the real tables. Does nothing when all is in place."""
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        names = _names(cursor)
        if not set(TABLES) <= names:      # no FTS5 on this SQLite: the slow fallback search is used
            return
        missing = {n: sql for n, sql in trigger_sql(_user_table(connection)).items() if n not in names}
        if not missing:
            return
        for sql in missing.values():
            cursor.execute(sql)
        cursor.execute("INSERT INTO feed_entry_fts(feed_entry_fts) VALUES ('rebuild')")
        cursor.execute('DELETE FROM accounts_profile_fts')
        cursor.execute(
            f"""INSERT INTO accounts_profile_fts(rowid, username, display_name, bio)
                SELECT p.id, u.username, p.display_name, p.bio
                FROM accounts_profile p JOIN {_user_table(connection)} u ON u.id = p.user_id""")
