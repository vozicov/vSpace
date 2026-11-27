from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import queries


@login_required
@require_GET
def search(request):
    q = request.GET.get('q', '').strip()[:100]
    kind = request.GET.get('type', 'all')
    if kind not in queries.TYPES:
        kind = 'all'
    short = queries.too_short(q)
    results = queries.run(q, kind)
    context = {
        'q': q,
        'type': kind,
        'results': results,
        'too_short': short,
        'has_any': any(results.values()),
    }
    # The drawer asks for just the inside of the panel; the full page (also what Enter and
    # people without JavaScript get) is a normal page.
    template = 'search/_drawer.html' if request.GET.get('fragment') else 'search/results.html'
    return render(request, template, context)
