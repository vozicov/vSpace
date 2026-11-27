from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Notification


@login_required
def notification_list(request):
    qs = Notification.objects.filter(recipient=request.user).select_related(
        'actor__profile', 'entry__parent')
    page_obj = Paginator(qs, 30).get_page(request.GET.get('page'))
    items = list(page_obj)   # read them first: what was unread when you arrived stays highlighted
    Notification.objects.filter(pk__in=[n.pk for n in items if not n.is_read]).update(is_read=True)
    return render(request, 'notifications/list.html', {'page_obj': page_obj, 'items': items})
