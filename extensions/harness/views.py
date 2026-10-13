"""The designer page and the JSON API it talks to (the stand-alone app's shapes)."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from core.permissions import can

from .drawing import Apps
from .models import DrawingVersion


def _apps(request, needed='viewer'):
    apps = Apps(request.user)
    if not apps.ready:
        raise Http404('Install the Devices and Harness templates first.')
    for table in (apps.devices, apps.projects):
        if not can(request.user, table.app, needed):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f'You need "{needed}" access to {table.app.name}.')
    return apps


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return None


def _error(exc, status=400):
    return JsonResponse({'error': ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)}, status=status)


@login_required
def designer(request):
    apps = Apps(request.user)
    if not apps.ready:
        return render(request, 'harness/not_ready.html', {})
    return render(request, 'harness/designer.html', {
        'api_base': reverse('harness:api_devices').removesuffix('/devices'),
        'users_url': reverse('accounts:user_list') if request.user.is_superuser else reverse('accounts:profile'),
        'devices_url': apps.devices.get_absolute_url(),
        'devices_create_url': reverse('core:record_new', args=[apps.devices.app.slug, apps.devices.slug]),
        'images_url': '/r/0/',  # '0' is replaced by the open project's id
        'embed': bool(request.GET.get('embed')),
    })


@login_required
@require_GET
def api_devices(request):
    return JsonResponse(_apps(request).all_devices(), safe=False)


@login_required
@require_GET
def api_device(request, pk):
    apps = _apps(request)
    device = apps.data.record(pk)
    if device is None or device.table_id != apps.devices.pk:
        raise Http404
    return JsonResponse(apps.device_json(device))


@login_required
@require_http_methods(['GET', 'POST'])
def api_projects(request):
    apps = _apps(request, 'viewer' if request.method == 'GET' else 'editor')
    if request.method == 'GET':
        return JsonResponse([apps.project_json(p) for p in apps.data.records(apps.projects)], safe=False)
    data = _body(request)
    if not isinstance(data, dict):
        return HttpResponseBadRequest('Expected a JSON object.')
    try:
        record = apps.save_project(data)
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(apps.project_json(record))


def _project(apps, pk):
    record = apps.data.record(pk)
    if record is None or record.table_id != apps.projects.pk:
        raise Http404
    return record


@login_required
@require_http_methods(['GET', 'DELETE'])
def api_project(request, pk):
    apps = _apps(request, 'viewer' if request.method == 'GET' else 'editor')
    record = _project(apps, pk)
    if request.method == 'DELETE':
        from core import service
        try:
            service.delete_record(record, request.user, apps.data)
        except ValidationError as exc:
            return _error(exc)
        DrawingVersion.objects.filter(record_id=pk).delete()
        return JsonResponse({'deleted': True})
    version = request.GET.get('version')
    if version and not DrawingVersion.objects.filter(record_id=pk, version=version).exists():
        raise Http404
    return JsonResponse(apps.project_json(record, int(version) if version else None))


@login_required
def api_project_versions(request, pk):
    apps = _apps(request)
    _project(apps, pk)
    return JsonResponse({'versions': sorted(DrawingVersion.objects.filter(record_id=pk).values_list('version', flat=True))})


@login_required
@require_http_methods(['POST'])
def api_project_activate(request, pk, version):
    apps = _apps(request, 'editor')
    record = _project(apps, pk)
    if not DrawingVersion.objects.filter(record_id=pk, version=version).exists():
        return JsonResponse({'error': 'version not found'}, status=404)
    try:
        record = apps.activate(record, version)
    except ValidationError as exc:
        return _error(exc)
    return JsonResponse(apps.project_json(record))


@login_required
@require_http_methods(['GET', 'POST'])
def api_signal_rules(request):
    apps = _apps(request, 'viewer' if request.method == 'GET' else 'editor')
    if request.method == 'POST':
        data = _body(request)
        if not isinstance(data, dict) or not isinstance(data.get('pairs', []), list):
            return HttpResponseBadRequest('Expected {"pairs": [[a, b], ...]}.')
        try:
            apps.replace_rules(p for p in data.get('pairs', []) if isinstance(p, list) and len(p) == 2)
        except ValidationError as exc:
            return _error(exc)
        apps.data.invalidate()
    return JsonResponse({'pairs': apps.rule_pairs()})


@login_required
def api_users(request):
    users = get_user_model().objects.filter(is_active=True)
    return JsonResponse({'users': [{'id': str(u.pk), 'name': str(u)} for u in users]})


@login_required
@require_http_methods(['POST'])
def api_extension(request):
    apps = _apps(request, 'editor')
    data = _body(request) or {}
    device = apps.data.record(data.get('device_id') or 0)
    if device is None or device.table_id != apps.devices.pk:
        return JsonResponse({'error': 'That device no longer exists.'}, status=404)
    try:
        ext = apps.make_extension(device, data.get('connector_id') or '')
    except ValidationError as exc:
        return _error(exc, 404)
    return JsonResponse(apps.device_json(ext))


@login_required
@require_GET
def api_parts(request):
    return JsonResponse({'parts': _apps(request).part_list()})


@login_required
@require_http_methods(['POST'])
def api_order(request):
    apps = _apps(request, 'editor')
    data = _body(request) or {}
    try:
        return JsonResponse(apps.draft_order(data.get('lines'), data.get('note')))
    except ValidationError as exc:
        return _error(exc)
