"""What Pages adds to Osmia (see core.extensions)."""
from django.template.loader import render_to_string
from django.urls import reverse

from core.extensions import Panel


def nav(request, space):
    return [('📄', 'Pages', reverse('pages:space', args=[space.key]))]


def space_section(request, space):
    from core.permissions import can_space

    from .models import Page
    from .render import TEMPLATES
    pages = Page.objects.filter(space=space).select_related('updated_by').order_by('-updated_at')[:6]
    html = render_to_string('pages/_space_section.html', {
        'space': space, 'pages': pages, 'count': Page.objects.filter(space=space).count(), 'templates': TEMPLATES,
        'can_write': can_space(request.user, space, 'editor') if request else False}, request=request)
    return Panel('Pages', html, order=10)


def home_pinned(request):
    from core.permissions import can_space

    from .models import PagePin
    pins = [p.page for p in PagePin.objects.filter(user=request.user).select_related('page__space')
            if can_space(request.user, p.page.space, 'viewer')][:10]
    html = render_to_string('pages/_home_pins.html', {'pins': pins}, request=request)
    return Panel('Pinned pages', html, order=20)


def search(request, q):
    from core.permissions import can_space

    from .models import Page
    from .sanitize import text_of
    out = []
    low = q.lower()
    for page in Page.objects.select_related('space').order_by('-updated_at')[:2000]:
        if low in page.title.lower() or low in text_of(page.body).lower() or low in page.labels.lower():
            if can_space(request.user, page.space, 'viewer'):
                out.append((f'{page.emoji or "📄"} {page.title}', page.get_absolute_url(), page.space.name))
        if len(out) >= 20:
            break
    return ('Pages', out) if out else None


def register(registry):
    registry.space_nav(nav)
    registry.space_section(space_section)
    registry.home_section('pages', 'Pinned pages', home_pinned)
    registry.search(search)
