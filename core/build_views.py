"""Building apps: tables, fields, views, automations and who has access.
For creators of an app (and administrators)."""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import automation, filters, formula, schema
from .data import Data
from .fieldtypes import COLORS, ROLLUPS, TYPES, choices_for_form
from .models import App, AppAccess, Automation, AutomationRun, Field, Table, View
from .permissions import RANK, can, can_make_apps, require
from .viewtypes import VIEW_TYPES, get_view_type
from .space_views import app_context


def _app(request, slug, needed='creator'):
    app = get_object_or_404(App, slug=slug)
    require(request.user, app, needed)
    return app


def _errors(request, exc):
    for m in (exc.messages if isinstance(exc, ValidationError) else [str(exc)]):
        messages.error(request, m)


# -- Apps -------------------------------------------------------------------------------

@login_required
def app_create(request):
    """Make an app. Administrators make workspace apps (or their own, with ?own=1);
    everyone else makes their own: they build it, and others see it only if they share it."""
    if not can_make_apps(request.user):
        raise PermissionDenied("You can't make apps.")
    own = not request.user.is_superuser or bool(request.GET.get('own') or request.POST.get('own'))
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Give the app a name.')
        else:
            with transaction.atomic():
                app = schema.create_app(name, request.user, icon=request.POST.get('icon', '').strip() or '▦',
                                        color=request.POST.get('color') or '#2e7d5b',
                                        description=request.POST.get('description', ''),
                                        owner=request.user if own else None,
                                        default_role=App.Role.NONE if own else App.Role.VIEWER)
                first = request.POST.get('table', '').strip()
                if first:
                    table = schema.create_table(app, first)
                    return redirect('core:fields', app.slug, table.slug)
            return redirect(app)
    return render(request, 'core/build/app_form.html', {'colors': COLORS[8:], 'own': own})


@login_required
def app_settings(request, app_slug):
    app = _app(request, app_slug)
    if request.method == 'POST':
        if 'delete' in request.POST:
            if not (request.user.is_superuser or app.owner_id == request.user.pk):
                messages.error(request, "Only administrators and the app's owner can delete it.")
                return redirect('core:app_settings', app.slug)
            if request.POST.get('confirm', '').strip() != app.name:
                messages.error(request, f"Type the app's name, {app.name}, to delete it.")
                return redirect('core:app_settings', app.slug)
            try:
                schema.delete_app(app)
            except ValidationError as exc:
                _errors(request, exc)
                return redirect('core:app_settings', app.slug)
            messages.success(request, f'{app.name} and all its records are deleted.')
            return redirect('core:home')
        app.name = request.POST.get('name', '').strip() or app.name
        app.icon = request.POST.get('icon', '').strip() or app.icon
        app.color = request.POST.get('color') or app.color
        app.description = request.POST.get('description', '')
        if request.user.is_superuser:
            role = request.POST.get('default_role')
            if role in App.Role.values:
                app.default_role = role
            try:
                app.position = int(request.POST.get('position') or app.position)
            except ValueError:
                pass
        elif app.owner_id == request.user.pk:
            # an owner may let everyone look at their app, not change it
            if request.POST.get('default_role') in (App.Role.NONE, App.Role.VIEWER):
                app.default_role = request.POST['default_role']
        app.save()
        if request.user.is_superuser:
            AppAccess.objects.filter(app=app).delete()
            for kind in ('user', 'group'):
                for key, role in request.POST.items():
                    if key.startswith(f'{kind}_') and role in App.Role.values:
                        AppAccess.objects.create(app=app, role=role, **{f'{kind}_id': int(key.split('_', 1)[1])})
        messages.success(request, f'{app.name} is saved.')
        return redirect('core:app_settings', app.slug)
    access = {('user', a.user_id): a.role for a in app.access.filter(user__isnull=False)}
    access.update({('group', a.group_id): a.role for a in app.access.filter(group__isnull=False)})
    users = [(u, access.get(('user', u.pk), '')) for u in get_user_model().objects.filter(is_active=True, is_superuser=False)]
    teams = [(g, access.get(('group', g.pk), '')) for g in Group.objects.order_by('name')]
    from . import dependencies
    return render(request, 'core/build/app_settings.html', {**app_context(app, request.user), 'roles': App.Role.choices,
                                                            'users': users, 'teams': teams, 'colors': COLORS[8:],
                                                            'blockers': dependencies.blockers(dependencies.app_removal(app))})


# -- Tables -----------------------------------------------------------------------------

@login_required
def table_create(request, app_slug):
    app = _app(request, app_slug)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Give the table a name.')
        else:
            table = schema.create_table(app, name, icon=request.POST.get('icon', '').strip(),
                                        primary=request.POST.get('primary', '').strip() or 'Name')
            messages.success(request, f'{table.name} is made. Add its fields.')
            return redirect('core:fields', app.slug, table.slug)
    return render(request, 'core/build/table_form.html', {**app_context(app, request.user)})


@login_required
def table_settings(request, app_slug, table_slug):
    app = _app(request, app_slug)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    if request.method == 'POST':
        if 'delete' in request.POST:
            if request.POST.get('confirm', '').strip() != table.name:
                messages.error(request, f'Type the table\'s name, {table.name}, to delete it.')
                return redirect('core:table_settings', app.slug, table.slug)
            try:
                schema.delete_table(table)
            except ValidationError as exc:
                _errors(request, exc)
                return redirect('core:table_settings', app.slug, table.slug)
            messages.success(request, f'{table.name} and its records are deleted.')
            return redirect(app)
        table.name = request.POST.get('name', '').strip() or table.name
        table.icon = request.POST.get('icon', '').strip()
        table.description = request.POST.get('description', '')
        display = Field.objects.filter(pk=request.POST.get('display_field') or 0, table=table).first()
        table.display_field = display
        table.save()
        try:
            _save_tree(request, table)
        except ValidationError as exc:
            _errors(request, exc)
            return redirect('core:table_settings', app.slug, table.slug)
        order = [int(x) for x in request.POST.getlist('table_order') if x.isdigit()]
        if order:
            schema.reorder(Table, order)
        messages.success(request, f'{table.name} is saved.')
        return redirect('core:table_settings', app.slug, table.slug)
    from . import dependencies
    return render(request, 'core/build/table_settings.html', {
        **app_context(app, request.user), 'table': table, 'fields': table.fields.all(),
        'parent_choices': [f for f in table.fields.filter(type='link') if f.opt('target') == table.pk and not f.opt('multiple')],
        'blockers': dependencies.blockers(dependencies.table_removal(table))})


def _save_tree(request, table):
    """A tree (its parent field) and whether its records are spaces."""
    from . import space as spaces
    from .trees import make_tree
    if 'tree_field' not in request.POST:
        return
    parent = Field.objects.filter(pk=request.POST.get('tree_field') or 0, table=table).first()
    if (parent.pk if parent else None) != table.tree_field_id:
        make_tree(table, parent)
        table.refresh_from_db()
    wanted = bool(request.POST.get('is_space')) and table.tree_field_id is not None
    if wanted != table.is_space:
        spaces.set_space(table, wanted)


# -- Fields -----------------------------------------------------------------------------

@login_required
def fields(request, app_slug, table_slug):
    app = _app(request, app_slug)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    if request.method == 'POST':
        order = [int(x) for x in request.POST.getlist('order') if x.isdigit()]
        schema.reorder(Field, order)
        return redirect('core:fields', app.slug, table.slug)
    data = Data(request.user)
    rows = []
    for f in data.fields(table):
        info = ''
        if f.type == 'link':
            target = data.table(f.opt('target'))
            info = f'→ {target.label if target else "?"}' + (' (many)' if f.opt('multiple') else ' (one)')
        elif f.type in ('lookup', 'rollup'):
            link, target = data.field(f.opt('link')), data.field(f.opt('field'))
            info = f'{ROLLUPS.get(f.opt("func"), "") + " of " if f.type == "rollup" else ""}{link.name if link else "?"}' \
                   f'{" › " + target.name if target else ""}'
        elif f.type == 'formula':
            info = f.opt('expression', '')
        elif f.type in ('select', 'multiselect'):
            info = ', '.join(c['value'] for c in f.opt('choices') or [])
        elif f.type == 'button':
            auto = Automation.objects.filter(pk=f.opt('automation')).first()
            info = f'runs "{auto.name}"' if auto else 'no automation'
        rows.append({'field': f, 'info': info, 'primary': f == data.primary_field(table)})
    return render(request, 'core/build/fields.html', {**app_context(app, request.user), 'table': table, 'rows': rows})


def _options_from_post(post, ftype):
    o = {}

    def num(name):
        v = post.get(name, '').strip()
        return v if v != '' else None
    if ftype in ('number', 'currency', 'percent'):
        for k in ('decimals', 'min', 'max'):
            if num(k) is not None:
                o[k] = num(k)
        if ftype == 'currency':
            o['symbol'] = post.get('symbol', '€') or '€'
    if ftype == 'rating':
        o['max'] = int(post.get('rating_max') or 5)
    if ftype in ('select', 'multiselect'):
        values, colors = post.getlist('choice_value'), post.getlist('choice_color')
        o['choices'] = [{'value': v.strip(), 'color': c} for v, c in zip(values, colors) if v.strip()]
        transitions = {}
        for line in post.get('transitions', '').splitlines():
            if ':' in line:
                src, dst = line.split(':', 1)
                transitions[src.strip()] = [d.strip() for d in dst.split(',') if d.strip()]
        if transitions:
            o['transitions'] = transitions
    if ftype in ('user', 'link'):
        o['multiple'] = bool(post.get('multiple'))
    if ftype == 'user' and post.get('home'):
        o['home'] = True   # whose home space a record of a space table is
    if ftype == 'link' and post.get('access_from') in ('1', '0'):
        o['access_from'] = post.get('access_from') == '1'   # carry the linked records' access tags, or not
    if ftype == 'link':
        o['target'] = int(post.get('target') or 0)
    if ftype in ('lookup', 'rollup'):
        o['link'] = int(post.get('link') or 0)
        o['field'] = int(post.get('target_field') or 0) or None
    if ftype == 'rollup':
        o['func'] = post.get('func', 'sum')
        if post.get('filter', '').strip():
            o['filter'] = post.get('filter').strip()
    if ftype == 'formula':
        o['expression'] = post.get('expression', '').strip()
    if ftype in ('formula', 'rollup'):
        o['format'] = post.get('format', 'auto')
        if num('decimals') is not None:
            o['decimals'] = num('decimals')
        if post.get('format') == 'currency':
            o['symbol'] = post.get('symbol', '€') or '€'
    if ftype == 'autonumber':
        o['prefix'] = post.get('prefix', '')
        o['digits'] = int(post.get('digits') or 1)
    if ftype == 'attachment' and post.get('images_only'):
        o['images_only'] = True
    if ftype == 'button':
        o['label'] = post.get('label', '').strip()
        o['color'] = post.get('btn_color', '')
        o['automation'] = int(post.get('automation') or 0) or None
        if post.get('confirm', '').strip():
            o['confirm'] = post.get('confirm').strip()
    if ftype in ('text', 'longtext', 'email', 'url', 'phone', 'number', 'currency', 'percent', 'select', 'date', 'datetime', 'checkbox'):
        if post.get('default', '').strip():
            o['default'] = post.get('default').strip()
    if TYPES.get(ftype) and TYPES[ftype].stored and TYPES[ftype].editable and post.get('readonly'):
        o['readonly'] = True
    return o


@login_required
def field_edit(request, app_slug, table_slug, field_id=None):
    app = _app(request, app_slug)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    field = get_object_or_404(Field, pk=field_id, table=table) if field_id else None
    if request.method == 'POST':
        if 'delete' in request.POST and field:
            pair = Field.objects.select_related('table__app').filter(pk=field.opt('inverse')).first() if field.type == 'link' else None
            if pair is not None and not can(request.user, pair.table.app, 'creator'):
                messages.error(request, f'Deleting {field.name} would also delete {pair.name} in {pair.table.label}, '
                                        "which you can't change. Ask an administrator.")
                return redirect('core:field_edit', app.slug, table.slug, field.pk)
            try:
                schema.delete_field(field)
            except ValidationError as exc:
                _errors(request, exc)
                return redirect('core:field_edit', app.slug, table.slug, field.pk)
            messages.success(request, f'The field {field.name} is deleted.')
            return redirect('core:fields', app.slug, table.slug)
        ftype = request.POST.get('type') or (field.type if field else 'text')
        options = _options_from_post(request.POST, ftype)
        try:
            if ftype == 'link' and field is None:
                target = Table.objects.select_related('app').filter(pk=options.get('target')).first()
                if target is not None and not can(request.user, target.app, 'creator'):
                    raise ValidationError(f"A link adds a field to {target.label}, and you can't change {target.app.name}. "
                                          'Link to tables of your own apps, or ask an administrator.')
            if field is None:
                field = schema.add_field(table, request.POST.get('name', ''), ftype, options,
                                         required=bool(request.POST.get('required')),
                                         description=request.POST.get('description', ''),
                                         inverse_name=request.POST.get('inverse_name', '').strip() or None,
                                         inverse_multiple=bool(request.POST.get('inverse_multiple')))
                messages.success(request, f'The field {field.name} is added.')
            else:
                before = field.opt('access_from')
                schema.update_field(field, name=request.POST.get('name'), ftype=ftype, options=options,
                                    required=bool(request.POST.get('required')),
                                    description=request.POST.get('description', ''))
                if field.type == 'link' and field.opt('access_from') != before:
                    from .access import refresh_tables
                    refresh_tables([field.table_id, field.opt('target')])
                messages.success(request, f'The field {field.name} is saved.')
            if request.POST.get('make_primary'):
                table.display_field = field
                table.save(update_fields=['display_field'])
            return redirect('core:fields', app.slug, table.slug)
        except ValidationError as exc:
            _errors(request, exc)
    data = Data(request.user)
    all_tables = [t for t in Table.objects.select_related('app') if can(request.user, t.app, 'creator')]
    tables_meta = {t.pk: {'name': t.label, 'fields': [{'id': f.pk, 'name': f.name, 'type': f.type} for f in data.fields(t)]}
                   for t in all_tables}
    links = [{'id': f.pk, 'name': f.name, 'target': f.opt('target')} for f in data.fields(table) if f.type == 'link']
    return render(request, 'core/build/field_form.html', {
        **app_context(app, request.user), 'table': table, 'field': field, 'type_choices': choices_for_form(),
        'types': TYPES, 'all_tables': all_tables, 'colors': COLORS,
        'meta': json.dumps({'tables': tables_meta, 'links': links,
                            'field': {'type': field.type, 'options': field.options} if field else None,
                            'help': {k: t.help for k, t in TYPES.items()}, 'colors': COLORS}),
        'transitions_text': '\n'.join(f'{k}: {", ".join(v)}' for k, v in (field.opt('transitions') or {}).items()) if field else '',
        'automations': Automation.objects.filter(table=table, trigger='button'),
        'rollups': ROLLUPS.items(), 'functions': formula.HELP, 'table_fields': data.fields(table),
        'is_primary': field is not None and field == data.primary_field(table),
    })


# -- Views ------------------------------------------------------------------------------

@login_required
@require_POST
def view_create(request, app_slug, table_slug):
    app = _app(request, app_slug)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    vtype = request.POST.get('type', 'grid')
    if vtype not in VIEW_TYPES:
        vtype = 'grid'
    vt = VIEW_TYPES[vtype]
    name = request.POST.get('name', '').strip() or vt.label
    view = View.objects.create(table=table, name=name, type=vtype, position=table.views.count())
    data = Data(request.user)
    # sensible first settings, so the view shows something straight away
    cfg = {}
    flds = data.fields(table)
    pick = lambda types, same=False: next((f.key for f in flds if f.type in types and (not same or f.opt('target') == table.pk)), None)
    if vtype == 'kanban':
        cfg['group_field'] = pick(('select',)) or pick(('user',)) or pick(('link',))
    elif vtype == 'calendar':
        cfg['date_field'] = pick(('date', 'datetime'))
    elif vtype == 'gantt':
        dates = [f.key for f in flds if f.type in ('date', 'datetime')]
        if dates:
            cfg['start_field'] = dates[0]
            if len(dates) > 1:
                cfg['end_field'] = dates[1]
    elif vtype == 'tree':
        cfg['parent_field'] = pick(('link',), same=True)
    view.config = {k: v for k, v in cfg.items() if v}
    view.save(update_fields=['config'])
    if vt.missing(view, data) or vtype == 'form':
        return redirect('core:view_settings', app.slug, table.slug, view.pk)
    return redirect(view)


@login_required
def view_settings(request, app_slug, table_slug, view_id):
    app = _app(request, app_slug)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    view = get_object_or_404(View, pk=view_id, table=table)
    vt = get_view_type(view.type)
    data = Data(request.user)
    if request.method == 'POST':
        if 'delete' in request.POST:
            try:
                schema.delete_view(view)
            except ValidationError as exc:
                _errors(request, exc)
                return redirect('core:view_settings', app.slug, table.slug, view.pk)
            messages.success(request, f'The view {view.name} is deleted.')
            return redirect(table)
        if 'duplicate' in request.POST:
            copy = View.objects.create(table=table, name=f'{view.name} (copy)', type=view.type, config=view.config,
                                       position=table.views.count())
            return redirect('core:view_settings', app.slug, table.slug, copy.pk)
        view.name = request.POST.get('name', '').strip() or view.name
        cfg = dict(view.config or {})
        for s in vt.settings:
            if s.kind == 'fields':
                keys = [k for k in request.POST.getlist(s.name) if k]
                if keys:
                    cfg[s.name] = keys
                else:
                    cfg.pop(s.name, None)
            else:
                value = request.POST.get(s.name, '').strip()
                if value:
                    cfg[s.name] = value
                else:
                    cfg.pop(s.name, None)
        if 'fields' not in {s.name for s in vt.settings}:
            keys = [k for k in request.POST.getlist('fields') if k]
            if keys:
                cfg['fields'] = keys
            else:
                cfg.pop('fields', None)
        view.config = cfg
        view.save()
        order = [int(x) for x in request.POST.getlist('view_order') if x.isdigit()]
        if order:
            schema.reorder(View, order)
        messages.success(request, f'The view {view.name} is saved.')
        return redirect(view)
    settings = []
    for s in vt.settings:
        options = []
        if s.kind == 'field':
            options = [f for f in data.fields(table) if (not s.types or f.type in s.types)
                       and (not s.same_table_link or f.opt('target') == table.pk)]
        settings.append({'s': s, 'options': options, 'value': (view.config or {}).get(s.name, '')})
    current = (view.config or {}).get('fields') or []
    all_fields = data.fields(table)
    ordered = [f for k in current for f in all_fields if f.key == k] + [f for f in all_fields if f.key not in current]
    return render(request, 'core/build/view_settings.html', {
        **app_context(app, request.user), 'table': table, 'view': view, 'vt': vt, 'settings': settings,
        'ordered_fields': ordered, 'shown': set(current) if current else {f.key for f in all_fields}, 'views': table.views.all(),
    })


# -- Automations ------------------------------------------------------------------------

@login_required
def automation_list(request, app_slug):
    app = _app(request, app_slug)
    data = Data(request.user)
    autos = Automation.objects.filter(table__app=app).select_related('table')
    rows = []
    for a in autos:
        last = a.runs.first()
        rows.append({'a': a, 'trigger': automation.TRIGGERS.get(a.trigger, a.trigger),
                     'conditions': filters.describe(data, a.table, a.conditions),
                     'steps': [automation.ACTIONS[s['type']].label if s.get('type') in automation.ACTIONS
                               else f'{s.get("type")} (not available)' for s in a.actions],
                     'last': last})
    return render(request, 'core/build/automations.html', {**app_context(app, request.user), 'rows': rows})


def builder_meta(app, data, user):
    from django.contrib.auth import get_user_model
    tables = {}
    for t in Table.objects.select_related('app'):
        if not can(user, t.app, 'viewer'):
            continue
        tables[t.pk] = {'id': t.pk, 'name': t.name, 'label': t.label, 'app': t.app_id,
                        'writable': t.app_id == app.pk or can(user, t.app, 'editor'),
                        'fields': [{'id': f.pk, 'key': f.key, 'name': f.name, 'type': f.type,
                                    'editable': f.kind.stored or f.type == 'link',
                                    'target': f.opt('target'), 'multiple': bool(f.opt('multiple')),
                                    'choices': [c['value'] for c in f.opt('choices') or []],
                                    'ops': filters.ops_for(f)} for f in data.fields(t)]}
    return {
        'tables': tables,
        'triggers': automation.TRIGGERS,
        'trigger_help': automation.TRIGGER_HELP,
        'actions': {k: {'label': a.label, 'icon': a.icon, 'help': a.help,
                        'params': [{'name': p.name, 'label': p.label, 'type': p.type, 'required': p.required,
                                    'help': p.help, 'choices': list(p.choices)} for p in a.params]}
                    for k, a in automation.ACTIONS.items()},
        'users': [{'id': u.pk, 'name': str(u)} for u in get_user_model().objects.filter(is_active=True)],
        'teams': [{'id': g.pk, 'name': g.name} for g in Group.objects.order_by('name')],
        'automations': [{'id': a.pk, 'name': a.name, 'table': a.table_id} for a in Automation.objects.all()],
        'all_ops': filters.OPS, 'no_value': sorted(filters.NO_VALUE),
    }


@login_required
def automation_edit(request, app_slug, automation_id=None):
    app = _app(request, app_slug)
    auto = get_object_or_404(Automation, pk=automation_id, table__app=app) if automation_id else None
    data = Data(request.user)
    if request.method == 'POST':
        if 'delete' in request.POST and auto:
            try:
                schema.delete_automation(auto)
            except ValidationError as exc:
                _errors(request, exc)
                return redirect('core:automation_edit', app.slug, auto.pk)
            messages.success(request, f'The automation {auto.name} is deleted.')
            return redirect('core:automations', app.slug)
        try:
            spec = json.loads(request.POST.get('spec') or '{}')
        except ValueError:
            spec = {}
        table = Table.objects.filter(pk=spec.get('table'), app=app).first()
        problems = []
        if table is None:
            problems.append('Pick the table the automation is about.')
        if not (spec.get('name') or '').strip():
            problems.append('Give the automation a name.')
        if spec.get('trigger') not in automation.TRIGGERS:
            problems.append('Pick when it runs.')
        for i, step in enumerate(spec.get('actions') or [], 1):
            act = automation.ACTIONS.get(step.get('type'))
            if act is None:
                problems.append(f'Step {i}: pick what to do.')
                continue
            for p in act.params:
                if p.required and not step.get(p.name):
                    problems.append(f'Step {i} ({act.label}): fill in "{p.label}".')
            for value in _strings(step):
                if value.startswith('='):
                    problem = formula.check(value)
                    if problem:
                        problems.append(f'Step {i}: the formula {value} has a mistake: {problem}')
        if table is not None:
            problems.extend(_write_problems(request.user, app, table, spec.get('actions') or []))
        if (spec.get('conditions') or {}).get('formula'):
            problem = formula.check(spec['conditions']['formula'])
            if problem:
                problems.append(f'The condition formula has a mistake: {problem}')
        if problems:
            for p in problems:
                messages.error(request, p)
        else:
            auto = auto or Automation(table=table)
            old_trigger = auto.trigger if auto.pk else None
            auto.table = table
            auto.name = spec['name'].strip()
            auto.description = spec.get('description', '')
            auto.active = bool(spec.get('active', True))
            auto.trigger = spec['trigger']
            cfg = spec.get('trigger_config') or {}
            if auto.pk and auto.trigger_config.get('last_run'):
                cfg['last_run'] = auto.trigger_config['last_run']
            auto.trigger_config = cfg
            auto.conditions = spec.get('conditions') or {}
            auto.actions = spec.get('actions') or []
            auto.save()
            automation.prime_states(auto)
            messages.success(request, f'The automation {auto.name} is saved.')
            return redirect('core:automation_edit', app.slug, auto.pk)
        initial = spec
    else:
        initial = {'table': auto.table_id, 'name': auto.name, 'description': auto.description, 'active': auto.active,
                   'trigger': auto.trigger, 'trigger_config': auto.trigger_config, 'conditions': auto.conditions,
                   'actions': auto.actions} if auto else {
            'table': int(request.GET.get('table') or 0) or (app.tables.first().pk if app.tables.exists() else None),
            'name': '', 'active': True, 'trigger': 'record_created', 'trigger_config': {},
            'conditions': {'match': 'all', 'rules': []}, 'actions': []}
    return render(request, 'core/build/automation_form.html', {
        **app_context(app, request.user), 'auto': auto, 'app_tables': app.tables.all(),
        'meta': json.dumps(builder_meta(app, data, request.user)), 'initial': json.dumps(initial),
        'runs': auto.runs.select_related('user')[:30] if auto else [],
        'functions': formula.HELP,
    })


def _write_problems(user, app, table, steps):
    """Steps that would change apps the user may only look at."""
    data = Data(user)
    links = {f.key: f for f in data.fields(table) if f.type == 'link'}
    problems = []
    for i, step in enumerate(steps, 1):
        targets = []
        if step.get('type') in ('create_record', 'find_or_create') and step.get('table'):
            targets.append(data.table(step['table']))
        if step.get('type') in ('update_record', 'delete_record'):
            target = step.get('target') or 'this'
            if target.startswith('link:') and not target.startswith('link:item.'):
                link = links.get(target[5:])
                targets.append(data.table(link.opt('target')) if link else None)
            elif target == 'item' and step.get('for_each') in links:
                targets.append(data.table(links[step['for_each']].opt('target')))
        if step.get('type') == 'run_automation':
            other = Automation.objects.select_related('table__app').filter(pk=step.get('automation')).first()
            targets.append(other.table if other else None)
        for t in targets:
            if t is not None and t.app_id != app.pk and not can(user, t.app, 'editor'):
                problems.append(f'Step {i} would change {t.label}; you can only look at {t.app.name}.')
    return problems


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


@login_required
def automation_runs(request, app_slug):
    app = _app(request, app_slug, 'editor')
    runs = AutomationRun.objects.filter(automation__table__app=app).select_related('automation', 'user')
    status = request.GET.get('status')
    if status:
        runs = runs.filter(status=status)
    runs = list(runs[:600])
    from .models import Record
    data = Data(request.user)
    there = set(Record.objects.filter(pk__in={r.record_id for r in runs if r.record_id}).values_list('pk', flat=True))
    shown = [r for r in runs if not r.record_id or r.record_id not in there or data.record(r.record_id) is not None][:300]
    return render(request, 'core/build/runs.html', {**app_context(app, request.user), 'runs': shown, 'status': status})


@login_required
def app_history(request, app_slug):
    from .models import Change
    app = _app(request, app_slug, 'viewer')
    from .access import allows
    changes = Change.objects.filter(table__app=app).select_related('table', 'user')
    table = request.GET.get('table')
    if table and table.isdigit():
        changes = changes.filter(table_id=int(table))
    shown = [c for c in changes[:1000] if allows(request.user, c.access, c.record_id)][:300]
    return render(request, 'core/build/history.html', {**app_context(app, request.user), 'changes': shown,
                                                       'table_filter': table})
