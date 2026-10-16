"""Showing a page: its live parts are filled in as it's shown, for the reader.

Live parts are placeholders in the (cleaned) HTML:

    <div class="embed-view" data-view="12">          a live view of an app
    <a class="record-ref" data-record="5">            a link to a record
    <div class="record-card" data-record="5" data-fields="3,4">   a card with some of a record's fields
    <span class="record-value" data-record="5" data-field="3">    one field's value inside a sentence
    <span class="page-calc" data-formula="...">       a calculation (see calc)
    <a class="app-card" data-app="orders">            a small card that opens an app
    <div class="live-block" data-block="my_work">     a block of core or an extension (see blocks)
    <div class="grid-block" data-cols="3"><div class="grid-cell">…</div>…</div>   cells side by side

What the reader can't see (an app they have no access to, a record whose tags
they don't hold) is left out entirely: no placeholder, no "locked" notice.
"""
import re

from django.template.loader import render_to_string
from django.utils.html import escape

from ..formula import FormulaError
from ..models import App, View
from ..permissions import can
from ..viewtypes import query, visible_fields
from . import calc
from .calc import PageData, calculate

EMBED = re.compile(r'<div class="embed-view" data-view="(\d+)"[^>]*>.*?</div>', re.S)
RECORD = re.compile(r'<a class="record-ref" data-record="(\d+)"[^>]*>(.*?)</a>', re.S)
CARD = re.compile(r'<div class="record-card"([^>]*)>.*?</div>', re.S)
VALUE = re.compile(r'<span class="record-value"([^>]*)>(.*?)</span>', re.S)
APP_CARD = re.compile(r'<a class="app-card" data-app="([a-z0-9-]+)"[^>]*>.*?</a>', re.S)
BLOCK = re.compile(r'<div class="live-block" data-block="([a-z0-9_]+)"[^>]*>.*?</div>', re.S)
ATTR = re.compile(r'(data-[a-z]+)="([\d,]*)"')
NOT_SHOWN = ('button', 'json')   # fields a card or a value doesn't show
ROWS = 25


def _safe(work):
    """A value worked out from links can be too big for a page (calc.MAX_LINKED): say so, don't fail."""
    try:
        return work()
    except FormulaError as e:
        return f'⚠ {escape(str(e))}'


def _view_html(view_id, user, data):
    view = View.objects.select_related('table__app').filter(pk=view_id).first()
    if view is None or not can(user, view.table.app, 'viewer'):
        return ''
    if data.is_big(view.table_id):
        return (f'<div class="embed-missing">⊞ <a href="{view.get_absolute_url()}">{escape(view.table.name)} › {escape(view.name)}</a> '
                f'has {data.table_size(view.table_id):,} records, more than the {calc.BIG_TABLE:,} a page shows in a view. '
                'Open it to look through them.</div>')
    cfg = view.config or {}
    state = {'filters': cfg.get('filters') or {}, 'sorts': cfg.get('sorts') or [], 'group_by': '', 'q': '', 'temporary': False}
    records = query(data, view, state)
    columns = [f for f in visible_fields(view, data) if f.type not in NOT_SHOWN][:8]
    rows = [{'record': r, 'cells': [_safe(lambda: data.html(r, f)) for f in columns]} for r in records[:ROWS]]
    return render_to_string('core/canvas/_embed_view.html', {'view': view, 'columns': columns, 'rows': rows,
                                                             'more': max(0, len(records) - ROWS), 'total': len(records)})


def _readable(record_id, user, data):
    """The record, if the reader may see it (else None)."""
    record = data.record(record_id) if record_id else None
    if record is None:
        return None
    table = data.table(record.table_id)
    return record if can(user, table.app, 'viewer') else None


def _record_html(record_id, user, data):
    record = _readable(record_id, user, data)
    if record is None:
        return ''
    table = data.table(record.table_id)
    return (f'<a class="record-ref" href="{record.get_absolute_url()}" title="{escape(table.app.name)} › '
            f'{escape(table.name)}">{table.icon or "▦"} {escape(data.label(record))}</a>')


def _card_html(attrs, user, data):
    attrs = dict(ATTR.findall(attrs))
    record = _readable(int(attrs.get('data-record') or 0), user, data)
    if record is None:
        return ''
    table = data.table(record.table_id)
    ids = [int(x) for x in (attrs.get('data-fields') or '').split(',') if x]
    fields = [f for f in (data.field(i) for i in ids) if f is not None and f.table_id == table.pk and f.type not in NOT_SHOWN]
    rows = [{'field': f, 'html': _safe(lambda: data.html(record, f))} for f in fields]
    return render_to_string('core/canvas/_record_card.html', {'record': record, 'table': table, 'label': data.label(record),
                                                              'rows': rows, 'gone': len(ids) - len(fields)})


def _value_html(attrs, user, data):
    attrs = dict(ATTR.findall(attrs))
    record = _readable(int(attrs.get('data-record') or 0), user, data)
    if record is None:
        return ''
    field = data.field(attrs.get('data-field'))
    if field is None or field.table_id != record.table_id or field.type in NOT_SHOWN:
        return ''
    try:
        shown = data.text(record, field) or '—'
    except FormulaError as e:
        return f'<span class="record-ref gone" title="{escape(str(e))}">⚠</span>'
    where = f'{data.label(record)} › {field.name}'
    return f'<a class="record-value" href="{record.get_absolute_url()}" title="{escape(where)} · live">{escape(shown)}</a>'


def app_card(app):
    return render_to_string('core/canvas/_app_card.html', {'a': app})


def _app_card_html(slug, user):
    app = App.objects.filter(slug=slug).first()
    if app is None or not can(user, app, 'viewer'):
        return ''
    return app_card(app)


def _block_html(key, request, context):
    from .blocks import render_block
    return render_block(key, request, context)


def render(body, request, context=None):
    """The page for ``request.user``; ``context``: {'space': record, 'app': app} it is the page of."""
    user = request.user
    context = context or {}
    data = PageData(user)
    body = calculate(body or '', user, data)
    body = BLOCK.sub(lambda m: _block_html(m.group(1), request, {**context, 'data': data}), body)
    body = APP_CARD.sub(lambda m: _app_card_html(m.group(1), user), body)
    body = EMBED.sub(lambda m: _view_html(int(m.group(1)), user, data), body)
    body = CARD.sub(lambda m: _card_html(m.group(1), user, data), body)
    body = VALUE.sub(lambda m: _value_html(m.group(1), user, data), body)
    return RECORD.sub(lambda m: _record_html(int(m.group(1)), user, data), body)
