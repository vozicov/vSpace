from django import template

from accounts.models import Follow

register = template.Library()


@register.simple_tag
def following_of(user, limit=40):
    """The people `user` follows, newest follow first (for the right sidebar)."""
    return list(
        Follow.objects.filter(follower=user)
        .select_related('following__profile')
        .order_by('-created_at', '-id')[:limit]
    )


@register.filter
def tilt(value):
    """A small, steady "random" tilt in degrees (never flat) taken from an id, for the Explore grid."""
    angles = (-4, -3, -2, 2, 3, 4)
    mixed = (int(value) * 2654435761) % 4294967296
    return angles[(mixed >> 16) % len(angles)]
