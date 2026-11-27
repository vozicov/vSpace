from django.apps import AppConfig
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models.signals import post_migrate, pre_migrate

# migrations of these apps can rebuild the tables the search triggers are attached to
WATCHED_APPS = {'feed', 'accounts', 'auth', 'search'}


def _before_migrate(sender=None, using=DEFAULT_DB_ALIAS, plan=None, **kwargs):
    """Take the triggers down while migrations that may rebuild their tables are about to run."""
    from . import index
    if connections[using].vendor == 'sqlite' and any(m.app_label in WATCHED_APPS for m, _ in (plan or [])):
        index.drop_triggers(connections[using])


def _after_migrate(sender=None, using=DEFAULT_DB_ALIAS, **kwargs):
    """Put them back (and refill the index if they had been down). Cheap when nothing changed."""
    from . import index
    index.ensure(connections[using])


class SearchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'search'

    def ready(self):
        pre_migrate.connect(_before_migrate, dispatch_uid='search.before_migrate')
        post_migrate.connect(_after_migrate, dispatch_uid='search.after_migrate')
