"""What the Documentation app adds to Osmia (see core.extensions)."""
from django.template.loader import render_to_string

from core.extensions import Panel


def space_pages_block(request, context):
    """On a space's page: its pages, and buttons to write one."""
    from .models import Page
    from .service import can_write, visible_pages
    from .starters import TEMPLATES
    space = context.get('space')
    if space is None:
        return ''
    pages = visible_pages(request.user, Page.objects.filter(space=space).select_related('updated_by').order_by('-updated_at'))
    return render_to_string('docs/_space_block.html', {
        'space': space, 'pages': pages[:8], 'count': len(pages), 'templates': TEMPLATES,
        'can_write': can_write(request.user, space)}, request=request)


def pinned_block(request, context):
    from .models import PagePin
    from .service import visible_pages
    pins = visible_pages(request.user, [p.page for p in PagePin.objects.filter(user=request.user).select_related('page__space')])
    return render_to_string('docs/_pins_block.html', {'pins': pins[:10]}, request=request)


def search(request, q):
    from core.data import Data

    from .views import search_pages
    data = Data(request.user)
    out = [(f'{p.emoji or "📄"} {p.title}', p.get_absolute_url(), data.label(p.space)) for p in search_pages(request.user, q)]
    return ('Pages', out) if out else None


def mentioned_in(request, record, data):
    """On a record's page: the pages that mention it (the ones the reader can see)."""
    from .models import PageReference
    from .service import visible_pages
    refs = PageReference.objects.filter(record=record).select_related('page__space', 'page__updated_by').order_by('-page__updated_at')
    pages = visible_pages(request.user, [r.page for r in refs])
    if not pages:
        return None
    html = render_to_string('docs/_mentioned_in.html', {'pages': pages[:20], 'more': max(0, len(pages) - 20)}, request=request)
    return Panel(f'Mentioned in {len(pages)} page{"s" if len(pages) != 1 else ""}', html, order=50)


def access_changed(record_ids):
    from .service import refresh_access
    refresh_access(record_ids)


def dependencies(removal, gone):
    """Pages showing something that would be removed."""
    from core.canvas.references import targets, uses

    from .models import Page
    records, slugs = targets(removal)
    out = []
    for page in Page.objects.exclude(space__table_id__in=removal.tables).only('pk', 'title', 'body'):
        if uses(page.body, removal, gone, records, slugs):
            out.append(f'The page "{page.title}" (Documentation) shows it.')
    return out


def pages():
    from .models import Page
    return [(f'the page "{p.title}" (Documentation)', p.body) for p in Page.objects.only('title', 'body')]


def register(registry):
    registry.app('Documentation', 'docs:index', '📄', 'Pages for people to read, a section for every space.',
                 color='#7c3aed', extension='docs', group='Workspace')
    registry.block('space_pages', 'Pages of this space', space_pages_block, icon='📄', where='space',
                   help='The Documentation pages of this space, and buttons to write one.')
    registry.block('pinned_pages', 'Pinned pages', pinned_block, icon='📌', help='The pages you pinned.')
    registry.search(search)
    registry.record_panel(mentioned_in)
    registry.on_access_change(access_changed)
    registry.dependency_check(dependencies)
    registry.page_source(pages)
