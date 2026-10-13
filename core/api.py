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
    if isinstance(exc, ValidationError):
        return JsonResponse({'error': ' '.join(exc.messages)}, status=status)
    return JsonResponse({'error': str(exc)}, status=status)


def _record(request, pk, needed):
    record = get_object_or_404(Record.objects.select_related('table__app'), pk=pk)
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
        'cells': {f.pk: {'html': str(data.html(record, f)), 'raw': data.raw(record, f)} for f in data.fields(record.table_id)},
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
    found = data.search(table, request.GET.get('q', ''), limit=limit)
    full = request.GET.get('full')
    return JsonResponse({'records': [record_json(data, r) if full else {'id': r.pk, 'label': data.label(r)} for r in found]})


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
    values = _body(request).get('values') or {}
    try:
        service.update_record(record, values, user=request.user, data=data)
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(record_json(data, record))


@login_required
@require_POST
def record_create(request, table_id):
    table = get_object_or_404(Table.objects.select_related('app'), pk=table_id)
    require(request.user, table.app, 'editor')
    data = Data(request.user)
    try:
        record = service.create_record(table, _body(request).get('values') or {}, user=request.user, data=data)
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
