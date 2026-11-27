from django import template

from notifications.models import Notification

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notifications(context):
    """How many notifications the signed-in member has not seen yet (0 for visitors)."""
    request = context.get('request')
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return 0
    return Notification.objects.filter(recipient=user, is_read=False).count()
