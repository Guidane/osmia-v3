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
from django.utils.html import format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import blueprints, filters, service
from .data import Data
from .formula import Records
from .extensions import registry
from .fieldtypes import TYPES
from .models import App, Attachment, Automation, AutomationRun, Change, Comment, Field, Notification, Record, Table, View
from .permissions import can, require, visible_apps
from .space_views import app_context
from .viewtypes import VIEW_TYPES, get_view_type, query, toolbar_state


def local_next(request):
    """Where to go next (?next= or a posted next), if it's a page of this Osmia; '' if not."""
    url = request.POST.get('next') or request.GET.get('next') or ''
    ok = url.startswith('/') and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()})
    return url if ok else ''


# -- Helpers -------------------------------------------------------------------------

def get_table(request, app_slug, table_slug, needed='viewer'):
    app = get_object_or_404(App, slug=app_slug)
    require(request.user, app, needed)
    table = get_object_or_404(Table, app=app, slug=table_slug)
    return app, table


def record_or_404(request, pk, needed='viewer'):
    """The record, if the person may see it (its app, and its access tags); else "not found"."""
    from .access import can_see
    record = get_object_or_404(Record.objects.select_related('table__app'), pk=pk)
    if not can_see(request.user, record):
        raise Http404('There is no such record.')
    require(request.user, record.table.app, needed)
    return record


def sharing_error(request, exc):
    """Someone was put on a record they can't see: say so, and offer to share it with them."""
    from .access import NeedsSharing
    if isinstance(exc, NeedsSharing):
        messages.error(request, exc.messages[0])
        return True
    return False


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
            if f.type == 'attributes':
                item['names'] = f.kind.names(f)
                item['expects'] = f.kind.source(f) is not None   # the editor asks what this record should fill in
            meta[f.pk] = item
    return meta


def copied_values(data, record, fields):
    """A record's values to start a copy with: (preset lists, single values), by field id. Files aren't copied."""
    preset, initial = {}, {}
    for f in fields:
        if f.type == 'attachment':
            continue
        raw = data.raw(record, f)
        if raw in (None, '', []):
            continue
        if f.type in ('link', 'user', 'multiselect'):
            items = raw if isinstance(raw, list) else [raw]
            preset[f.pk] = [i.get('id', i) if isinstance(i, dict) else i for i in items]
        elif f.type == 'attributes':
            initial[f.pk] = '\n'.join(f"{p['name']}: {p['value']}" if p['value'] else p['name'] for p in raw)
        else:
            initial[f.pk] = raw
    return preset, initial


def form_items(request, fields, data, preset=None, initial=None):
    """Each field of a form with what to show in it: what was sent, ?f_<id>= in
    the address, a preset link, a copied value, or the field's default."""
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
        elif initial and f.pk in initial:
            value = initial[f.pk]
            values = [value]
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
        names = json.dumps(f.kind.names(f)) if f.type == 'attributes' else '[]'
        source = f.kind.source(f) if f.type == 'attributes' else None   # e.g. the category lists what to fill in
        items.append({'f': f, 'pk': f.pk, 'name': name, 'value': value, 'values': values, 'json': json.dumps(linked),
                      'names_json': names,
                      'source_json': json.dumps({'link': source[0].pk, 'field': source[1].pk}) if source else ''})
    return items


def users_meta(data):
    return [{'id': u.pk, 'name': str(u)} for u in data.users().values() if u.is_active]


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
                # everyone's home space lives in the Organisation tree, so it always comes
                keys = ['departments'] + [k for k in values.getlist('templates') if k in catalog and k != 'departments']
                try:
                    blueprints.install_many(keys, user=candidate, sample=bool(values.get('sample')))
                except ValidationError as exc:
                    errors.extend(exc.messages)
                    transaction.set_rollback(True)
            if not errors:
                from . import middleware
                middleware._ready = True
                login(request, candidate, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, 'Osmia is ready. This is your home space: type / on its page (✎ Edit page) '
                                          'to put apps, views and blocks on it.')
                return redirect('core:home')
    return render(request, 'core/setup.html', {'catalog': catalog, 'errors': errors, 'values': values})


# -- Records ------------------------------------------------------------------------------

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
    return redirect(local_next(request) or record.get_absolute_url())


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
    context = {**app_context(app, request.user), 'table': table, 'view': view, 'vt': vt, 'state': state,
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
        record = service.create_record(table, values, user=request.user, data=data, share=bool(request.POST.get('share')))
        _save_files(request, record, data, user=request.user)
    except ValidationError as exc:
        if sharing_error(request, exc):
            context['needs_share'] = True
        else:
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
    main, sections, files, notes = [], [], [], []
    for f in fields:
        if f.type == 'link' and f.opt('multiple'):
            target = data.table(f.opt('target'))
            if target is None:
                continue
            inverse = data.field(f.opt('inverse'))
            sections.append(linked_section(request, data, record, f, target, inverse))
        elif f.type == 'attachment':
            files.append({'field': f, 'items': data.value(record, f)})
        elif f.type == 'button':
            continue
        elif f.type == 'longtext':   # notes and the like: a card of their own, beside the rest
            notes.append(cell(data, record, f))
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
        'note_cells': notes,
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
        **access_context(request, record, table),
    }


def linked_section(request, data, record, field, target, inverse):
    """A multiple link's records on a record's page. Its ``show`` option says how: {"fields": [keys], "sort": [keys],
    "group_by": [keys], "group_join": " → "}; without it, the first seven fields in the order they were linked.
    Grouped, each group has a sub-header with the values it shares, and adds a row with them already filled in."""
    show = field.opt('show') or {}
    by_key = {tf.key: tf for tf in data.fields(target) if tf.type != 'button'}
    cols = [by_key[k] for k in show.get('fields') or [] if k in by_key and by_key[k] != inverse]
    if not cols:
        cols = [tf for tf in data.fields(target) if tf != inverse and tf.type not in ('button',)][:7]
    records = data.linked(record, field)
    sort = [by_key[k] for k in show.get('sort') or [] if k in by_key]
    group = [by_key[k] for k in show.get('group_by') or [] if k in by_key]
    for f in reversed(group + sort):
        records = sorted(records, key=lambda r, f=f: f.kind.sort_key(data.value(r, f)))
    # "keep_together": rows with the same value of it (a harness's wires of one set) stay next to each other, where
    # the first of them is, with an outline around them
    together = by_key.get(show.get('keep_together')) if show.get('keep_together') else None
    sets = {}
    if together is not None:
        def bucket(r):
            value = data.text(r, together)
            return (tuple(str(data.value(r, g)) for g in group), value) if value else None
        buckets = {}
        for r in records:
            if bucket(r) is not None:
                buckets.setdefault(bucket(r), []).append(r)
        ordered, placed = [], set()
        for r in records:
            b = bucket(r)
            if b is None:
                ordered.append(r)
            elif b not in placed:
                placed.add(b)
                ordered += buckets[b]
                if len(buckets[b]) > 1:
                    for i, m in enumerate(buckets[b]):
                        sets[m.pk] = 'set-row' + (' set-first' if i == 0 else '') + (' set-last' if i == len(buckets[b]) - 1 else '')
        records = ordered
    rows = [{'record': r, 'cells': [cell(data, r, c) for c in cols], 'set': sets.get(r.pk, '')} for r in records]
    groups = []
    if group:
        new_url = reverse('core:record_new', args=[target.app.slug, target.slug])
        for row in rows:
            r = row['record']
            values = [data.value(r, g) for g in group]
            key = [tuple(v.ids) if isinstance(v, Records) else str(v) for v in values]
            if not groups or groups[-1]['key'] != key:
                presets = ''.join(f'&f_{g.pk}={i}' for g, v in zip(group, values) if isinstance(v, Records) for i in v.ids)
                groups.append({'key': key, 'rows': [], 'presets': presets,
                               'headers': [group_lines(data, v, show['group_lines']) if show.get('group_lines') and isinstance(v, Records)
                                           else data.html(r, g) for g, v in zip(group, values)]})
            groups[-1]['rows'].append(row)
    keys = [c.key for c in cols]
    # "group_columns": {"from": ["a_function", "source_contact"]}: the From connector heads those columns (one key or
    # several next to each other); a value the same as the group above it is left out, so a change stands out
    above = {}
    for i, g in enumerate(group):
        wanted = show.get('group_columns', {}).get(g.key)
        wanted = [wanted] if isinstance(wanted, str) else list(wanted or [])
        at = sorted(keys.index(k) for k in wanted if k in keys)
        if at:
            above[at[0]] = (i, at[-1] - at[0] + 1)
    aligned = bool(above)
    if aligned:
        previous = None
        for g in groups:
            g['cells'], col = [], 0
            while col < len(cols):
                if col in above:
                    i, span = above[col]
                    same = previous is not None and previous['key'][i] == g['key'][i]
                    g['cells'].append({'html': '' if same else g['headers'][i], 'span': span})
                    col += span
                else:
                    g['cells'].append({'html': '', 'span': 1})
                    col += 1
            placed = {i for i, _ in above.values()}
            g['rest'] = [h for i, h in enumerate(g['headers']) if i not in placed]
            previous = g
    # "column_groups": [{"label": "A", "fields": [...]}, ...]: a row above the column names
    bands = []
    if show.get('column_groups'):
        named = {k: b.get('label', '') for b in show['column_groups'] for k in b.get('fields') or []}
        for k in keys:
            label = named.get(k, '')
            if bands and bands[-1]['label'] == label and label:
                bands[-1]['span'] += 1
            else:
                bands.append({'label': label, 'span': 1})
    # a line down the table where a band starts (between A and B, and before the wire details)
    edges = []
    for i, b in enumerate(bands):
        edges += [i > 0] + [False] * (b['span'] - 1)
    # "add_by": a link of the rows to pick them by (an order's lines by their part), "add_quantity": how many of it;
    # "link_existing": false where rows belong to this record alone (an order's lines): no ⇄ Link
    pick = by_key.get(show.get('add_by')) if show.get('add_by') else None
    pick = pick if pick is not None and pick.type == 'link' else None
    can_add = show.get('add', True) and can(request.user, target.app, 'editor')
    return {'footer': add_below(request, data, record, show, target, inverse, bands, len(cols)) if can_add else [],
            'field': field, 'target': target, 'columns': cols, 'rows': rows, 'inverse': inverse, 'groups': groups,
            'pick': pick, 'pick_qty': by_key.get(show.get('add_quantity')) if pick else None,
            'link_existing': show.get('link_existing', True),
            'group_join': show.get('group_join') or ' · ', 'aligned': aligned, 'bands': bands, 'edges': edges,
            'can_add': can_add}


def group_lines(data, value, lines):
    """A sub-header's linked record in lines, "group_lines": [["part"], ["designator", "gender"]]: its part above,
    its designator and gender under it."""
    out = []
    for pk in value.ids:
        linked = data.record(pk)
        if linked is None:
            continue
        fields = {f.key: f for f in data.fields(linked.table)}
        texts = [' · '.join(t for t in (data.text(linked, fields[k]) for k in line if k in fields) if t) for line in lines]
        out.append(format_html('<a class="link-chip lines" href="{}">{}</a>', linked.get_absolute_url(),
                               format_html_join('', '<span>{}</span>', ((t,) for t in texts if t))))
    return format_html_join('', '{}', ((h,) for h in out))


def add_below(request, data, record, show, target, inverse, bands, width):
    """Buttons in a row at the bottom of a section, under the band they belong to, "add_below": [{"band": "A",
    "label": "Connector", "link": "connectors", "values": {"side": "A"}}, {"band": "Wire details", "label": "Wire"}]:
    a new one in a form, linked to this record, through the record's own link "link" (this section's, without it)
    and with "values" filled in."""
    wanted = show.get('add_below') or []
    if not wanted:
        return []
    own = {f.key: f for f in data.fields(record.table)}
    here = request.get_full_path()
    buttons = []
    for b in wanted:
        table, link_field = target, inverse
        if b.get('link'):
            through = own.get(b['link'])
            if through is None or through.type != 'link' or not through.opt('inverse'):
                continue
            table = Table.objects.filter(pk=through.opt('target')).first()
            link_field = Field.objects.filter(pk=through.opt('inverse')).first()
        if table is None or link_field is None or not can(request.user, table.app, 'editor'):
            continue
        fields = {f.key: f for f in data.fields(table)}
        presets = ''.join(f'&f_{fields[k].pk}={v}' for k, v in (b.get('values') or {}).items() if k in fields)
        url = (reverse('core:record_new', args=[table.app.slug, table.slug]) +
               f'?link_field={link_field.pk}&link_to={record.pk}{presets}&next={here}')
        buttons.append((b.get('band', ''), format_html('<a class="btn small ghost" href="{}">＋ {}</a>', url, b.get('label') or table.name)))
    cells = [{'span': band['span'], 'buttons': [h for name, h in buttons if name == band['label']]} for band in bands] \
        or [{'span': width, 'buttons': [h for _, h in buttons]}]
    placed = {name for name, _ in buttons} & {band['label'] for band in bands}
    cells[0]['buttons'] += [h for name, h in buttons if name not in placed]
    return cells


def access_context(request, record, table):
    """The record's access tags (own and inherited), who it is shared with, and the tags the person may put on it."""
    from .access import user_tags
    from .models import AccessGrant, Tag
    tags = {t.pk: t for t in Tag.objects.filter(pk__in=set(record.access or []) | set(record.tags or []))}
    mine = user_tags(request.user)
    return {
        'access_own': [tags[t] for t in record.tags or [] if t in tags],
        'access_inherited': [tags[t] for t in record.access or [] if t in tags and t not in (record.tags or [])],
        'access_grants': AccessGrant.objects.filter(record=record).select_related('user', 'granted_by'),
        'tag_choices': [{'tag': t, 'on': t.pk in (record.tags or [])} for t in Tag.objects.filter(pk__in=mine)],
        'can_tag': can(request.user, table.app, 'editor') and bool(mine),
        'is_space_record': table.is_space and table.tree_field_id,
    }


@login_required
@require_POST
def record_tags(request, pk):
    """Put access tags on a record (only tags the person holds; see core.access.set_tags)."""
    from . import access
    record = record_or_404(request, pk, 'editor')
    try:
        access.set_tags(record, [t for t in request.POST.getlist('tags') if t.isdigit()], request.user)
    except ValidationError as exc:
        for m in exc.messages:
            messages.error(request, m)
    else:
        messages.success(request, 'The access tags are saved.')
    return redirect(record)


@login_required
def record_page(request, pk):
    from . import space
    from .models import Star
    record = record_or_404(request, pk)
    space.seen(request.user, record)
    data = Data(request.user)
    record = data.record(record.pk)
    table = data.table(record.table_id)
    context = {**app_context(table.app, request.user), 'table': table, 'cell_editing': can(request.user, table.app, 'editor'),
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
    initial, copied = {}, None
    copy = request.GET.get('copy', '')
    if copy.isdigit():
        copied = data.record(int(copy))
        if copied is not None and copied.table_id == table.pk:
            preset, initial = copied_values(data, copied, fields)
            if request.method == 'GET':
                messages.info(request, f'A copy of {data.label(copied)}: change what differs, then save. '
                                       'Its files and comments are not copied.')
    needs_share = False
    if request.method == 'POST':
        values, _ = _form_values(request, fields)
        for k, v in preset.items():
            values.setdefault(k, v)
        try:
            with transaction.atomic():
                record = service.create_record(table, values, user=request.user, data=data,
                                               share=bool(request.POST.get('share')),
                                               tags=[t for t in request.POST.getlist('tags') if t.isdigit()])
                _save_files(request, record, data, request.user)
        except ValidationError as exc:
            if sharing_error(request, exc):
                needs_share = True
            else:
                for m in exc.messages:
                    messages.error(request, m)
        else:
            messages.success(request, f'{data.label(data.record(record.pk))} is added.')
            if 'add_another' in request.POST:
                return redirect(request.get_full_path())
            return redirect(local_next(request) or record.get_absolute_url())
    return render(request, 'core/record_new.html', {
        **app_context(app, request.user), 'table': table, 'items': form_items(request, fields, data, preset, initial),
        'all_users': get_user_model().objects.filter(is_active=True), 'next': local_next(request),
        'link_field': link_field or '', 'link_to': link_to or '', 'needs_share': needs_share,
        'tag_choices': _tag_choices(request), 'chosen_tags': request.POST.getlist('tags'),
        'meta': json.dumps({'fields': fields_meta(data, [table]), 'users': users_meta(data)}),
    })


def _tag_choices(request):
    from .access import user_tags
    from .models import Tag
    return list(Tag.objects.filter(pk__in=user_tags(request.user)))


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
    return redirect(local_next(request) or table.get_absolute_url())


@login_required
@require_POST
def record_comment(request, pk):
    record = record_or_404(request, pk, 'editor')
    text = request.POST.get('text', '').strip()
    if text:
        service.add_comment(record, text, request.user)
    return redirect(local_next(request) or record.get_absolute_url())


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
    return redirect(local_next(request) or record.get_absolute_url())


@login_required
@require_POST
def attachment_delete(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('record__table__app'), pk=pk)
    record = record_or_404(request, attachment.record_id, 'editor')
    service.remove_attachment(attachment, request.user)
    return redirect(local_next(request) or record.get_absolute_url())


@login_required
def attachment_file(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related('record__table__app'), pk=pk)
    record_or_404(request, attachment.record_id)
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
    return render(request, 'core/table_import.html', {**app_context(app, request.user), 'table': table, 'report': report,
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
