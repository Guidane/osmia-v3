"""Spaces: the list, making one, a space's overview and its settings."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from . import space as spaces
from .data import Data
from .extensions import registry
from .fieldtypes import COLORS
from .models import App, Record, Space, SpaceApp, SpaceLink, SpaceMember
from .permissions import can, can_make_spaces, can_space, require_space, space_role, visible_apps, visible_spaces


def get_space(request, key, needed='viewer'):
    space = get_object_or_404(Space, key__iexact=key)
    require_space(request.user, space, needed)
    return space


def space_sidebar(request, space):
    """What the sidebar shows inside a space: its pages (extensions), its apps, its settings."""
    own, added = spaces.space_apps(space)
    return {
        'space': space,
        'space_role': space_role(request.user, space),
        'space_nav': registry.nav_for_space(request, space),
        'space_own_apps': [a for a in own if can(request.user, a, 'viewer')],
        'space_added_apps': [a for a in added if can(request.user, a, 'viewer')],
        'can_admin_space': can_space(request.user, space, 'admin'),
    }


@login_required
def space_list(request):
    mine = spaces.ensure_personal(request.user)
    member_of = set(SpaceMember.objects.filter(user=request.user).values_list('space_id', flat=True))
    rows = []
    for s in visible_spaces(request.user):
        if s.is_personal and s.owner_id != request.user.pk and s.visibility == Space.Visibility.PRIVATE:
            continue
        rows.append({'s': s, 'member': s.pk in member_of or s.owner_id == request.user.pk, 'role': space_role(request.user, s),
                     'apps': s.apps.exclude(is_space=True).count()})
    groups = []
    for kind, label in Space.Kind.choices:
        items = [r for r in rows if r['s'].kind == kind]
        if items:
            groups.append({'label': label if kind != Space.Kind.PERSONAL else 'Personal spaces', 'rows': items})
    return render(request, 'core/spaces/list.html', {'groups': groups, 'personal': mine,
                                                     'can_make': can_make_spaces(request.user)})


@login_required
def space_create(request):
    if not can_make_spaces(request.user):
        raise PermissionDenied('Making spaces needs the "Can make spaces" permission; ask an administrator.')
    values = request.POST if request.method == 'POST' else {}
    if request.method == 'POST':
        name = values.get('name', '').strip()
        key = values.get('key', '').strip().upper()
        if not name:
            messages.error(request, 'Give the space a name.')
        elif key and (not key.replace('_', '').isalnum() or len(key) > 20):
            messages.error(request, 'A key is letters and digits only, at most 20, e.g. ENG.')
        else:
            try:
                with transaction.atomic():
                    space = spaces.create_space(name, request.user, key=key, kind=values.get('kind', 'team'),
                                                visibility=values.get('visibility', 'internal'),
                                                description=values.get('description', ''), icon=values.get('icon', '').strip(),
                                                color=values.get('color', ''))
                    for app in App.objects.filter(pk__in=[int(x) for x in request.POST.getlist('apps') if x.isdigit()]):
                        if can(request.user, app, 'viewer'):
                            SpaceApp.objects.create(space=space, app=app)
            except IntegrityError:
                messages.error(request, f'The key {key} is taken; pick another.')
            else:
                messages.success(request, f'The space {space.name} is made. Add members, apps and pages.')
                return redirect(space)
    shareable = [a for a in visible_apps(request.user) if a.space and not a.space.is_personal and not a.is_space]
    return render(request, 'core/spaces/form.html', {'values': values, 'kinds': [k for k in Space.Kind.choices if k[0] != 'personal'],
                                                     'visibilities': Space.Visibility.choices, 'colors': COLORS[8:],
                                                     'shareable': shareable})


@login_required
def space_overview(request, space_key):
    space = get_space(request, space_key)
    if space.is_personal and space.owner_id == request.user.pk:
        return redirect('core:home')
    data = Data(request.user)
    links = [{'label': l.label, 'record': l.record, 'title': data.label(data.record(l.record_id)), 'table': l.record.table}
             for l in space.links.select_related('record__table__app__space')
             if can(request.user, l.record.table.app, 'viewer')]
    members = list(space.members.select_related('user', 'group'))
    return render(request, 'core/spaces/overview.html', {
        **space_sidebar(request, space), 'links': links, 'members': members,
        'sections': registry.sections_for_space(request, space),
    })


@login_required
def space_settings(request, space_key):
    space = get_space(request, space_key, 'admin')
    data = Data(request.user)
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        if action == 'delete':
            if space.is_personal:
                messages.error(request, 'Your personal space stays.')
            elif request.POST.get('confirm', '').strip() != space.name:
                messages.error(request, f'Type the space\'s name, {space.name}, to delete it.')
            else:
                with transaction.atomic():
                    from .blueprints import company_space
                    target = company_space() if space.kind != Space.Kind.COMPANY else None
                    if request.POST.get('apps') == 'delete' or target is None:
                        from . import schema
                        for app in space.apps.all():
                            for table in list(app.tables.all()):
                                schema.delete_table(table)
                            app.delete()
                    else:
                        space.apps.update(space=target)
                    space.delete()
                messages.success(request, f'The space {space.name} is deleted.')
                return redirect('core:spaces')
            return redirect('core:space_settings', space.key)
        if action == 'save':
            space.name = request.POST.get('name', '').strip() or space.name
            space.icon = request.POST.get('icon', '').strip() or space.icon
            space.color = request.POST.get('color') or space.color
            space.description = request.POST.get('description', '')
            if request.POST.get('visibility') in Space.Visibility.values:
                space.visibility = request.POST['visibility']
            if not space.is_personal and request.POST.get('kind') in Space.Kind.values and request.POST['kind'] != 'personal':
                space.kind = request.POST['kind']
            if space.is_personal:
                order = [k for k in request.POST.getlist('home') if k in dict(spaces.HOME_SECTIONS) or k in registry.home_sections]
                space.config = {**(space.config or {}), 'home': order}
            space.save()
            if not space.is_personal:
                SpaceMember.objects.filter(space=space).delete()
                for kind in ('user', 'group'):
                    for name, value in request.POST.items():
                        if name.startswith(f'{kind}_') and value in Space.Role.values:
                            SpaceMember.objects.create(space=space, role=value, **{f'{kind}_id': int(name.split('_', 1)[1])})
                if not space.members.filter(role=Space.Role.ADMIN).exists() and not request.user.is_superuser:
                    SpaceMember.objects.create(space=space, user=request.user, role=Space.Role.ADMIN)
                    messages.warning(request, 'A space needs an admin, so you stay one.')
            # apps from other spaces
            wanted = {int(x) for x in request.POST.getlist('shortcuts') if x.isdigit()}
            SpaceApp.objects.filter(space=space).exclude(app_id__in=wanted).delete()
            have = set(SpaceApp.objects.filter(space=space).values_list('app_id', flat=True))
            for app in App.objects.filter(pk__in=wanted - have):
                if can(request.user, app, 'viewer') and app.space_id != space.pk:
                    SpaceApp.objects.create(space=space, app=app)
            messages.success(request, f'{space.name} is saved.')
        if action == 'add_link':
            label = request.POST.get('label', '').strip()
            record = Record.objects.filter(pk=request.POST.get('record') or 0).select_related('table__app').first()
            if label and record is not None and can(request.user, record.table.app, 'viewer'):
                SpaceLink.objects.create(space=space, label=label[:60], record=record, position=space.links.count())
                messages.success(request, f'Linked {label}: {data.label(record)}.')
            else:
                messages.error(request, 'Give a label and pick a record.')
        if action == 'remove_link':
            SpaceLink.objects.filter(space=space, pk=request.POST.get('link') or 0).delete()
        return redirect('core:space_settings', space.key)
    roles = {('user', m.user_id): m.role for m in space.members.filter(user__isnull=False)}
    roles.update({('group', m.group_id): m.role for m in space.members.filter(group__isnull=False)})
    users = [(u, roles.get(('user', u.pk), '')) for u in get_user_model().objects.filter(is_active=True)]
    teams = [(g, roles.get(('group', g.pk), '')) for g in Group.objects.order_by('name')]
    added = set(space.shortcuts.values_list('app_id', flat=True))
    shareable = [(a, a.pk in added) for a in visible_apps(request.user)
                 if a.space_id != space.pk and not a.is_space and not (a.space and a.space.is_personal and a.space.owner_id != request.user.pk)]
    links = [{'l': l, 'title': data.label(data.record(l.record_id))} for l in space.links.select_related('record__table')]
    home = spaces.home_sections(space) if space.is_personal else []
    section_labels = dict(spaces.HOME_SECTIONS)
    section_labels.update({k: v[0] for k, v in registry.home_sections.items()})
    ordered = home + [k for k in section_labels if k not in home]
    return render(request, 'core/spaces/settings.html', {
        **space_sidebar(request, space), 'users': users, 'teams': teams, 'roles': Space.Role.choices,
        'kinds': [k for k in Space.Kind.choices if k[0] != 'personal'], 'visibilities': Space.Visibility.choices,
        'colors': COLORS[8:], 'shareable': shareable, 'links': links,
        'home_sections': [(k, section_labels[k], k in home) for k in ordered if k in section_labels],
        'link_tables': [t for a in visible_apps(request.user) if not a.is_space for t in a.tables.all()],
    })
