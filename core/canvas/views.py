"""What the page editor asks the server: records to put on a page, a record's fields,
a calculation's preview, and what the slash menu offers."""
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..data import Data, record_ids_with_text
from ..extensions import registry
from ..permissions import can, visible_apps
from .calc import PageData, result
from .render import NOT_SHOWN
from .sanitize import clean

EMBEDDABLE = ('grid', 'tree', 'kanban', 'gallery', 'calendar', 'gantt')


def editor_config(request, where='page', upload_url=''):
    """What the editor's slash menu offers: ``where`` is 'space', 'app' or 'page'."""
    apps = visible_apps(request.user)
    views = []
    for app in apps:
        for table in app.tables.all():
            for view in table.views.all():
                if view.type in EMBEDDABLE:
                    views.append([f'{app.name} › {table.name} › {view.name}', view.pk])
    block_where = where if where in ('space', 'app') else 'page'
    return {
        'records': reverse('core:editor_records'), 'calc': reverse('core:editor_calc'), 'upload': upload_url,
        'views': views,
        'apps': [{'slug': a.slug, 'name': a.name, 'icon': a.icon, 'color': a.color} for a in apps],
        'blocks': [{'key': b.key, 'label': b.label, 'icon': b.icon, 'help': b.help}
                   for b in registry.blocks.values() if b.where == 'any' or b.where == block_where],
    }


@login_required
def records_for_link(request):
    """Records to put on a page: ?q= across the tables the writer can see.
    Big tables are searched in the database (their stored text), not loaded whole."""
    q = request.GET.get('q', '').strip()
    data = PageData(request.user)
    out = []
    if q:
        for app in visible_apps(request.user):
            for table in app.tables.all():
                if data.is_big(table.pk):
                    found = data.records_by_ids(list(record_ids_with_text(table.pk, q)[:5]))
                else:
                    found = data.search(table, q, limit=5)
                for r in found:
                    out.append({'id': r.pk, 'label': data.label(r), 'where': f'{app.name} › {table.name}'})
                if len(out) >= 30:
                    break
    return JsonResponse({'records': out[:30]})


@login_required
def record_for_link(request, pk):
    """A record and its fields as they are now, for choosing what a card or a value shows."""
    data = Data(request.user)
    record = data.record(pk)
    if record is None or not can(request.user, data.table(record.table_id).app, 'viewer'):
        raise Http404
    fields = [{'id': f.pk, 'name': f.name, 'text': data.text(record, f)[:80]}
              for f in data.fields(record.table_id) if f.type not in NOT_SHOWN]
    table = data.table(record.table_id)
    return JsonResponse({'id': record.pk, 'label': data.label(record), 'icon': table.icon or '▦',
                         'where': f'{table.app.name} › {table.name}', 'fields': fields})


@login_required
@require_POST
def calc_preview(request):
    """What a calculation being written shows: ?index= of the calculations in the posted body."""
    try:
        index = int(request.POST.get('index', ''))
    except ValueError:
        return JsonResponse({'error': 'Which calculation?'}, status=400)
    return JsonResponse({'html': result(clean(request.POST.get('body', '')), request.user, index)})
