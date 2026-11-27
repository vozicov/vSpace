"""Who may see what. Signed-in members see everything. A visitor who is not signed in sees only
what the profile owner has switched on in Settings > Privacy."""
from django.db.models import Q

from feed.models import Entry


def can_see_profile(viewer, owner):
    """May `viewer` open `owner`'s profile page?"""
    return viewer.is_authenticated or owner.profile.is_public


def can_see_kind(viewer, owner, kind):
    """May `viewer` see `owner`'s posts (kind='post') or tweets (kind='tweet')?"""
    if viewer.is_authenticated:
        return True
    p = owner.profile
    return p.is_public and (p.public_posts if kind == Entry.Kind.POST else p.public_tweets)


def can_see_entry(viewer, entry):
    """May `viewer` open this entry? A comment is a tweet, so it follows the tweet switch."""
    return can_see_kind(viewer, entry.author, entry.kind)


# The same rules as a queryset filter, for lists of entries by several authors (comments).
PUBLIC_ENTRIES = Q(author__profile__is_public=True) & (
    Q(kind=Entry.Kind.POST, author__profile__public_posts=True)
    | Q(kind=Entry.Kind.TWEET, author__profile__public_tweets=True)
)
