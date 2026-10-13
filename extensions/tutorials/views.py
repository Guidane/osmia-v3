from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.http import Http404
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from .content import AUDIENCES, BY_SLUG, CATEGORIES, TUTORIALS


def _for(user, tutorial):
    """Administrators' tutorials only for administrators; the rest for everyone."""
    return tutorial.audience != 'admins' or user.is_superuser


def _gif(tutorial):
    return f'tutorials/{tutorial.gif}.gif' if tutorial.gif and finders.find(f'tutorials/{tutorial.gif}.gif') else ''


@login_required
def index(request):
    q = request.GET.get('q', '').strip().lower()
    groups = []
    for key, label in CATEGORIES:
        items = [t for t in TUTORIALS if t.category == key and _for(request.user, t)
                 and (not q or q in (t.title + ' ' + t.summary + ' ' + ' '.join(t.steps)).lower())]
        if items:
            groups.append({'label': label, 'items': [{'t': t, 'gif': _gif(t)} for t in items]})
    return render(request, 'tutorials/index.html', {'groups': groups, 'q': request.GET.get('q', ''), 'audiences': AUDIENCES})


@login_required
def detail(request, slug):
    tutorial = BY_SLUG.get(slug)
    if tutorial is None or not _for(request.user, tutorial):
        raise Http404
    try:
        try_href = reverse(tutorial.try_url) if tutorial.try_url else ''
    except NoReverseMatch:  # e.g. the designer, with its extension switched off
        try_href = ''
    visible = [t for t in TUTORIALS if _for(request.user, t)]
    i = visible.index(tutorial)
    return render(request, 'tutorials/detail.html', {
        't': tutorial, 'gif': _gif(tutorial), 'try_href': try_href, 'audience': AUDIENCES[tutorial.audience],
        'related': [BY_SLUG[s] for s in tutorial.related if s in BY_SLUG and _for(request.user, BY_SLUG[s])],
        'prev': visible[i - 1] if i > 0 else None, 'next': visible[i + 1] if i + 1 < len(visible) else None,
        'category': dict(CATEGORIES)[tutorial.category],
    })
