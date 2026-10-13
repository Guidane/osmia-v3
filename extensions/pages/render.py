"""Showing a page: live views and record links are filled in as it's shown, with
the reader's permissions (a view they can't see says so instead)."""
import re

from django.template.loader import render_to_string
from django.utils.html import escape

from core.data import Data
from core.models import Record, View
from core.permissions import can
from core.viewtypes import query, visible_fields

EMBED = re.compile(r'<div class="embed-view" data-view="(\d+)"[^>]*>.*?</div>', re.S)
RECORD = re.compile(r'<a class="record-ref" data-record="(\d+)"[^>]*>(.*?)</a>', re.S)
ROWS = 25


class _State(dict):
    """A toolbar state without a request: the view's own filters and sorts."""


def _view_html(view_id, user, data):
    view = View.objects.select_related('table__app').filter(pk=view_id).first()
    if view is None:
        return '<div class="embed-missing">A view was here; it has been deleted.</div>'
    if not can(user, view.table.app, 'viewer'):
        return f'<div class="embed-missing">🔒 A view of {escape(view.table.app.name)} you have no access to.</div>'
    cfg = view.config or {}
    state = {'filters': cfg.get('filters') or {}, 'sorts': cfg.get('sorts') or [], 'group_by': '', 'q': '', 'temporary': False}
    records = query(data, view, state)
    columns = [f for f in visible_fields(view, data) if f.type not in ('button', 'json')][:8]
    rows = [{'record': r, 'cells': [data.html(r, f) for f in columns]} for r in records[:ROWS]]
    return render_to_string('pages/_embed_view.html', {'view': view, 'columns': columns, 'rows': rows,
                                                       'more': max(0, len(records) - ROWS), 'total': len(records)})


def _record_html(record_id, text, user, data):
    record = Record.objects.select_related('table__app').filter(pk=record_id).first()
    if record is None:
        return f'<span class="record-ref gone" title="Deleted">{text}</span>'
    if not can(user, record.table.app, 'viewer'):
        return '<span class="record-ref gone">🔒 a record</span>'
    label = escape(data.label(data.record(record.pk)))
    return (f'<a class="record-ref" href="{record.get_absolute_url()}" title="{escape(record.table.app.name)} › '
            f'{escape(record.table.name)}">{record.table.icon or "▦"} {label}</a>')


def render(body, user):
    data = Data(user)
    body = EMBED.sub(lambda m: _view_html(int(m.group(1)), user, data), body or '')
    return RECORD.sub(lambda m: _record_html(int(m.group(1)), m.group(2), user, data), body)


TEMPLATES = {
    'blank': ('Blank page', '📄', ''),
    'meeting': ('Meeting notes', '🗓', """
<div class="panel info"><p><b>Date:</b> &nbsp; <b>Attendees:</b> </p></div>
<h2>Goals</h2><ul><li></li></ul>
<h2>Discussion</h2><table><thead><tr><th>Topic</th><th>Who</th><th>Notes</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Action items</h2><ul class="tasks"><li class="task" data-checked="false"></li></ul>
<h2>Decisions</h2><ul><li></li></ul>"""),
    'howto': ('How-to', '🛠', """
<div class="panel note"><p>What this is for, in one sentence.</p></div>
<h2>Before you start</h2><ul><li></li></ul>
<h2>Steps</h2><ol><li></li><li></li><li></li></ol>
<div class="panel warning"><p>What to watch out for.</p></div>
<h2>Related</h2><ul><li></li></ul>"""),
    'decision': ('Decision', '⚖', """
<table><tbody><tr><th>Status</th><td>Proposed</td></tr><tr><th>Owner</th><td></td></tr><tr><th>Decided on</th><td></td></tr></tbody></table>
<h2>Background</h2><p></p>
<h2>Options</h2><table><thead><tr><th>Option</th><th>For</th><th>Against</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Decision</h2><div class="panel success"><p></p></div>
<h2>Consequences</h2><ul><li></li></ul>"""),
    'retro': ('Retrospective', '🔁', """
<h2>What went well</h2><ul><li></li></ul>
<h2>What could be better</h2><ul><li></li></ul>
<h2>What we'll try next</h2><ul class="tasks"><li class="task" data-checked="false"></li></ul>"""),
    'project': ('Project plan', '📁', """
<div class="panel info"><p><b>Goal:</b> </p></div>
<h2>Scope</h2><p><b>In:</b> </p><p><b>Out:</b> </p>
<h2>Milestones</h2><table><thead><tr><th>Milestone</th><th>Date</th><th>Owner</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Risks</h2><table><thead><tr><th>Risk</th><th>Likelihood</th><th>What we do about it</th></tr></thead><tbody><tr><td></td><td></td><td></td></tr></tbody></table>
<h2>Tasks</h2><p>Embed a view of the project's tasks with <b>⊞ View</b> in the toolbar.</p>"""),
}
