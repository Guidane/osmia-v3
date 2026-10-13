"""Kinds of views: grid, tree, kanban, gallery, calendar, gantt, form, detail.

Every view shows the records of its table that pass its filters (and the
filters, search and sort typed in the toolbar), in its order. A view type
turns those records into what its template needs. Extensions add their own
with ``core.extensions.registry.view_type``.

``View.config`` keys used here:

    fields        visible field keys, in order (default: all)
    widths        {field key: px}  (grid)
    filters       conditions (see core.filters)
    sorts         [{"field": key, "dir": "asc" | "desc"}]
    group_by      field key (grid, gantt)
    group_field   select / single link / user field (kanban)
    cover_field   attachment field (kanban, gallery)
    date_field, end_field, color_field                  (calendar)
    start_field, end_field, progress_field, color_field (gantt)
    parent_field  link to the same table (tree)
    title, description, submit_label, message           (form)
"""
import calendar as cal
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from . import filters, formula
from .formula import FormulaError, Records

VIEW_TYPES = {}


def register(cls):
    VIEW_TYPES[cls.key] = cls()
    return cls


def get_view_type(key):
    return VIEW_TYPES.get(key) or VIEW_TYPES['grid']


@dataclass
class Setting:
    """One setting of a view type, shown on the view's settings form.
    kind: field | fields | text | textarea | choice"""
    name: str
    label: str
    kind: str = 'field'
    types: tuple = ()       # field types allowed (kind field)
    choices: tuple = ()     # (value, label) for kind choice
    help: str = ''
    required: bool = False
    same_table_link: bool = False


# -- The records a view shows ------------------------------------------------------------

def visible_fields(view, data, default_count=None):
    fields = data.fields(view.table_id)
    keys = (view.config or {}).get('fields')
    if keys:
        by_key = {f.key: f for f in fields}
        shown = [by_key[k] for k in keys if k in by_key]
        return shown or fields[:1]
    return fields[:default_count] if default_count else fields


def toolbar_state(request, view):
    """Filters, sorts, search and grouping: the view's own, or what the toolbar asks for."""
    cfg = view.config or {}
    state = {
        'filters': cfg.get('filters') or {'match': 'all', 'rules': []},
        'sorts': cfg.get('sorts') or [],
        'group_by': cfg.get('group_by') or '',
        'q': request.GET.get('q', '').strip(),
        'temporary': False,
    }
    if 'filters' in request.GET:
        try:
            state['filters'] = json.loads(request.GET['filters']) or {'match': 'all', 'rules': []}
            state['temporary'] = True
        except ValueError:
            pass
    if 'sorts' in request.GET:
        try:
            state['sorts'] = json.loads(request.GET['sorts']) or []
            state['temporary'] = True
        except ValueError:
            pass
    if 'group_by' in request.GET:
        state['group_by'] = request.GET['group_by']
        state['temporary'] = True
    return state


def sort_records(data, table, records, sorts):
    fields = {f.key: f for f in data.fields(table)}
    for s in reversed(sorts or []):
        field = fields.get(s.get('field'))
        if field is None:
            continue
        desc = s.get('dir') == 'desc'
        blanks = [r for r in records if field.kind.sort_key(data.value(r, field))[0] == 1]
        filled = [r for r in records if field.kind.sort_key(data.value(r, field))[0] != 1]
        filled.sort(key=lambda r: field.kind.sort_key(data.value(r, field)), reverse=desc)
        records = filled + blanks  # empty values last, either way
    return records


def query(data, view, state):
    records = data.records(view.table_id)
    records = filters.apply(data, records, state['filters'])
    if state['q']:
        found = {r.pk for r in data.search(view.table_id, state['q'])}
        records = [r for r in records if r.pk in found]
    return sort_records(data, view.table_id, records, state['sorts'])


def cover_url(data, record, view):
    key = (view.config or {}).get('cover_field')
    fields = [f for f in data.fields(view.table_id) if f.type == 'attachment' and (not key or f.key == key)]
    for f in fields:
        for a in data.value(record, f) or []:
            if a.is_image:
                return f'/files/{a.pk}/?thumb=1'
    return ''


def color_of(data, record, field):
    if field is None:
        return ''
    value = formula.unwrap(data.value(record, field))
    if field.type in ('select', 'multiselect') and value:
        from .fieldtypes import choice_color
        return choice_color(field, value if isinstance(value, str) else value[0])
    if field.type == 'color':
        return value or ''
    return ''


def field_by_key(data, view, name):
    key = (view.config or {}).get(name)
    return next((f for f in data.fields(view.table_id) if f.key == key), None) if key else None


def _unlinked(html):
    """A value without its links: a card is a link itself, and links can't be nested."""
    from django.utils.safestring import mark_safe
    html = str(html)
    if '<a' not in html:
        return mark_safe(html)
    html = re.sub(r'<a(?=[\s>])[^>]*?(\sclass="[^"]*")?[^>]*>', lambda m: f'<span{m.group(1) or ""}>', html)
    return mark_safe(html.replace('</a>', '</span>'))


def card(data, record, view, fields):
    return {
        'record': record,
        'title': data.label(record),
        'cover': cover_url(data, record, view),
        'fields': [(f, _unlinked(data.html(record, f))) for f in fields if f != data.primary_field(view.table_id)],
    }


# -- View types --------------------------------------------------------------------------------

class ViewType:
    key = ''
    label = ''
    icon = '▦'
    help = ''
    template = ''
    settings = ()
    uses_records = True   # False: the view shows something else (e.g. a form)
    toolbar = True

    def available(self, table, data):
        return True

    def missing(self, view, data):
        """What has to be set before the view can show anything (or None)."""
        for s in self.settings:
            if s.required and not field_by_key(data, view, s.name):
                return f'Pick the {s.label.lower()} in the view\'s settings.'
        return None

    def context(self, request, view, data, records, state):
        return {}


@register
class Grid(ViewType):
    key, label, icon, template = 'grid', 'Grid', '▦', 'core/views/grid.html'
    help = 'A spreadsheet: edit cells in place, group, filter and sort.'
    page_size = 200

    def context(self, request, view, data, records, state):
        columns = visible_fields(view, data)
        widths = (view.config or {}).get('widths') or {}
        group_field = next((f for f in data.fields(view.table_id) if f.key == state['group_by']), None)
        try:
            page = max(1, int(request.GET.get('page', 1)))
        except ValueError:
            page = 1
        total = len(records)
        shown = records[(page - 1) * self.page_size: page * self.page_size]

        def row(r):
            return {'record': r, 'cells': [(f, data.html(r, f), widths.get(f.key)) for f in columns]}

        groups = []
        if group_field:
            order, buckets = [], {}
            for r in shown:
                value = data.value(r, group_field)
                key = formula.text(value)
                if key not in buckets:
                    buckets[key] = []
                    order.append((key, data.html(r, group_field)))
                buckets[key].append(row(r))
            if group_field.type == 'select':
                rank = {c['value']: i for i, c in enumerate(group_field.opt('choices') or [])}
                order.sort(key=lambda kv: rank.get(kv[0], 999 if kv[0] else 1000))
            else:
                order.sort(key=lambda kv: (kv[0] == '', kv[0].lower()))
            groups = [{'key': k, 'html': h, 'rows': buckets[k]} for k, h in order]
        totals = []
        for f in columns:
            if f.kind.align == 'num' or (f.type == 'formula' and f.opt('format') in ('number', 'currency')):
                vals = formula.numbers([data.value(r, f) for r in records])
                if vals and f.type not in ('record_id', 'autonumber', 'rating'):
                    from decimal import Decimal
                    s = sum(vals, Decimal(0))
                    totals.append(f.kind.html(f, s, data) if f.type not in ('rollup', 'formula') else
                                  f.kind.html(f, s, data))
                    continue
            totals.append('')
        return {
            'columns': [(f, widths.get(f.key)) for f in columns],
            'rows': [row(r) for r in shown] if not groups else [],
            'groups': groups,
            'group_field': group_field,
            'totals': totals if any(totals) else [],
            'page': page,
            'pages': max(1, (total + self.page_size - 1) // self.page_size),
            'total': total,
        }


@register
class Tree(ViewType):
    key, label, icon, template = 'tree', 'Tree', '🌳', 'core/views/tree.html'
    help = 'Records nested under their parent, e.g. budgets and sub-budgets, or locations on shelves in racks.'
    settings = (Setting('parent_field', 'Parent field', 'field', ('link',), required=True, same_table_link=True,
                        help='A link field to the same table that points at the parent.'),)

    def available(self, table, data):
        return any(f.type == 'link' and f.opt('target') == table.pk for f in data.fields(table))

    def context(self, request, view, data, records, state):
        parent_field = field_by_key(data, view, 'parent_field')
        columns = visible_fields(view, data)
        all_records = data.records(view.table_id)
        parent_of = {}
        for r in all_records:
            ids = data.linked_ids(r, parent_field)
            parent_of[r.pk] = ids[0] if ids else None
        shown = {r.pk for r in records}
        filtered = len(shown) != len(all_records)
        if filtered:  # keep the parents of the matches, so they stay in place
            for pk in list(shown):
                node, seen = parent_of.get(pk), set()
                while node and node not in seen:
                    seen.add(node)
                    shown.add(node)
                    node = parent_of.get(node)
        order = {r.pk: i for i, r in enumerate(records)}
        by_id = {r.pk: r for r in all_records}
        children = {}
        for r in all_records:
            if r.pk in shown:
                children.setdefault(parent_of[r.pk] if parent_of[r.pk] in shown else None, []).append(r)
        for kids in children.values():
            kids.sort(key=lambda r: (order.get(r.pk, len(order)), r.position, r.pk))
        rows, seen = [], set()

        def walk(parent, depth):
            for r in children.get(parent, []):
                if r.pk in seen:
                    continue
                seen.add(r.pk)
                rows.append({'record': r, 'depth': depth, 'parent': parent, 'has_children': bool(children.get(r.pk)),
                             'match': r.pk in order, 'cells': [(f, data.html(r, f)) for f in columns]})
                walk(r.pk, depth + 1)
        walk(None, 0)
        return {'columns': columns, 'rows': rows, 'parent_field': parent_field, 'filtered': filtered,
                'by_id': by_id}


@register
class Kanban(ViewType):
    key, label, icon, template = 'kanban', 'Kanban', '▥', 'core/views/kanban.html'
    help = 'Cards in columns by a status (or person, or link); drag a card to move it on.'
    settings = (
        Setting('group_field', 'Columns by', 'field', ('select', 'user', 'link'), required=True,
                help='A single select, a user field or a single link.'),
        Setting('cover_field', 'Cover picture', 'field', ('attachment',)),
        Setting('fields', 'Fields on the cards', 'fields'),
    )

    def available(self, table, data):
        return any(f.type in ('select', 'user', 'link') for f in data.fields(table))

    def context(self, request, view, data, records, state):
        group = field_by_key(data, view, 'group_field')
        fields = visible_fields(view, data, default_count=4)
        fields = [f for f in fields if f != group]
        columns = []
        if group.type == 'select':
            for c in group.opt('choices') or []:
                columns.append({'value': c['value'], 'label': c['value'], 'color': color_of_choice(group, c['value']), 'cards': []})
        elif group.type == 'user':
            for uid, u in sorted(data.users().items(), key=lambda kv: str(kv[1])):
                if u.is_active:
                    columns.append({'value': uid, 'label': str(u), 'color': '', 'cards': []})
        else:
            for t in data.records(group.opt('target'))[:50]:
                columns.append({'value': t.pk, 'label': data.label(t), 'color': '', 'cards': []})
        empty = {'value': '', 'label': f'No {group.name.lower()}', 'color': '', 'cards': []}
        index = {str(c['value']): c for c in columns}
        for r in records:
            value = data.value(r, group)
            if isinstance(value, Records):
                key = str(value.ids[0]) if value.ids else ''
            else:
                key = formula.text(value)
            (index.get(key) or empty)['cards'].append(card(data, r, view, fields))
        if empty['cards'] or not columns:
            columns.insert(0, empty)
        return {'columns': columns, 'group_field': group,
                'can_drag': group.editable and (group.type != 'link' or not group.opt('multiple'))}


def color_of_choice(field, value):
    from .fieldtypes import choice_color
    return choice_color(field, value)


@register
class Gallery(ViewType):
    key, label, icon, template = 'gallery', 'Gallery', '▩', 'core/views/gallery.html'
    help = 'Cards with a picture, e.g. parts or tools.'
    settings = (
        Setting('cover_field', 'Cover picture', 'field', ('attachment',)),
        Setting('fields', 'Fields on the cards', 'fields'),
    )

    def context(self, request, view, data, records, state):
        fields = visible_fields(view, data, default_count=5)
        return {'cards': [card(data, r, view, fields) for r in records[:500]], 'more': max(0, len(records) - 500)}


@register
class Calendar(ViewType):
    key, label, icon, template = 'calendar', 'Calendar', '📅', 'core/views/calendar.html'
    help = 'Records on the days of a month; drag one to another day.'
    settings = (
        Setting('date_field', 'Date', 'field', ('date', 'datetime', 'created_time', 'formula', 'lookup', 'rollup'), required=True),
        Setting('end_field', 'Until (optional)', 'field', ('date', 'datetime', 'formula')),
        Setting('color_field', 'Colour by', 'field', ('select', 'color')),
    )

    def available(self, table, data):
        return any(f.type in ('date', 'datetime', 'created_time') for f in data.fields(table))

    def context(self, request, view, data, records, state):
        start_f = field_by_key(data, view, 'date_field')
        end_f = field_by_key(data, view, 'end_field')
        color_f = field_by_key(data, view, 'color_field')
        today = timezone.localdate()
        try:
            year, month = (int(x) for x in request.GET.get('month', '').split('-'))
            first = date(year, month, 1)
        except ValueError:
            first = today.replace(day=1)
        last = first.replace(day=cal.monthrange(first.year, first.month)[1])
        grid_start = first - timedelta(days=first.weekday())
        grid_end = last + timedelta(days=6 - last.weekday())
        days = {}
        undated = 0
        for r in records:
            try:
                s = formula.to_date(data.value(r, start_f))
                e = formula.to_date(data.value(r, end_f)) if end_f else None
            except FormulaError:
                s = e = None
            if s is None:
                undated += 1
                continue
            e = e if e and e >= s else s
            d = max(s, grid_start)
            while d <= min(e, grid_end):
                days.setdefault(d, []).append({'record': r, 'label': data.label(r), 'color': color_of(data, r, color_f),
                                               'start': d == s, 'end': d == e})
                d += timedelta(days=1)
        weeks, d = [], grid_start
        while d <= grid_end:
            weeks.append([{'date': d + timedelta(days=i), 'events': days.get(d + timedelta(days=i), []),
                           'other': (d + timedelta(days=i)).month != first.month,
                           'today': d + timedelta(days=i) == today} for i in range(7)])
            d += timedelta(days=7)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        next_month = last + timedelta(days=1)
        return {'weeks': weeks, 'month': first, 'prev': prev_month.strftime('%Y-%m'), 'next': next_month.strftime('%Y-%m'),
                'this_month': today.strftime('%Y-%m'), 'date_field': start_f, 'end_field': end_f, 'undated': undated,
                'can_drag': start_f.type in ('date', 'datetime') and start_f.editable,
                'weekdays': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']}


@register
class Gantt(ViewType):
    key, label, icon, template = 'gantt', 'Gantt', '▤', 'core/views/gantt.html'
    help = 'A timeline of bars from a start to an end date; drag a bar to move it, its end to make it longer.'
    settings = (
        Setting('start_field', 'Start', 'field', ('date', 'datetime', 'formula', 'lookup', 'rollup', 'created_time'), required=True),
        Setting('end_field', 'End', 'field', ('date', 'datetime', 'formula', 'lookup', 'rollup')),
        Setting('group_by', 'Group by', 'field', ('select', 'link', 'user', 'text')),
        Setting('color_field', 'Colour by', 'field', ('select', 'color')),
        Setting('progress_field', 'Progress', 'field', ('percent', 'number', 'formula', 'rollup', 'checkbox')),
        Setting('dependency_field', 'Depends on', 'field', ('link',), same_table_link=True,
                help='A link to the same table: the tasks that must finish first (drawn as arrows).'),
        Setting('zoom', 'Scale', 'choice', choices=(('day', 'Days'), ('week', 'Weeks'), ('month', 'Months'))),
    )
    SCALE = {'day': 32, 'week': 12, 'month': 4}

    def available(self, table, data):
        return any(f.type in ('date', 'datetime') for f in data.fields(table))

    def context(self, request, view, data, records, state):
        cfg = view.config or {}
        start_f = field_by_key(data, view, 'start_field')
        end_f = field_by_key(data, view, 'end_field')
        color_f = field_by_key(data, view, 'color_field')
        progress_f = field_by_key(data, view, 'progress_field')
        dep_f = field_by_key(data, view, 'dependency_field')
        group_f = next((f for f in data.fields(view.table_id) if f.key == (state['group_by'] or cfg.get('group_by'))), None)
        zoom = request.GET.get('zoom') or cfg.get('zoom') or 'day'
        px = self.SCALE.get(zoom, 32)
        today = timezone.localdate()
        items, unscheduled = [], []
        for r in records:
            try:
                s = formula.to_date(data.value(r, start_f))
                e = formula.to_date(data.value(r, end_f)) if end_f else None
            except FormulaError:
                s = e = None
            if s is None and e is None:
                unscheduled.append(r)
                continue
            s = s or e
            e = e if e and e >= s else s
            progress = None
            if progress_f:
                v = formula.unwrap(data.value(r, progress_f))
                if progress_f.type == 'checkbox':
                    progress = 100 if v else 0
                else:
                    try:
                        progress = max(0, min(100, float(formula.num(v)))) if not formula.is_blank(v) else None
                    except FormulaError:
                        progress = None
            items.append({'record': r, 'label': data.label(r), 'start': s, 'end': e, 'color': color_of(data, r, color_f),
                          'progress': progress, 'deps': data.linked_ids(r, dep_f) if dep_f else [],
                          'group': (formula.text(data.value(r, group_f)) if group_f else '')})
        if items:
            lo = min(i['start'] for i in items)
            hi = max(i['end'] for i in items)
        else:
            lo = hi = today
        lo = min(lo, today) - timedelta(days=3 if zoom == 'day' else 14)
        hi = max(hi, today) + timedelta(days=7 if zoom == 'day' else 30)
        if zoom != 'day':
            lo -= timedelta(days=lo.weekday())
        days = (hi - lo).days + 1
        for i in items:
            i['left'] = (i['start'] - lo).days * px
            i['width'] = max(((i['end'] - i['start']).days + 1) * px - 2, 6)
        groups = []
        if group_f:
            order = []
            buckets = {}
            for i in items:
                buckets.setdefault(i['group'], []).append(i)
                if i['group'] not in order:
                    order.append(i['group'])
            if group_f.type == 'select':
                rank = {c['value']: n for n, c in enumerate(group_f.opt('choices') or [])}
                order.sort(key=lambda g: rank.get(g, 999))
            else:
                order.sort(key=lambda g: (g == '', g.lower()))
            groups = [{'label': g or f'No {group_f.name.lower()}', 'items': buckets[g]} for g in order]
        else:
            groups = [{'label': '', 'items': items}]
        row = 0
        for g in groups:
            if g['label']:
                row += 1
            for i in g['items']:
                i['row'] = row
                row += 1
        index = {i['record'].pk: i for i in items}
        arrows = []
        for i in items:
            for d in i['deps']:
                if d in index:
                    a = index[d]
                    arrows.append({'x1': a['left'] + a['width'], 'y1': a['row'] * 34 + 17, 'x2': i['left'], 'y2': i['row'] * 34 + 17})
        # header: months, and days or weeks
        months, ticks = [], []
        d = lo
        while d <= hi:
            month_end = min(d.replace(day=cal.monthrange(d.year, d.month)[1]), hi)
            months.append({'label': d.strftime('%b %Y'), 'width': ((month_end - d).days + 1) * px})
            d = month_end + timedelta(days=1)
        d = lo
        while d <= hi:
            if zoom == 'day':
                ticks.append({'label': d.day, 'width': px, 'weekend': d.weekday() >= 5, 'today': d == today})
                d += timedelta(days=1)
            elif zoom == 'week':
                ticks.append({'label': f'W{d.isocalendar()[1]}', 'width': 7 * px, 'weekend': False, 'today': False})
                d += timedelta(days=7)
            else:
                ticks.append({'label': '', 'width': 7 * px, 'weekend': False, 'today': False})
                d += timedelta(days=7)
        return {'zooms': (('day', 'Days'), ('week', 'Weeks'), ('month', 'Months')),
                'groups': groups, 'unscheduled': unscheduled, 'months': months, 'ticks': ticks, 'px': px, 'zoom': zoom,
                'width': days * px, 'height': max(row, 1) * 34, 'today_left': (today - lo).days * px,
                'origin': lo.isoformat(), 'arrows': arrows, 'start_field': start_f, 'end_field': end_f,
                'can_drag': start_f.type in ('date', 'datetime') and start_f.editable and (end_f is None or end_f.editable)}


@register
class Form(ViewType):
    key, label, icon, template = 'form', 'Form', '☰', 'core/views/form.html'
    help = 'A form to add records, with a title, a text and the fields you choose.'
    uses_records = False
    toolbar = False
    settings = (
        Setting('fields', 'Fields on the form', 'fields'),
        Setting('title', 'Title', 'text'),
        Setting('description', 'Text above the form', 'textarea'),
        Setting('submit_label', 'Button text', 'text'),
        Setting('message', 'Message after sending', 'text'),
    )

    def context(self, request, view, data, records, state):
        fields = [f for f in visible_fields(view, data) if f.editable and (f.kind.stored or f.type == 'link')]
        return {'form_fields': fields}


@register
class Detail(ViewType):
    key, label, icon, template = 'detail', 'Detail', '◧', 'core/views/detail.html'
    help = 'A list on the left and the whole record on the right, with its linked records, files and history.'
    settings = (Setting('fields', 'Fields in the list', 'fields'),)

    def context(self, request, view, data, records, state):
        fields = visible_fields(view, data, default_count=3)
        primary = data.primary_field(view.table_id)
        subtitle = [f for f in fields if f != primary][:2]
        selected = None
        rid = request.GET.get('r')
        if rid and rid.isdigit():
            selected = next((r for r in records if r.pk == int(rid)), None) or data.record(int(rid))
            if selected is not None and selected.table_id != view.table_id:
                selected = None
        if selected is None and records:
            selected = records[0]
        items = [{'record': r, 'title': data.label(r), 'sub': [data.text(r, f) for f in subtitle]} for r in records[:500]]
        return {'items': items, 'selected': selected}
