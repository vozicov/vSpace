from django.conf import settings
from django.db.models import Exists, Max, OuterRef, Prefetch, Q

from feed.models import HAS_PICTURE, Entry

from .models import PIN_SLOTS, InterestPin, ShelfItem

PICKER_LIMIT = 100   # most recent posts offered in the "pin a post" popup
ADD_LIMIT = 60       # most recent posts offered in "Add posts"


def shelf_for(user):
    """A user's top-level shelf items. Collections come with their posts loaded,
    so templates never run a query per item."""
    children = ShelfItem.objects.select_related('entry')
    return (
        ShelfItem.objects
        .filter(owner=user, parent__isnull=True)
        .select_related('entry')
        .prefetch_related(Prefetch('children', queryset=children))
    )


def with_entries(items, viewer):
    """Give every post item a `.card`: its entry with like/comment counts for `viewer`
    (one query for all of them). Posts that no longer exist are dropped."""
    from feed.views import entries_qs   # imported here: feed.views imports this module

    items = list(items)
    ids = [i.entry_id for i in items if i.entry_id]
    by_pk = {e.pk: e for e in entries_qs(viewer).filter(pk__in=ids)} if ids else {}
    for item in items:
        item.card = by_pk.get(item.entry_id)
    return [i for i in items if i.kind == ShelfItem.Kind.FOLDER or i.card]


def pin_slots(user):
    """List of PIN_SLOTS entries: the pin in each slot, or None when the slot is empty."""
    by_slot = {p.slot: p for p in InterestPin.objects.filter(owner=user).select_related('entry')}
    return [by_slot.get(slot) for slot in range(1, PIN_SLOTS + 1)]


def pickable_posts(user):
    """The user's own posts that have a picture and are not pinned yet (newest first)."""
    return (
        Entry.objects
        .filter(author=user, kind=Entry.Kind.POST)
        .filter(HAS_PICTURE)
        .exclude(pins__owner=user)
        .order_by('-created_at', '-id')
    )


def addable_posts(user, collection=None):
    """Posts offered by "Add posts". On the shelf: your own posts that are not on it yet.
    For a collection: those too, plus the posts sitting loose on your shelf."""
    mine = ShelfItem.objects.filter(owner=user, entry=OuterRef('pk'))
    not_on_shelf = ~Exists(mine)
    qs = Entry.objects.filter(kind=Entry.Kind.POST)
    if collection is None:
        qs = qs.filter(author=user).filter(not_on_shelf)
    else:
        loose = Exists(mine.filter(parent__isnull=True))
        qs = qs.filter((Q(author=user) & not_on_shelf) | Q(loose))
    return qs.order_by('-created_at', '-id')[:ADD_LIMIT]


def next_position(owner, parent_id):
    """Position that puts a new item last among its siblings."""
    top = ShelfItem.objects.filter(owner=owner, parent_id=parent_id).aggregate(m=Max('position'))['m']
    return 0 if top is None else top + 1


def posts_on_shelf(user):
    return ShelfItem.objects.filter(owner=user, kind=ShelfItem.Kind.POST).count()


def shelf_is_full(user):
    return posts_on_shelf(user) >= settings.MAX_SHELF_ITEMS


def room_left(user):
    return max(0, settings.MAX_SHELF_ITEMS - posts_on_shelf(user))


def collections_are_full(user):
    return ShelfItem.objects.filter(owner=user, kind=ShelfItem.Kind.FOLDER).count() \
        >= settings.MAX_SHELF_GROUPS
