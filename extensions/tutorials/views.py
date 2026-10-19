import json
import math
import re
from functools import lru_cache

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


@lru_cache(maxsize=None)
def _steps(folder):
    """The step-by-step pictures of a tutorial, in order: [{'image': static path, 'caption', 'width', 'height'}]."""
    path = finders.find(f'tutorials/{folder}/steps.json') if folder else None
    if not path:
        return ()
    with open(path, encoding='utf-8') as f:
        return tuple({**s, 'image': f'tutorials/{folder}/{s["image"]}'} for s in json.load(f))


def _pictures(tutorial):
    return list(_steps(tutorial.pictures))


# Words a question is made of that say nothing about what it's after
QUIET = {'how', 'what', 'can', 'the', 'and', 'for', 'with', 'into', 'onto', 'from', 'make', 'get', 'see', 'want', 'way',
         'do', 'does', 'my', 'your', 'our', 'you', 'its', 'are', 'there', 'this', 'that', 'some', 'show', 'put', 'add', 'use'}


def _words(text):
    """The words of ``text`` to search with, plurals made singular (tasks: task)."""
    out = []
    for w in re.findall(r'[\w-]+', text.lower()):
        w = w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w
        if len(w) > 2 and w not in QUIET:
            out.append(w)
    return out


def search(tutorials, q):
    """The tutorials that match most of the words of ``q``, best first: a question in your own words
    ("how do I make an overview of tasks on the home screen") finds the recipe for it."""
    words = _words(q) or [q.lower()]
    needed = max(1, math.ceil(len(words) / 2))
    found = []
    for i, t in enumerate(tutorials):
        title = ' '.join(_words(t.title))
        text = ' '.join(_words(' '.join([t.title, t.summary, *t.steps, *t.tips, t.keywords])))
        hits = sum(1 for w in words if w in text)
        if hits >= needed:
            # the more words, and the more of them in the title, the better; How do I… before the rest
            found.append((-(hits * 2 + sum(1 for w in words if w in title)), t.category != 'howto', i, t))
    return [t for *_, t in sorted(found)]


@login_required
def index(request):
    q = request.GET.get('q', '').strip()
    visible = [t for t in TUTORIALS if _for(request.user, t)]
    if q:
        found = search(visible, q)
        groups = [{'label': 'Best matches', 'items': [{'t': t, 'pictures': bool(_pictures(t))} for t in found]}] if found else []
    else:
        groups = []
        for key, label in CATEGORIES:
            items = [t for t in visible if t.category == key]
            if items:
                groups.append({'label': label, 'items': [{'t': t, 'pictures': bool(_pictures(t))} for t in items]})
    return render(request, 'tutorials/index.html', {'groups': groups, 'q': q, 'audiences': AUDIENCES})


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
        't': tutorial, 'pictures': _pictures(tutorial), 'try_href': try_href, 'audience': AUDIENCES[tutorial.audience],
        'related': [BY_SLUG[s] for s in tutorial.related if s in BY_SLUG and _for(request.user, BY_SLUG[s])],
        'prev': visible[i - 1] if i > 0 else None, 'next': visible[i + 1] if i + 1 < len(visible) else None,
        'category': dict(CATEGORIES)[tutorial.category],
    })
