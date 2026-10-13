"""The pages people use every day: apps, views, records, files and setup."""
import csv
import io
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login, password_validation
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from . import blueprints, filters, service
from .data import Data
from .extensions import registry
from .fieldtypes import TYPES
from .models import App, Attachment, Automation, AutomationRun, Change, Comment, Field, Notification, Record, Table, View
from .permissions import can, require, visible_apps
from .viewtypes import VIEW_TYPES, get_view_type, query, toolbar_state


# -- Helpers -------------------------------------------------------------------------

def get_table(request, app_slug, table_slug, needed='viewer'):
    app = get_object_or_404(App, slug=app_slug)
    require(request.user, app, needed)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    return app, table


def record_or_404(request, pk, needed='viewer'):
    record = get_object_or_404(Record.objects.select_related('table__app'), pk=pk)
    require(request.user, record.table.app, needed)
    return record


def cell(data, record, field):
    return {'field': field, 'html': data.html(record, field), 'raw': json.dumps(data.raw(record, field), default=str)}


def fields_meta(data, tables):
    """What the cell editors need to know about the fields of ``tables``."""
    meta = {}
    for table in tables:
        for f in data.fields(table):
            item = {'key': f.key, 'name': f.name, 'type': f.type, 'editor': f.kind.editor, 'editable': f.editable,
                    'table': table.pk, 'required': f.required}
            if f.type in ('select', 'multiselect'):
                item['choices'] = f.opt('choices') or []
            if f.type in ('link', 'user'):
                item['multiple'] = bool(f.opt('multiple'))
            if f.type == 'link':
                target = data.table(f.opt('target'))
                item['target'] = f.opt('target')
                item['target_name'] = target.name if target else ''
            if f.type == 'rating':
                item['max'] = int(f.opt('max', 5))
            meta[f.pk] = item
    return meta


def form_items(request, fields, data, preset=None):
    """Each field of a form with what to show in it: what was sent, ?f_<id>= in
    the address, a preset link, or the field's default."""
    items = []
    posted = request.POST if request.method == 'POST' else None
    for f in fields:
        name = f'f_{f.pk}'
        value, values = None, []
        if posted is not None:
            value, values = posted.get(name), posted.getlist(name)
        elif name in request.GET:
            value, values = request.GET.get(name), request.GET.getlist(name)
        elif preset and f.pk in preset:
            values = list(preset[f.pk])
        elif f.kind.stored:
            default = f.kind.default(f)
            if isinstance(default, list):
                values = default
            else:
                value = default
                values = [default] if default not in (None, '') else []
        linked = []
        if f.type == 'link':
            ids = [int(v) for v in values if str(v).isdigit()]
            linked = [{'id': r.pk, 'name': data.label(r)} for r in data.records_by_ids(ids)]
        if f.type == 'user':
            values = [int(v) for v in values if str(v).isdigit()]
        items.append({'f': f, 'pk': f.pk, 'name': name, 'value': value, 'values': values, 'json': json.dumps(linked)})
    return items


def users_meta(data):
    return [{'id': u.pk, 'name': str(u)} for u in data.users().values() if u.is_active]


def sidebar(app, user):
    from . import space as spaces
    from .permissions import can_space
    out = {'app': app, 'tables': list(app.tables.prefetch_related('views')), 'can_build': can(user, app, 'creator'),
           'can_edit': can(user, app, 'editor'), 'app_pages': registry.pages_for_app(app), 'space': app.space}
    if app.space is not None:
        own, added = spaces.space_apps(app.space)
        out.update({'space_own_apps': [a for a in own if can(user, a, 'viewer')],
                    'space_added_apps': [a for a in added if can(user, a, 'viewer')],
                    'space_nav': registry.nav_for_space(None, app.space),
                    'can_admin_space': can_space(user, app.space, 'admin')})
    return out


# -- Setup ----------------------------------------------------------------------------

def setup(request):
    User = get_user_model()
    if User.objects.filter(is_superuser=True).exists():
        return redirect('core:home')
    catalog = blueprints.available()
    errors, values = [], {}
    if request.method == 'POST':
        values = request.POST
        username = values.get('username', '').strip()
        p1, p2 = values.get('password1', ''), values.get('password2', '')
        if not username:
            errors.append('Choose a user name.')
        if p1 != p2:
            errors.append('The two passwords are not the same.')
        candidate = User(username=username, email=values.get('email', '').strip(),
                         first_name=values.get('first_name', '').strip(), last_name=values.get('last_name', '').strip())
        if not errors:
            try:
                password_validation.validate_password(p1, candidate)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if not errors:
            with transaction.atomic():
                candidate.is_superuser = candidate.is_staff = True
                candidate.set_password(p1)
                candidate.save()
                if values.get('demo_users'):
                    for name, first, last, title in [('alice', 'Alice', 'Martin', 'Engineer'),
                                                     ('bob', 'Bob', 'Jansen', 'Warehouse'),
                                                     ('carla', 'Carla', 'Rossi', 'Purchasing')]:
                        u = User(username=name, first_name=first, last_name=last, job_title=title)
                        u.set_password('demo')
                        u.save()
                keys = [k for k in values.getlist('templates') if k in catalog]
                try:
                    blueprints.install_many(keys, user=candidate, sample=bool(values.get('sample')))
                except ValidationError as exc:
                    errors.extend(exc.messages)
                    transaction.set_rollback(True)
            if not errors:
                from . import middleware
                middleware._ready = True
                login(request, candidate, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Osmia is ready. Make an app, or open one of the templates you installed.')
                return redirect('core:home')
    return render(request, 'core/setup.html', {'catalog': catalog, 'errors': errors, 'values': values})


# -- Home and apps ------------------------------------------------------------------------

@login_required
def home(request):
    """Your home is your personal space: your work across the apps (like Jira's
    "Your work"), your to-dos and bookmarks, your spaces and your apps; you
    choose which of these show in the space's settings."""
    from django.utils import timezone

    from . import space as spaces
    from .permissions import role, visible_spaces
    data = Data(request.user)
    personal = spaces.widgets(request.user, data)
    shown = spaces.home_sections(personal['personal'])
    apps = visible_apps(request.user)
    mine, others = [], []
    if 'apps' in shown:
        for app in apps:
            if app.is_space:
                continue
            card = {'app': app, 'tables': list(app.tables.all()), 'records': Record.objects.filter(table__app=app).count(),
                    'role': role(request.user, app)}
            (mine if app.space_id == personal['personal'].pk else others).append(card)
    hour = timezone.localtime().hour
    greeting = 'Good morning' if hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'
    assigned = spaces.assigned(request.user, data, apps) if 'work' in shown else []
    extra = []
    for key in shown:
        if key in registry.home_sections:
            panel = registry.home_sections[key][1](request)
            if panel is not None:
                extra.append(panel)
    return render(request, 'core/home.html', {
        'shown': shown, 'mine': mine, 'cards': others, 'greeting': greeting,
        'tab': request.GET.get('tab') or ('assigned' if assigned else 'recent'),
        'assigned': assigned, 'recent': spaces.recent(request.user, data) if 'work' in shown else [],
        'starred': spaces.starred(request.user, data) if 'work' in shown else [],
        'spaces': [s for s in visible_spaces(request.user) if not s.is_personal] if 'spaces' in shown else [],
        'notifications': Notification.objects.filter(user=request.user, read=False)[:6] if 'notifications' in shown else [],
        'extra_sections': extra,
        'personal_nav': registry.nav_for_space(request, personal['personal']),
        **personal,
    })


@login_required
@require_POST
def record_star(request, pk):
    """Star a record, or unstar it."""
    from .models import Star
    record = record_or_404(request, pk)
    star, created = Star.objects.get_or_create(user=request.user, record=record)
    if not created:
        star.delete()
    if request.headers.get('x-requested-with') == 'fetch':
        from django.http import JsonResponse
        return JsonResponse({'starred': created})
    return redirect(request.POST.get('next') or record.get_absolute_url())


@login_required
def app_page(request, app_slug):
    app = get_object_or_404(App, slug=app_slug)
    require(request.user, app, 'viewer')
    table = app.tables.first()
    if table is not None:
        return redirect(table)
    return render(request, 'core/app_empty.html', {**sidebar(app, request.user)})


@login_required
def table_page(request, app_slug, table_slug):
    app, table = get_table(request, app_slug, table_slug)
    view = table.views.first() or View.objects.create(table=table, name=f'All {table.name.lower()}', type='grid')
    return redirect(view)


@login_required
def view_page(request, app_slug, table_slug, view_id):
    app, table = get_table(request, app_slug, table_slug)
    view = get_object_or_404(View, pk=view_id, table=table)
    data = Data(request.user)
    vt = get_view_type(view.type)
    state = toolbar_state(request, view)
    can_edit = can(request.user, app, 'editor')
    context = {**sidebar(app, request.user), 'table': table, 'view': view, 'vt': vt, 'state': state,
               'views': list(table.views.all()), 'fields': data.fields(table), 'can_edit_records': can_edit,
               'view_types': VIEW_TYPES, 'data': data, 'cell_editing': can_edit,
               'new_view_types': [(k, t) for k, t in VIEW_TYPES.items() if t.available(table, data)]}
    if request.method == 'POST' and view.type == 'form':
        return form_submit(request, app, table, view, data, context)
    missing = vt.missing(view, data)
    if missing:
        context['missing'] = missing
    else:
        records = query(data, view, state) if vt.uses_records else []
        context['count'] = len(records)
        context.update(vt.context(request, view, data, records, state))
        if view.type == 'form':
            context['items'] = form_items(request, context['form_fields'], data)
            context['all_users'] = get_user_model().objects.filter(is_active=True)
        if view.type == 'detail' and context.get('selected') is not None:
            context.update(record_context(request, context['selected'], data))
    context['meta'] = json.dumps({'fields': fields_meta(data, _related_tables(data, table)), 'users': users_meta(data),
                                  'table': table.pk, 'view': view.pk,
                                  'state': {k: state[k] for k in ('filters', 'sorts', 'group_by')},
                                  'ops': {f.pk: filters.ops_for(f) for f in data.fields(table)},
                                  'config': view.config or {}})
    context['automations'] = Automation.objects.filter(table=table, active=True, trigger='button')
    return render(request, vt.template, context)


def _related_tables(data, table):
    """This table and the tables its link fields point at (for sub-grids on record pages)."""
    tables = [table]
    for f in data.fields(table):
        if f.type == 'link':
            t = data.table(f.opt('target'))
            if t and t not in tables:
                tables.append(t)
    return tables


def form_submit(request, app, table, view, data, context):
    require(request.user, app, 'editor')
    fields = [f for f in data.fields(table) if f.editable and (f.kind.stored or f.type == 'link')]
    shown = (view.config or {}).get('fields')
    if shown:
        fields = [f for f in fields if f.key in shown]
    values, files = _form_values(request, fields)
    try:
        record = service.create_record(table, values, user=request.user, data=data)
        _save_files(request, record, data, user=request.user)
    except ValidationError as exc:
        for m in exc.messages:
            messages.error(request, m)
        context.update(get_view_type('form').context(request, view, data, [], {}))
        context['items'] = form_items(request, context['form_fields'], data)
        context['all_users'] = get_user_model().objects.filter(is_active=True)
        context['meta'] = json.dumps({'fields': fields_meta(data, [table]), 'users': users_meta(data)})
        return render(request, 'core/views/form.html', context)
    messages.success(request, (view.config or {}).get('message') or f'Thank you, {data.label(data.record(record.pk))} is added.')
    return redirect(view)


def _form_values(request, fields):
    values, files = {}, {}
    for f in fields:
        name = f'f_{f.pk}'
        if f.type == 'checkbox':
            values[f.pk] = name in request.POST
        elif f.type in ('multiselect',):
            values[f.pk] = request.POST.getlist(name)
        elif f.type == 'link' or (f.type == 'user' and f.opt('multiple')):
            values[f.pk] = [v for v in request.POST.getlist(name) if v]
        elif f.type == 'attachment':
            continue
        elif name in request.POST:
            values[f.pk] = request.POST.get(name)
    return values, files


def _save_files(request, record, data, user):
    for f in data.fields(record.table_id):
        if f.type == 'attachment':
            for upload in request.FILES.getlist(f'f_{f.pk}'):
                service.add_attachment(record, f, upload, user)


# -- Records ------------------------------------------------------------------------------

def record_context(request, record, data):
    table = data.table(record.table_id)
    app = table.app
    fields = data.fields(table)
    main, sections, files = [], [], []
    for f in fields:
        if f.type == 'link' and f.opt('multiple'):
            target = data.table(f.opt('target'))
            if target is None:
                continue
            inverse = data.field(f.opt('inverse'))
            cols = [tf for tf in data.fields(target) if tf != inverse and tf.type not in ('button',)][:7]
            rows = [{'record': r, 'cells': [cell(data, r, c) for c in cols]} for r in data.linked(record, f)]
            sections.append({'field': f, 'target': target, 'columns': cols, 'rows': rows, 'inverse': inverse,
                             'can_add': can(request.user, target.app, 'editor')})
        elif f.type == 'attachment':
            files.append({'field': f, 'items': data.value(record, f)})
        elif f.type == 'button':
            continue
        else:
            main.append(cell(data, record, f))
    buttons = [{'field': f, 'html': data.html(record, f)} for f in fields if f.type == 'button']
    history = Change.objects.filter(table=table, record_id=record.pk).select_related('user')[:50]
    return {
        'record': record,
        'record_label': data.label(record),
        'record_table': table,
        'record_app': app,
        'main_cells': main,
        'sections': sections,
        'file_fields': files,
        'buttons': buttons,
        'manual_automations': [a for a in Automation.objects.filter(table=table, active=True, trigger='button')
                               if not any(f.opt('automation') == a.pk for f in fields if f.type == 'button')],
        'comments': Comment.objects.filter(record=record).select_related('user'),
        'history': history,
        'runs': AutomationRun.objects.filter(record_id=record.pk, automation__table=table).select_related('automation')[:10],
        'panels': registry.panels_for(request, record, table, data),
        'can_edit_record': can(request.user, app, 'editor'),
    }


@login_required
def record_page(request, pk):
    from . import space
    from .models import Star
    record = record_or_404(request, pk)
    space.seen(request.user, record)
    data = Data(request.user)
    record = data.record(record.pk)
    table = data.table(record.table_id)
    context = {**sidebar(table.app, request.user), 'table': table, 'cell_editing': can(request.user, table.app, 'editor'),
               **record_context(request, record, data)}
    context['meta'] = json.dumps({'fields': fields_meta(data, _related_tables(data, table)), 'users': users_meta(data),
                                  'table': table.pk})
    context['starred'] = Star.objects.filter(user=request.user, record=record).exists()
    records = [r.pk for r in data.records(table)]
    i = records.index(record.pk)
    context['prev_id'] = records[i - 1] if i > 0 else None
    context['next_id'] = records[i + 1] if i + 1 < len(records) else None
    return render(request, 'core/record.html', context)


@login_required
def record_new(request, app_slug, table_slug):
    app, table = get_table(request, app_slug, table_slug, 'editor')
    data = Data(request.user)
    fields = [f for f in data.fields(table) if f.editable and (f.kind.stored or f.type in ('link', 'attachment'))]
    preset = {}
    link_field = request.GET.get('link_field') or request.POST.get('link_field')
    link_to = request.GET.get('link_to') or request.POST.get('link_to')
    if link_field and link_to and link_field.isdigit() and link_to.isdigit():
        preset[int(link_field)] = [int(link_to)]
    if request.method == 'POST':
        values, _ = _form_values(request, fields)
        for k, v in preset.items():
            values.setdefault(k, v)
        try:
            with transaction.atomic():
                record = service.create_record(table, values, user=request.user, data=data)
                _save_files(request, record, data, request.user)
        except ValidationError as exc:
            for m in exc.messages:
                messages.error(request, m)
        else:
            messages.success(request, f'{data.label(data.record(record.pk))} is added.')
            back = request.POST.get('next')
            if 'add_another' in request.POST:
                return redirect(request.get_full_path())
            return redirect(back if back and back.startswith('/') else record.get_absolute_url())
    return render(request, 'core/record_new.html', {
        **sidebar(app, request.user), 'table': table, 'items': form_items(request, fields, data, preset),
        'all_users': get_user_model().objects.filter(is_active=True), 'next': request.GET.get('next', '') or request.POST.get('next', ''),
        'link_field': link_field or '', 'link_to': link_to or '',
        'meta': json.dumps({'fields': fields_meta(data, [table]), 'users': users_meta(data)}),
    })


@login_required
@require_POST
def record_delete(request, pk):
    record = record_or_404(request, pk, 'editor')
    table = record.table
    data = Data(request.user)
    label = data.label(data.record(record.pk))
    try:
        service.delete_record(record, request.user, data)
    except ValidationError as exc:
        for m in exc.messages:
            messages.error(request, m)
        return redirect(record)
    messages.success(request, f'{label} is deleted.')
    back = request.POST.get('next')
    return redirect(back if back and back.startswith('/') else table.get_absolute_url())


@login_required
@require_POST
def record_comment(request, pk):
    record = record_or_404(request, pk, 'editor')
    text = request.POST.get('text', '').strip()
    if text:
        service.add_comment(record, text, request.user)
    return redirect(request.POST.get('next') or record.get_absolute_url())


@login_required
@require_POST
def record_upload(request, pk, field_id):
    record = record_or_404(request, pk, 'editor')
    field = get_object_or_404(Field, pk=field_id, table=record.table, type='attachment')
    added, problems = 0, []
    for upload in request.FILES.getlist('files'):
        try:
            service.add_attachment(record, field, upload, request.user)
            added += 1
        except ValidationError as exc:
            problems.extend(exc.messages)
    if request.headers.get('x-requested-with') == 'fetch':
        from django.http import JsonResponse
        return JsonResponse({'added': added, 'errors': problems}, status=200 if not problems else 400)
    for p in problems:
        messages.error(request, p)
    return redirect(request.POST.get('next') or record.get_absolute_url())


@login_required
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('record__table__app'), pk=pk)
    require(request.user, attachment.record.table.app, 'editor')
    record = attachment.record
    service.remove_attachment(attachment, request.user)
    return redirect(request.POST.get('next') or record.get_absolute_url())


@login_required
def attachment_file(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('record__table__app'), pk=pk)
    require(request.user, attachment.record.table.app, 'viewer')
    if request.GET.get('thumb') and attachment.is_image:
        from .uploads import thumbnail_path
        try:
            return FileResponse(open(thumbnail_path(attachment), 'rb'), content_type='image/jpeg')
        except Exception:
            pass
    try:
        handle = attachment.file.open('rb')
    except FileNotFoundError:
        raise Http404('The file is missing.')
    inline = attachment.is_image or attachment.content_type == 'application/pdf'
    return FileResponse(handle, content_type=attachment.content_type or 'application/octet-stream',
                        as_attachment=not inline or bool(request.GET.get('download')), filename=attachment.name)


# -- Notifications --------------------------------------------------------------------------

@login_required
def notifications(request):
    if request.method == 'POST':
        Notification.objects.filter(user=request.user, read=False).update(read=True)
        return redirect('core:notifications')
    items = Notification.objects.filter(user=request.user)[:200]
    return render(request, 'core/notifications.html', {'items': items})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    note.read = True
    note.save(update_fields=['read'])
    return redirect(note.url or 'core:notifications')


# -- CSV ------------------------------------------------------------------------------------

@login_required
def table_csv(request, app_slug, table_slug):
    app, table = get_table(request, app_slug, table_slug)
    data = Data(request.user)
    view = View.objects.filter(pk=request.GET.get('view'), table=table).first()
    records = query(data, view, toolbar_state(request, view)) if view else data.records(table)
    fields = [f for f in data.fields(table) if f.type != 'button']
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f.name for f in fields])
    for r in records:
        writer.writerow([data.text(r, f) for f in fields])
    response = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{table.slug}.csv"'
    return response


@login_required
def table_import(request, app_slug, table_slug):
    """Add records from a CSV file whose header names the fields."""
    app, table = get_table(request, app_slug, table_slug, 'editor')
    data = Data(request.user)
    report = None
    if request.method == 'POST' and request.FILES.get('file'):
        raw = request.FILES['file'].read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
        rows = list(csv.reader(io.StringIO(text), delimiter=';' if text.split('\n', 1)[0].count(';') > text.split('\n', 1)[0].count(',') else ','))
        if not rows:
            messages.error(request, 'The file is empty.')
            return redirect(request.path)
        header = rows[0]
        columns = [data.field_named(table, h) for h in header]
        added, errors = 0, []
        run_automations = bool(request.POST.get('automations'))
        for n, row in enumerate(rows[1:], start=2):
            if not any(c.strip() for c in row):
                continue
            values = {}
            for field, value in zip(columns, row):
                if field is None or not field.editable or not (field.kind.stored or field.type == 'link'):
                    continue
                if field.type == 'link':
                    values[field.pk] = [v.strip() for v in value.split(',') if v.strip()] if field.opt('multiple') else (value.strip() or None)
                    if values[field.pk] is None:
                        values[field.pk] = []
                    elif not isinstance(values[field.pk], list):
                        values[field.pk] = [values[field.pk]]
                elif field.type == 'multiselect':
                    values[field.pk] = [v.strip() for v in value.split(',') if v.strip()]
                else:
                    values[field.pk] = value
            try:
                with transaction.atomic():
                    service.create_record(table, values, user=request.user, data=data, run_automations=run_automations)
                added += 1
            except ValidationError as exc:
                errors.append(f'Row {n}: {" ".join(exc.messages)}')
        report = {'added': added, 'errors': errors[:50], 'skipped': [h for h, c in zip(header, columns) if c is None]}
    return render(request, 'core/table_import.html', {**sidebar(app, request.user), 'table': table, 'report': report,
                                                      'fields': data.fields(table)})


# -- Search -----------------------------------------------------------------------------------

@login_required
def search(request):
    q = request.GET.get('q', '').strip()
    results = []
    if q:
        data = Data(request.user)
        for app in visible_apps(request.user):
            for table in app.tables.all():
                found = data.search(table, q, limit=8)
                if found:
                    results.append({'table': table, 'records': [(r, data.label(r)) for r in found]})
    more = [r for r in (fn(request, q) for fn in registry.searches) if r] if q else []
    return render(request, 'core/search.html', {'q': q, 'results': results, 'more': more})
