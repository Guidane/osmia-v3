"""Administration: app templates and extensions."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import blueprints
from .extensions import all_extensions, registry, set_enabled
from .models import App

admin_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


@admin_required
def templates(request):
    catalog = blueprints.available()
    installed = {}
    for app in App.objects.exclude(blueprint=''):
        installed.setdefault(app.blueprint, []).append(app)
    from .models import Space
    spaces = list(Space.objects.exclude(kind=Space.Kind.PERSONAL))
    if request.method == 'POST':
        sample = bool(request.POST.get('sample'))
        space = Space.objects.filter(pk=request.POST.get('space') or 0).exclude(kind=Space.Kind.PERSONAL).first()
        try:
            if request.FILES.get('file'):
                bp = json.loads(request.FILES['file'].read().decode('utf-8-sig'))
                if not isinstance(bp, dict) or not bp.get('tables'):
                    raise ValidationError('That file is not an app template.')
                name = bp.get('name')
                if bp.get('key') in installed:
                    name = f'{name} (copy)'
                    bp['key'] = f'{bp["key"]}_copy'
                app = blueprints.install(bp, user=request.user, sample=sample, name=name, space=space)
                messages.success(request, f'{app.name} is installed.')
                return redirect(app)
            keys = request.POST.getlist('templates')
            if not keys:
                messages.error(request, 'Tick the templates to install.')
            else:
                apps = blueprints.install_many(keys, user=request.user, sample=sample, space=space)
                messages.success(request, 'Installed ' + ', '.join(a.name for a in apps) + '.' if apps else 'They were already installed.')
                return redirect('core:templates')
        except (ValidationError, ValueError) as exc:
            for m in (exc.messages if isinstance(exc, ValidationError) else [f'That file can\'t be read: {exc}']):
                messages.error(request, m)
    rows = []
    for key, bp in catalog.items():
        rows.append({'key': key, 'bp': bp, 'apps': installed.get(key, []),
                     'requires': [catalog.get(r, {}).get('name', r) for r in bp.get('requires') or []],
                     'tables': [t['name'] for t in bp.get('tables') or []],
                     'automations': len(bp.get('automations') or []),
                     'extension': next((e.title for e in registry.extensions.values()
                                        if e.path and str(e.path) in bp.get('_path', '')), '')})
    return render(request, 'core/admin/templates.html', {'rows': rows, 'spaces': spaces,
                                                         'company': blueprints.company_space()})


@admin_required
def template_export(request, app_slug):
    app = get_object_or_404(App, slug=app_slug, is_space=False)  # someone's My space stays theirs
    bp = blueprints.export(app, with_records=bool(request.GET.get('records')))
    response = HttpResponse(json.dumps(bp, indent=2, ensure_ascii=False), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{bp["key"]}.json"'
    return response


@admin_required
def extensions(request):
    if request.method == 'POST':
        name = request.POST.get('name', '')
        known = {e.name for e in all_extensions()}
        if name in known:
            set_enabled(name, request.POST.get('enable') == '1')
            messages.success(request, 'Saved. Restart Osmia for the change to take effect '
                                      '(serve.py restarts by itself from this page).')
            if request.POST.get('restart'):
                from .restart import request_restart
                request_restart()
        return redirect('core:extensions')
    exts = all_extensions()
    for e in exts:
        e.pages = [p for p in registry.pages if p.extension == e.name]
    return render(request, 'core/admin/extensions.html', {'extensions': exts})
