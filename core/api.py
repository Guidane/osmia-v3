"""JSON endpoints for the pages' scripts (cell editing, drag and drop, pickers,
buttons) and for extensions. Every change still goes through core.service, so
automations, validation and history apply exactly as on the forms."""
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from . import service
from .data import Data
from .models import Automation, Field, Record, Table, View
from .permissions import can, require


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


def _error(exc, status=400):
    from .access import NeedsSharing
    if isinstance(exc, NeedsSharing):   # the page asks "share it with them?" and sends it again with "share": true
        return JsonResponse({'error': ' '.join(exc.messages), 'needs_share': True}, status=409)
    if isinstance(exc, ValidationError):
        return JsonResponse({'error': ' '.join(exc.messages)}, status=status)
    return JsonResponse({'error': str(exc)}, status=status)


def _record(request, pk, needed):
    """The record, if the person may see it (its app and its access tags)."""
    from django.http import Http404

    from .access import can_see
    record = get_object_or_404(Record.objects.select_related('table__app'), pk=pk)
    if not can_see(request.user, record):
        raise Http404('There is no such record.')
    require(request.user, record.table.app, needed)
    return record


def record_json(data, record):
    """Every field's value, shown (html) and raw, keyed by field id."""
    record = data.record(record.pk)
    return {
        'id': record.pk,
        'label': data.label(record),
        'url': record.get_absolute_url(),
        'table': record.table_id,
        'cells': {f.pk: {'html': str(data.html(record, f)), 'raw': data.raw(record, f),
                         **({'expected': f.kind.expected(f, record, data)} if f.type == 'attributes' else {})}
                  for f in data.fields(record.table_id)},
        'values': {f.key: _plain(data.raw(record, f)) for f in data.fields(record.table_id) if f.type != 'button'},
    }


def _plain(value):
    if isinstance(value, (str, int, float, bool, type(None), list, dict)):
        return value
    return str(value)


@login_required
@require_GET
def table_records(request, table_id):
    """Records for pickers: ?q= search, ?limit=. [{id, label}]"""
    table = get_object_or_404(Table.objects.select_related('app'), pk=table_id)
    require(request.user, table.app, 'viewer')
    data = Data(request.user)
    try:
        limit = min(int(request.GET.get('limit', 30)), 500)
    except ValueError:
        limit = 30
    under = request.GET.get('under', '')   # "<link field id>:<record id>": linked to that node of a tree, or under it
    browse = _browse(data, table) if request.GET.get('rich') else None
    if under.count(':') == 1 and all(p.isdigit() for p in under.split(':')):
        field_id, node = (int(p) for p in under.split(':'))
        field = data.field(field_id)
        if field is None or field.table_id != table.pk:
            return JsonResponse({'error': 'No such field.'}, status=400)
        from .trees import Tree
        nodes = {node} | set(Tree(data, field.opt('target')).descendant_ids(node))
        found = [r for r in data.search(table, request.GET.get('q', ''), limit=5000)
                 if set(getattr(data.value(r, field), 'ids', None) or []) & nodes][:limit]
    else:
        found = data.search(table, request.GET.get('q', ''), limit=limit)
    if request.GET.get('full'):
        return JsonResponse({'records': [record_json(data, r) for r in found]})
    if not request.GET.get('rich'):
        return JsonResponse({'records': [{'id': r.pk, 'label': data.label(r)} for r in found]})
    return JsonResponse({'records': [_rich(data, table, r) for r in found], 'browse': browse})


def _rich(data, table, record):
    """A record for a picker that shows more than its name: a line about it and a small picture of it."""
    from .models import Attachment
    display = table.display_field_id
    detail = next((f for f in data.fields(table) if f.type == 'text' and f.pk != display), None)
    picture = Attachment.objects.filter(record=record, is_image=True).order_by('position', 'pk').first()
    return {'id': record.pk, 'label': data.label(record),
            'detail': (data.text(record, detail) or '')[:90] if detail else '',
            'thumb': picture.get_absolute_url() + '?thumb=1' if picture else ''}


def _browse(data, table):
    """A tree the records link to (a part's category), to browse them by: {field, name, nodes: [{id, label, depth}]}."""
    from .trees import Tree
    for f in data.fields(table):
        if f.type != 'link':
            continue
        target = data.table(f.opt('target'))
        if target is None or not target.tree_field_id or target.pk == table.pk:
            continue
        tree, nodes = Tree(data, target), []

        def walk(node, depth):
            nodes.append({'id': node.pk, 'label': data.label(node), 'depth': depth})
            for kid in tree.kids(node.pk):
                walk(kid, depth + 1)
        for root_node in tree.roots():
            walk(root_node, 0)
        return {'field': f.pk, 'name': f.name, 'nodes': nodes}
    return None


@login_required
def record_api(request, pk):
    """GET: the record. POST {"values": {field id or key: value}}: change it."""
    if request.method == 'GET':
        record = _record(request, pk, 'viewer')
        return JsonResponse(record_json(Data(request.user), record))
    if request.method != 'POST':
        return JsonResponse({'error': 'GET or POST'}, status=405)
    record = _record(request, pk, 'editor')
    data = Data(request.user)
    body = _body(request)
    try:
        service.update_record(record, body.get('values') or {}, user=request.user, data=data, share=bool(body.get('share')))
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(record_json(data, record))


@login_required
@require_POST
def record_create(request, table_id):
    table = get_object_or_404(Table.objects.select_related('app'), pk=table_id)
    require(request.user, table.app, 'editor')
    data = Data(request.user)
    body = _body(request)
    try:
        record = service.create_record(table, body.get('values') or {}, user=request.user, data=data, share=bool(body.get('share')))
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(record_json(data, record))


@login_required
@require_POST
def record_delete(request, pk):
    record = _record(request, pk, 'editor')
    try:
        service.delete_record(record, request.user)
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse({'deleted': pk})


@login_required
@require_POST
def record_move(request, pk):
    record = _record(request, pk, 'editor')
    body = _body(request)
    service.move_record(record, before_id=body.get('before'), after_id=body.get('after'))
    return JsonResponse({'ok': True})


@login_required
@require_POST
def record_link(request, pk, field_id):
    """{"add": id} or {"remove": id}: one more or one fewer linked record."""
    record = _record(request, pk, 'editor')
    field = get_object_or_404(Field, pk=field_id, table=record.table, type='link')
    data = Data(request.user)
    body = _body(request)
    ids = data.linked_ids(data.record(record.pk), field)
    if body.get('add'):
        new = int(body['add'])
        ids = (ids + [new]) if field.opt('multiple') else [new]
    if body.get('remove'):
        ids = [i for i in ids if i != int(body['remove'])]
    try:
        service.update_record(record, {field.pk: list(dict.fromkeys(ids))}, user=request.user, data=data)
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(record_json(data, record))


@login_required
@require_POST
def record_button(request, pk, field_id):
    record = _record(request, pk, 'editor')
    field = get_object_or_404(Field, pk=field_id, table=record.table, type='button')
    data = Data(request.user)
    try:
        run = service.press_button(record, field, request.user, data)
    except ValidationError as exc:
        return _error(exc)
    return _run_result(run, data, record)


@login_required
@require_POST
def record_run(request, pk, automation_id):
    record = _record(request, pk, 'editor')
    auto = get_object_or_404(Automation, pk=automation_id, table=record.table, active=True)
    data = Data(request.user)
    try:
        runs = service.run_manually(auto, [record], request.user)
    except ValidationError as exc:
        return _error(exc)
    return _run_result(runs[0] if runs else None, data, record)


def _run_result(run, data, record):
    if run is None:
        return JsonResponse({'ok': True, 'message': 'Nothing to do.'})
    ok = run.status == run.Status.OK
    payload = {'ok': ok, 'status': run.status, 'message': run.log, 'record': None}
    if Record.objects.filter(pk=record.pk).exists():
        data.invalidate()
        payload['record'] = record_json(data, record)
    return JsonResponse(payload, status=200 if ok or run.status == run.Status.SKIPPED else 400)


@login_required
@require_POST
def view_config(request, view_id):
    """Save part of a view's settings (shown fields, widths, filters, sorts, group)."""
    view = get_object_or_404(View.objects.select_related('table__app'), pk=view_id)
    body = _body(request)
    keys = set(body)
    personal = {'widths'}
    if keys - personal:
        require(request.user, view.table.app, 'creator')
    else:
        require(request.user, view.table.app, 'editor')
    allowed = {'fields', 'widths', 'filters', 'sorts', 'group_by', 'zoom'}
    cfg = dict(view.config or {})
    for key, value in body.items():
        if key in allowed:
            if value in (None, '', []):
                cfg.pop(key, None)
            else:
                cfg[key] = value
    view.config = cfg
    view.save(update_fields=['config'])
    return JsonResponse({'config': cfg})


@login_required
@require_GET
def table_schema(request, table_id):
    """A table's fields, for extensions and scripts."""
    table = get_object_or_404(Table.objects.select_related('app'), pk=table_id)
    require(request.user, table.app, 'viewer')
    data = Data(request.user)
    return JsonResponse({'id': table.pk, 'name': table.name, 'app': table.app.name, 'key': table.key,
                         'fields': [{'id': f.pk, 'key': f.key, 'name': f.name, 'type': f.type, 'options': f.options,
                                     'required': f.required, 'editable': f.editable} for f in data.fields(table)],
                         'can_edit': can(request.user, table.app, 'editor')})
