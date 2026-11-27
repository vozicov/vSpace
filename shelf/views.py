import random

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from feed.models import Entry

from .forms import CollectionForm, MoveForm
from .models import PIN_SLOTS, InterestPin, ShelfItem
from .queries import (
    addable_posts, collections_are_full, next_position, pickable_posts,
    room_left, shelf_is_full, with_entries)

Kind = ShelfItem.Kind


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pin_tilt():
    """Pinned posts get a random tilt, never dead straight."""
    return random.choice((-1, 1)) * random.randint(3, 10)


def _home_url(user, collection_id=None):
    """Your shelf is on your profile; a collection has a page of its own."""
    if collection_id:
        return reverse('collection', args=[collection_id])
    return reverse('profile', args=[user.username]) + '#shelf'


def _back(request, fallback):
    target = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return fallback


def _own_collection(request, pk):
    return get_object_or_404(ShelfItem, pk=pk, owner=request.user, kind=Kind.FOLDER)


# ---------- Shelf ----------

@login_required
def shelf_edit(request):
    """Old address of the editor: the shelf lives on your profile."""
    return redirect(_home_url(request.user))


@login_required
def collection_detail(request, pk):
    """A collection's own page: its posts as a grid, in the owner's look."""
    from feed.views import entries_qs   # imported here: feed.views imports shelf.queries

    collection = get_object_or_404(
        ShelfItem.objects.select_related('owner__profile'), pk=pk, kind=Kind.FOLDER)
    items = with_entries(
        ShelfItem.objects.filter(parent=collection).select_related('entry'), request.user)
    owner = collection.owner
    return render(request, 'shelf/collection.html', {
        'collection': collection,
        'profile_user': owner,
        'items': items,
        'is_owner': owner == request.user,
    })


@login_required
def collection_create(request):
    back = _home_url(request.user)
    if collections_are_full(request.user):
        return render(request, 'shelf/item_form.html', {
            'heading': 'Too many collections', 'back_url': back,
            'limit_text': f'You can have at most {settings.MAX_SHELF_GROUPS} collections.',
        })
    is_post = request.method == 'POST'
    form = CollectionForm(
        request.POST if is_post else None,
        instance=ShelfItem(owner=request.user, kind=Kind.FOLDER))
    if is_post and form.is_valid():
        form.instance.position = next_position(request.user, None)
        item = form.save()
        return redirect(_home_url(request.user, item.pk))
    return render(request, 'shelf/item_form.html', {
        'form': form, 'heading': 'New collection', 'back_url': back})


@login_required
def item_edit(request, pk):
    """Rename a collection, or move a post into / out of a collection."""
    item = get_object_or_404(
        ShelfItem.objects.select_related('entry', 'parent'), pk=pk, owner=request.user)
    is_post = request.method == 'POST'
    back = _home_url(request.user, item.parent_id)
    if item.kind == Kind.FOLDER:
        form = CollectionForm(request.POST if is_post else None, instance=item)
        heading = 'Rename collection'
    else:
        form = MoveForm(request.POST if is_post else None, instance=item, user=request.user)
        heading = 'Move post'
    if is_post and form.is_valid():
        item = form.save()
        return redirect(_home_url(request.user, item.pk if item.kind == Kind.FOLDER else item.parent_id))
    return render(request, 'shelf/item_form.html', {
        'form': form, 'heading': heading, 'back_url': back, 'item': item})


@login_required
def item_delete(request, pk):
    """Take a post off the shelf, or delete a collection. The posts themselves are never deleted."""
    item = get_object_or_404(ShelfItem, pk=pk, owner=request.user)
    if request.method == 'POST':
        parent_id = item.parent_id
        item.delete()
        return redirect(_back(request, _home_url(request.user, parent_id)))
    if item.kind == Kind.FOLDER:
        return render(request, 'shelf/confirm_delete.html', {'folder': item})
    return redirect(_home_url(request.user, item.parent_id))


@login_required
@require_POST
def item_move(request, pk, direction):
    if direction not in ('left', 'right'):
        raise Http404
    item = get_object_or_404(ShelfItem, pk=pk, owner=request.user)
    siblings = list(ShelfItem.objects.filter(owner=request.user, parent_id=item.parent_id))
    idx = next(i for i, s in enumerate(siblings) if s.pk == item.pk)
    swap = idx - 1 if direction == 'left' else idx + 1
    if 0 <= swap < len(siblings):
        siblings[idx], siblings[swap] = siblings[swap], siblings[idx]
        for i, s in enumerate(siblings):
            s.position = i
        ShelfItem.objects.bulk_update(siblings, ['position'])
    return redirect(_back(request, _home_url(request.user, item.parent_id)))


@login_required
def add_posts(request, pk=None):
    """Pick posts (tick boxes) to put on your shelf, or into one of your collections."""
    collection = _own_collection(request, pk) if pk else None
    back = _home_url(request.user, collection.pk if collection else None)
    if not collection and shelf_is_full(request.user):
        return render(request, 'shelf/add_posts.html', {
            'folder': collection, 'back_url': back, 'limit': settings.MAX_SHELF_ITEMS})

    allowed = {p.pk: p for p in addable_posts(request.user, collection)}
    if request.method == 'POST':
        picked = [allowed[i] for i in dict.fromkeys(
            _int(v) for v in request.POST.getlist('entry')) if i in allowed]
        parent_id = collection.pk if collection else None
        room = room_left(request.user)
        with transaction.atomic():
            for entry in picked:
                item = ShelfItem.objects.filter(owner=request.user, entry=entry).first()
                if item:   # already loose on the shelf: move it into the collection
                    if item.parent_id != parent_id:
                        item.parent_id = parent_id
                        item.position = next_position(request.user, parent_id)
                        item.save(update_fields=['parent', 'position'])
                elif room > 0:
                    ShelfItem.objects.create(
                        owner=request.user, kind=Kind.POST, entry=entry, parent_id=parent_id,
                        position=next_position(request.user, parent_id))
                    room -= 1
        return redirect(back)
    return render(request, 'shelf/add_posts.html', {
        'posts': list(allowed.values()), 'folder': collection, 'back_url': back,
        'room': room_left(request.user)})


# ---------- Buttons on a post ----------

@login_required
@require_POST
def shelf_toggle_post(request, entry_pk):
    """'Add to shelf' / 'Remove from shelf' on a post."""
    entry = get_object_or_404(Entry, pk=entry_pk, kind=Entry.Kind.POST)
    back = _back(request, entry.get_absolute_url())

    existing = ShelfItem.objects.filter(owner=request.user, entry=entry)
    if existing.exists():
        existing.delete()
        return redirect(back)

    if shelf_is_full(request.user):
        return render(request, 'shelf/notice.html', {
            'message': f'Your shelf is full ({settings.MAX_SHELF_ITEMS} items). '
                       'Remove something first.',
            'back': back,
        })
    try:
        with transaction.atomic():
            ShelfItem.objects.create(
                owner=request.user, kind=Kind.POST, entry=entry,
                position=next_position(request.user, None))
    except IntegrityError:   # double click: it is already there
        pass
    return redirect(back)


@login_required
@require_POST
def pin_toggle(request, entry_pk):
    """'Pin to profile' / 'Unpin' on a post: up to 4 posts shown next to the picture."""
    entry = get_object_or_404(Entry, pk=entry_pk, kind=Entry.Kind.POST)
    back = _back(request, entry.get_absolute_url())

    pins = list(InterestPin.objects.filter(owner=request.user))
    already = next((p for p in pins if p.entry_id == entry.pk), None)
    if already:
        already.delete()
        return redirect(back)

    by_slot = {p.slot: p for p in pins}
    free = [s for s in range(1, PIN_SLOTS + 1) if s not in by_slot]
    if free:
        try:
            with transaction.atomic():
                InterestPin.objects.create(
                    owner=request.user, entry=entry, slot=free[0],
                    rotation=_pin_tilt())
        except IntegrityError:
            pass
        return redirect(back)

    # All spots are taken: ask which one to replace.
    wanted = _int(request.POST.get('slot'))
    if wanted in by_slot:
        pin = by_slot[wanted]
        pin.entry = entry
        pin.save(update_fields=['entry'])
        return redirect(back)
    return render(request, 'shelf/pin_replace.html', {
        'entry': entry, 'pins': pins, 'back': back,
    })


@login_required
@require_POST
def pin_remove(request, slot):
    InterestPin.objects.filter(owner=request.user, slot=slot).delete()
    return redirect(_home_url(request.user))


@login_required
@require_POST
def pin_set(request):
    """The + next to the profile picture: pin one of your own posts that has a picture."""
    entry = get_object_or_404(pickable_posts(request.user), pk=_int(request.POST.get('entry')))
    taken = set(InterestPin.objects.filter(owner=request.user).values_list('slot', flat=True))
    free = [s for s in range(1, PIN_SLOTS + 1) if s not in taken]
    if not free:
        return render(request, 'shelf/notice.html', {
            'message': f'All {PIN_SLOTS} spots next to your picture are taken. '
                       'Unpin one with its x first.',
            'back': _home_url(request.user),
        })
    slot = _int(request.POST.get('slot'))
    if slot not in free:
        slot = free[0]
    try:
        with transaction.atomic():
            InterestPin.objects.create(
                owner=request.user, entry=entry, slot=slot, rotation=_pin_tilt())
    except IntegrityError:   # double click
        pass
    return redirect(_home_url(request.user))
