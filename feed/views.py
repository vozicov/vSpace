import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404
from django.db.models import BooleanField, Count, Exists, OuterRef, Q, Value
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import Follow
from accounts.privacy import PUBLIC_ENTRIES, can_see_entry, can_see_kind, can_see_profile
from shelf.models import PIN_SLOTS, InterestPin, ShelfItem
from shelf.queries import (
    PICKER_LIMIT, collections_are_full, pickable_posts, pin_slots, shelf_for, with_entries)

from .forms import PostEditForm, PostForm, TweetEditForm, TweetForm
from .models import HAS_PICTURE, Entry, Like


def entries_qs(user):
    """Entries annotated with reply/like counts and whether `user` liked them.
    `user` may be a visitor who is not signed in: then nothing is liked, shelved or pinned."""
    if user.is_authenticated:
        mine = {
            'liked_by_me': Exists(Like.objects.filter(entry=OuterRef('pk'), user=user)),
            'on_shelf_by_me': Exists(ShelfItem.objects.filter(entry=OuterRef('pk'), owner=user)),
            'pinned_by_me': Exists(InterestPin.objects.filter(entry=OuterRef('pk'), owner=user)),
        }
    else:
        no = Value(False, output_field=BooleanField())
        mine = {'liked_by_me': no, 'on_shelf_by_me': no, 'pinned_by_me': no}
    return (
        Entry.objects
        .select_related('author__profile', 'parent__author')
        .annotate(
            reply_count=Count('replies', distinct=True),
            like_count=Count('likes', distinct=True),
            **mine,
        )
        # Meta.ordering is ignored once a query has Count() annotations, so say it here
        .order_by('-created_at', '-id')
    )


def already_posted(request):
    """Double-submit guard, step 1. Every form carries a one-time token. If this user already
    has an entry made with the token in this POST, the earlier click won: return that entry."""
    try:
        token = uuid.UUID(request.POST.get('submit_token', ''))
    except ValueError:
        return None
    return Entry.objects.filter(author=request.user, submit_token=token).first()


def save_once(form):
    """Double-submit guard, step 2. Two clicks can arrive at the same moment, so the database
    (a unique column) decides the winner. The loser removes the files it just wrote and gets
    the winner's entry back."""
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        entry = form.instance
        entry.media.delete(save=False)
        entry.thumbnail.delete(save=False)
        winner = Entry.objects.filter(author=entry.author, submit_token=entry.submit_token).first()
        if winner is None:
            raise  # not a duplicate, a real database error
        return winner


def paginate(request, qs, per_page=20):
    return Paginator(qs, per_page).get_page(request.GET.get('page'))


@login_required
def home(request):
    followed = Follow.objects.filter(follower=request.user).values_list('following_id', flat=True)
    following_any = followed.exists()

    qs = entries_qs(request.user).filter(kind=Entry.Kind.POST)
    if following_any:
        qs = qs.filter(Q(author_id__in=followed) | Q(author=request.user))

    return render(request, 'feed/home.html', {
        'page_obj': paginate(request, qs),
        'following_any': following_any,
    })


@login_required
def explore(request):
    qs = (
        entries_qs(request.user)
        .filter(kind=Entry.Kind.POST)
        .exclude(author=request.user)
        # only posts that have a picture to show (an image, a video thumbnail or a song cover)
        .filter(HAS_PICTURE)
    )
    # 30 per page fills whole rows of both 3 (phone) and 5 (computer)
    return render(request, 'feed/explore.html', {'page_obj': paginate(request, qs, 30)})


@login_required
def tweets(request):
    is_post = request.method == 'POST'
    if is_post and already_posted(request):
        return redirect('tweets')
    form = TweetForm(
        request.POST if is_post else None,
        instance=Entry(author=request.user, kind=Entry.Kind.TWEET),
    )
    if is_post and form.is_valid():
        save_once(form)
        return redirect('tweets')

    qs = entries_qs(request.user).filter(kind=Entry.Kind.TWEET)
    return render(request, 'feed/tweets.html', {'form': form, 'page_obj': paginate(request, qs)})


@login_required
def post_create(request):
    is_post = request.method == 'POST'
    duplicate = already_posted(request) if is_post else None
    if duplicate:
        return redirect(duplicate)
    form = PostForm(
        request.POST if is_post else None,
        request.FILES if is_post else None,
        instance=Entry(author=request.user, kind=Entry.Kind.POST),
    )
    if is_post and form.is_valid():
        return redirect(save_once(form))
    return render(request, 'feed/post_form.html', {
        'form': form,
        'max_image_mb': settings.MAX_IMAGE_UPLOAD_MB,
        'max_video_mb': settings.MAX_VIDEO_UPLOAD_MB,
    })


def entry_detail(request, pk):
    entry = get_object_or_404(entries_qs(request.user), pk=pk)
    # Visitors who are not signed in only get in when the author allows it (Settings > Privacy).
    # Otherwise they go to the login page, the same as for a missing entry, so nothing leaks.
    if not can_see_entry(request.user, entry):
        return redirect_to_login(request.get_full_path())

    is_post = request.method == 'POST'
    if is_post and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if is_post and already_posted(request):
        return redirect(entry)
    form = None
    if request.user.is_authenticated:
        # A comment is saved as a tweet owned by the commenter.
        form = TweetForm(
            request.POST if is_post else None,
            instance=Entry(author=request.user, kind=Entry.Kind.TWEET, parent=entry),
        )
        if is_post and form.is_valid():
            save_once(form)
            return redirect(entry)

    replies = entries_qs(request.user).filter(parent=entry).order_by('created_at')
    if not request.user.is_authenticated:
        replies = replies.filter(PUBLIC_ENTRIES)   # comments by people who keep their tweets private stay hidden
    return render(request, 'feed/detail.html', {'entry': entry, 'replies': replies, 'form': form})


@login_required
def entry_edit(request, pk):
    """Edit your own post, tweet or comment. Anyone else gets a 404."""
    # `saved` is what the page shows. The form works on its own copy, because a form that
    # fails validation has already changed the entry it holds.
    saved = get_object_or_404(Entry, pk=pk, author=request.user)
    entry = get_object_or_404(Entry, pk=pk, author=request.user)
    is_post = request.method == 'POST'

    if entry.kind == Entry.Kind.POST:
        form = PostEditForm(
            request.POST if is_post else None, request.FILES if is_post else None, instance=entry)
    else:
        form = TweetEditForm(request.POST if is_post else None, instance=entry)

    if is_post and form.is_valid():
        form.save()
        return redirect(saved)

    context = {'form': form, 'saved': saved, 'editing': True}
    if saved.kind == Entry.Kind.POST:
        context.update({
            'max_image_mb': settings.MAX_IMAGE_UPLOAD_MB,
            'max_video_mb': settings.MAX_VIDEO_UPLOAD_MB,
        })
        return render(request, 'feed/post_form.html', context)
    return render(request, 'feed/tweet_edit.html', context)


@login_required
def entry_delete(request, pk):
    """Delete your own post, tweet or comment. GET asks, POST does it. Anyone else gets a 404."""
    entry = get_object_or_404(entries_qs(request.user), pk=pk, author=request.user)

    if request.method == 'POST':
        parent = entry.parent
        kind = entry.kind
        files = [(f.storage, f.name) for f in (entry.media, entry.thumbnail) if f.name]
        with transaction.atomic():
            entry.delete()       # its comments, likes, shelf items and pins go with it
        for storage, name in files:
            storage.delete(name)

        if parent:
            return redirect(parent)
        target = reverse('profile', args=[request.user.username])
        return redirect(target + ('?kind=tweet' if kind == Entry.Kind.TWEET else ''))

    return render(request, 'feed/entry_confirm_delete.html', {'entry': entry})


@login_required
@require_POST
def like_toggle(request, pk):
    entry = get_object_or_404(Entry, pk=pk)
    like, created = Like.objects.get_or_create(user=request.user, entry=entry)
    if not created:
        like.delete()

    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = entry.get_absolute_url()
    return redirect(target)


def profile(request, username):
    User = get_user_model()
    profile_user = User.objects.select_related('profile').filter(username=username).first()
    # Not signed in: only profiles that switched "Anyone can see my profile" on. A private or
    # missing profile both go to the login page, so a visitor cannot tell which names exist.
    if profile_user is None:
        if request.user.is_authenticated:
            raise Http404('No such user')
        return redirect_to_login(request.get_full_path())
    if not can_see_profile(request.user, profile_user):
        return redirect_to_login(request.get_full_path())

    me = request.user.is_authenticated
    show_posts = can_see_kind(request.user, profile_user, Entry.Kind.POST)
    show_tweets = can_see_kind(request.user, profile_user, Entry.Kind.TWEET)
    allowed = [k for k, ok in ((Entry.Kind.POST, show_posts), (Entry.Kind.TWEET, show_tweets)) if ok]

    # Tabs: posts (the default), tweets, all. A visitor only gets the tabs the owner allows.
    kind = request.GET.get('kind')
    if kind == 'all' and len(allowed) < 2:
        kind = None
    if kind not in (Entry.Kind.POST, Entry.Kind.TWEET, 'all') or (kind != 'all' and kind not in allowed):
        kind = allowed[0] if allowed else Entry.Kind.POST
    qs = entries_qs(request.user).filter(author=profile_user, kind__in=allowed)
    if kind != 'all':
        qs = qs.filter(kind=kind)

    is_owner = profile_user == request.user
    slots = pin_slots(profile_user) if show_posts else [None] * PIN_SLOTS
    has_free_slot = any(pin is None for pin in slots)
    # Collections live on login-only pages, so a visitor who is not signed in does not get them
    shelf = with_entries(shelf_for(profile_user), request.user) if me and show_posts else []

    return render(request, 'feed/profile.html', {
        'profile_user': profile_user,
        'page_obj': paginate(request, qs),
        'kind': kind,
        'show_posts': show_posts,
        'show_tweets': show_tweets,
        'followers_count': Follow.objects.filter(following=profile_user).count(),
        'following_count': Follow.objects.filter(follower=profile_user).count(),
        'is_following': me and Follow.objects.filter(
            follower=request.user, following=profile_user
        ).exists(),
        'collections': [i for i in shelf if i.kind == ShelfItem.Kind.FOLDER],
        'shelf_posts': [i for i in shelf if i.kind == ShelfItem.Kind.POST],
        'pin_slots': slots,
        # Only the owner gets the editing tools (+ buttons, the post picker)
        'is_owner': is_owner,
        'can_add_collection': is_owner and not collections_are_full(request.user),
        'pickable': list(pickable_posts(request.user)[:PICKER_LIMIT])
                    if is_owner and has_free_slot else [],
    })
