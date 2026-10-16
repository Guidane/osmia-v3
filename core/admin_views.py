"""Administration: app templates, extensions, trees and access tags.

Installing never leaves something half there: what a template or an extension
needs is listed first, and installed with it or not at all. Removing is the
other way round (core.dependencies, core.extensions.in_use): nothing goes
while something still uses it."""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import access, blueprints
from .extensions import all_extensions, in_use, missing, registry, set_enabled, to_install
from .models import App, Table, Tag, TagEvent

admin_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


def _errors(request, exc):
    for m in (exc.messages if isinstance(exc, ValidationError) else [str(exc)]):
        messages.error(request, m)


# -- App templates ----------------------------------------------------------------------

@admin_required
def templates(request):
    catalog = blueprints.available()
    installed = {}
    for app in App.objects.exclude(blueprint=''):
        installed.setdefault(app.blueprint, []).append(app)
    if request.method == 'POST':
        sample = bool(request.POST.get('sample'))
        try:
            if request.FILES.get('file'):
                bp = json.loads(request.FILES['file'].read().decode('utf-8-sig'))
                if not isinstance(bp, dict) or not bp.get('tables'):
                    raise ValidationError('That file is not an app template.')
                name = bp.get('name')
                if bp.get('key') in installed:
                    name = f'{name} (copy)'
                    bp['key'] = f'{bp["key"]}_copy'
                needs = [k for k in bp.get('requires') or [] if k not in blueprints.installed_keys()]
                if needs:
                    names = ', '.join((catalog.get(k) or {}).get('name', k) for k in needs)
                    raise ValidationError(f'{name} needs {names}. Install {"it" if len(needs) == 1 else "them"} first, '
                                          'then the file.')
                app = blueprints.install(bp, user=request.user, sample=sample, name=name)
                messages.success(request, f'{app.name} is installed.')
                return redirect(app)
            keys = [k for k in request.POST.getlist('templates') if k in catalog]
            if not keys:
                messages.error(request, 'Tick the templates to install.')
            else:
                extra = blueprints.needed_for(keys, catalog)
                if extra and not request.POST.get('confirmed'):
                    return render(request, 'core/admin/install_confirm.html', {
                        'keys': keys, 'sample': sample, 'chosen': [catalog[k] for k in keys],
                        'extra': [catalog[k] for k in extra if k in catalog]})
                apps = blueprints.install_many(keys, user=request.user, sample=sample, catalog=catalog)
                messages.success(request, 'Installed ' + ', '.join(a.name for a in apps) + '.' if apps else 'They were already installed.')
                return redirect('core:templates')
        except (ValidationError, ValueError) as exc:
            _errors(request, exc if isinstance(exc, ValidationError) else ValidationError(f'That file can\'t be read: {exc}'))
    rows = []
    for key, bp in catalog.items():
        rows.append({'key': key, 'bp': bp, 'apps': installed.get(key, []),
                     'requires': [catalog.get(r, {}).get('name', r) for r in bp.get('requires') or []],
                     'tables': [t['name'] for t in bp.get('tables') or []],
                     'automations': len(bp.get('automations') or []),
                     'extension': next((e.title for e in registry.extensions.values()
                                        if e.path and str(e.path) in bp.get('_path', '')), '')})
    return render(request, 'core/admin/templates.html', {'rows': rows})


@admin_required
def template_export(request, app_slug):
    app = get_object_or_404(App, slug=app_slug)
    bp = blueprints.export(app, with_records=bool(request.GET.get('records')))
    response = HttpResponse(json.dumps(bp, indent=2, ensure_ascii=False), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{bp["key"]}.json"'
    return response


# -- Extensions -------------------------------------------------------------------------------

def _restart_or_say(request, restart):
    if restart:
        from .restart import request_restart
        request_restart()
        messages.info(request, 'Osmia restarts now (serve.py starts it again by itself).')
    else:
        messages.info(request, 'Restart Osmia for the change to take effect.')


@admin_required
def extensions(request):
    exts = all_extensions()
    for e in exts:
        e.tabs = [p for p in registry.pages if p.extension == e.name]
        e.launch = [a for a in registry.apps if a.extension == e.name]
        e.missing = missing(e)
        e.used_by = in_use(e.name) if e.enabled else []
    return render(request, 'core/admin/extensions.html', {'extensions': exts})


@admin_required
def extension_switch(request, name):
    """Switch an extension on (after listing what it needs and installing it) or off (unless something uses it)."""
    ext = next((e for e in all_extensions() if e.name == name), None)
    if ext is None:
        raise PermissionDenied('There is no such extension.')
    if ext.enabled:
        used = in_use(ext.name)
        if request.method == 'POST':
            if used:
                for line in ['It can\'t be switched off while something uses it:'] + used:
                    messages.error(request, line)
                return redirect('core:extensions')
            set_enabled(ext.name, False)
            messages.success(request, f'{ext.title} is switched off. Everything it stored stays, as ordinary apps and fields.')
            _restart_or_say(request, request.POST.get('restart'))
            return redirect('core:extensions')
        return render(request, 'core/admin/extension_switch.html', {'ext': ext, 'used': used, 'on': False})
    gaps = missing(ext)
    unfixable = [(req, why) for req, why, key in gaps if not key]
    installs = to_install(ext)
    from .extensions import extension_blueprints
    catalog = {**blueprints.available(include_hidden=True), **extension_blueprints(ext)}
    if request.method == 'POST' and not unfixable:
        try:
            with transaction.atomic():
                blueprints.install_many(installs, user=request.user, sample=bool(request.POST.get('sample')), catalog=catalog)
        except ValidationError as exc:
            _errors(request, exc)
            return redirect('core:extension_switch', ext.name)
        set_enabled(ext.name, True)
        messages.success(request, f'{ext.title} is switched on' + (f', with {", ".join(catalog[k].get("name", k) for k in installs)}.' if installs else '.'))
        _restart_or_say(request, request.POST.get('restart'))
        return redirect('core:extensions')
    return render(request, 'core/admin/extension_switch.html', {
        'ext': ext, 'on': True, 'gaps': gaps, 'unfixable': unfixable,
        'installs': [catalog[k] for k in installs if k in catalog]})


# -- Trees and spaces -----------------------------------------------------------------------------

@admin_required
def trees(request):
    """Every table that is a tree (or could be one), and which are trees of spaces."""
    from .space import home_field
    rows = []
    for table in Table.objects.select_related('app', 'tree_field'):
        self_links = [f for f in table.fields.filter(type='link') if f.opt('target') == table.pk and not f.opt('multiple')]
        if table.tree_field_id or self_links:
            rows.append({'table': table, 'home': home_field(table) if table.is_space else None, 'can_be': bool(self_links)})
    return render(request, 'core/admin/trees.html', {'rows': rows})


# -- Access tags ------------------------------------------------------------------------------------

def _may_make_tags(user):
    return user.is_superuser or user.owned_tags.exists()


@login_required
def tags(request):
    """The tags someone holds and owns. Administrators and tag owners make new tags."""
    if request.method == 'POST':
        if not _may_make_tags(request.user):
            raise PermissionDenied('Administrators and tag owners make access tags.')
        try:
            tag = access.create_tag(request.POST.get('name', ''), request.user, color=request.POST.get('color', ''),
                                    description=request.POST.get('description', ''))
        except ValidationError as exc:
            _errors(request, exc)
            return redirect('core:tags')
        messages.success(request, f'The tag {tag.name} is made. You own it and hold it; give it to the people who need it.')
        return redirect('core:tag', tag.pk)
    mine = access.user_tags(request.user)
    rows = [{'tag': t, 'holds': t.pk in mine, 'owns': t.owners.filter(pk=request.user.pk).exists(),
             'members': t.members.count()} for t in Tag.objects.prefetch_related('owners')]
    return render(request, 'core/admin/tags.html', {'rows': rows, 'can_make': _may_make_tags(request.user)})


@login_required
def tag_detail(request, pk):
    tag = get_object_or_404(Tag, pk=pk)
    owner = access.is_owner(request.user, tag)
    User = get_user_model()
    if request.method == 'POST':
        if not owner:
            raise PermissionDenied(f'Only the owners of {tag.name} can change who holds it.')
        person = User.objects.filter(pk=request.POST.get('user') or 0).first()
        action = request.POST.get('action')
        try:
            if action == 'details':
                tag.description = request.POST.get('description', '')[:300]
                tag.color = request.POST.get('color') or tag.color
                tag.save(update_fields=['description', 'color'])
            elif person is None:
                raise ValidationError('Pick someone.')
            elif action == 'grant':
                access.grant(tag, person, request.user)
            elif action == 'revoke':
                access.revoke(tag, person, request.user)
            elif action == 'owner':
                access.add_owner(tag, person, request.user)
            elif action == 'not_owner':
                access.remove_owner(tag, person, request.user)
        except ValidationError as exc:
            _errors(request, exc)
        else:
            messages.success(request, 'Saved. The other owners are told.' if action != 'details' else 'Saved.')
        return redirect('core:tag', tag.pk)
    return render(request, 'core/admin/tag.html', {
        'tag': tag, 'owner': owner, 'owners': tag.owners.all(), 'members': tag.members.all(),
        'people': User.objects.filter(is_active=True).order_by('username'),
        'events': TagEvent.objects.filter(tag=tag).select_related('user', 'by')[:100] if owner else [],
    })
