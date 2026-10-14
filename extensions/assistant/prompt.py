"""The prompt Osmia gives an AI: the person's request, how to answer, and their workspace.

Only what the person may see goes in: the spaces and apps they can look at, the
fields of the apps in the chosen space (or the chosen app), and, if they ask for it,
some of the records and the page being changed. Whatever is in it goes to the AI
they paste it into, so the page says so.
"""
import re

from core.data import Data
from core.fieldtypes import ROLLUPS, TYPES
from core.models import Space
from core.permissions import can_make_spaces, role, space_role, visible_apps, visible_spaces

from .plan import MAX_CHANGES, MAX_RECORDS, VIEWS, field_types

SAMPLE_RECORDS = 10       # records per table, when asked for
MAX_CONTEXT = 60_000      # characters of workspace description
MAX_PAGE = 20_000         # characters of the page being changed

FORMAT = """\
## How to answer

Answer with ONE JSON object in a ```json code block, and nothing else. Osmia checks it, shows the person
every change, and makes them only when they say so. It never deletes anything, so there is no change for that.

{"osmia": 1, "summary": "One sentence: what this does", "changes": [ ...changes, in order... ]}

If the request is unclear or can't be done with these changes, answer {"osmia": 1, "question": "..."} instead.

Changes (later changes can use what earlier ones make; use the exact names from the workspace below):

{"do": "create_space", "name": "Operations", "key": "OPS", "kind": "team", "visibility": "internal", "description": "..."}
    kind: <<KINDS>>. visibility: "internal" (everyone can look) or "private" (members only).
{"do": "create_app", "space": "OPS", "name": "Suppliers", "icon": "🏭", "description": "...",
 "tables": [{"name": "Suppliers", "fields": [FIELD, ...], "views": [VIEW, ...], "records": [RECORD, ...]}, ...]}
    space: a space key or name, or "personal" for the person's own space. The first field of a table is its name field.
{"do": "change_app", "app": "Suppliers", "name": "...", "icon": "...", "description": "..."}
{"do": "add_table", "app": "Suppliers", "name": "Contacts", "fields": [FIELD, ...], "views": [VIEW, ...], "records": [RECORD, ...]}
{"do": "add_field", "app": "Suppliers", "table": "Suppliers", "field": FIELD}
{"do": "change_field", "app": "Suppliers", "table": "Suppliers", "field": "Status",
 "name": "new name", "type": "new type", "choices": ["all", "the", "choices"], "expression": "new formula", "required": true, "description": "..."}
    give only what changes.
{"do": "add_view", "app": "Suppliers", "table": "Suppliers", "name": "Board", "type": "kanban", "group_by": "Status"}
{"do": "add_records", "app": "Suppliers", "table": "Suppliers", "records": [RECORD, ...]}
{"do": "update_records", "app": "Suppliers", "table": "Suppliers", "where": {"Name": "Acme"}, "set": {"Status": "Paused"}}
    where: field values the records have now (all must match). At most <<MAX_RECORDS>> records per change.
{"do": "create_page", "space": "OPS", "title": "Supplier handbook", "parent": "title of a page to put it under", "emoji": "📘", "body": "HTML"}
{"do": "update_page", "space": "OPS", "page": "Supplier handbook", "title": "...", "body": "HTML (replaces it)", "append": "HTML (added at the end)"}

FIELD: {"name": "Status", "type": "select", "choices": ["Active", "Paused"], "required": false, "description": "..."}
    type is one of: <<TYPES>>
    select / multiselect: "choices". user: "multiple": true/false.
    link: "target": "Table" (in the same app) or "App › Table", "multiple": true/false. A link adds its pair to the
          other table by itself (named after this table, or "inverse_name"); never make both sides.
    formula: "expression", e.g. "{Quantity} * {Unit price}" or "IF({Due} < TODAY(), \\"Late\\", \\"\\")".
    lookup: "link": a link field of this table, "field": a field of the linked table.
    rollup: "link", "field" and "func": one of <<FUNCS>> (count needs no "field").
VIEW: {"name": "Board", "type": "kanban", "group_by": "a select, user or link field"}
    type is one of: <<VIEWTYPES>> (calendar needs "date": a date field).
RECORD: {"Field name": value, ...}. Links take the name of the linked record, select fields one of the choices,
    dates "2026-10-14", users a username.
Page bodies are simple HTML: p, h2, h3, ul/ol/li, table/thead/tbody/tr/th/td, b, i, a, blockquote, code, pre and
    <div class="panel info|note|warning|success"><p>...</p></div>.

At most <<MAX_CHANGES>> changes in one answer. Keep to what was asked: small requests need small changes.
"""


def _fmt():
    values = {'KINDS': ', '.join(k for k in Space.Kind.values if k != 'personal'),
              'TYPES': ', '.join(f'{k} ({TYPES[k].label})' for k in field_types()),
              'FUNCS': ', '.join(ROLLUPS), 'VIEWTYPES': ', '.join(VIEWS),
              'MAX_RECORDS': str(MAX_RECORDS), 'MAX_CHANGES': str(MAX_CHANGES)}
    return re.sub(r'<<([A-Z_]+)>>', lambda m: values[m.group(1)], FORMAT)


def _field_line(data, f):
    extra = ''
    if f.type in ('select', 'multiselect'):
        extra = ': ' + ', '.join(c['value'] for c in f.opt('choices') or [])
    elif f.type == 'link':
        target = data.table(f.opt('target'))
        extra = f' → {target.app.name} › {target.name}' if target else ''
    elif f.type == 'formula':
        extra = f': {f.opt("expression")}'
    req = ', required' if f.required else ''
    return f'{f.name} ({f.type}{extra}{req})'


def _app_block(user, data, app, with_records):
    lines = [f'- App "{app.name}" (address name {app.slug}) in {_where(app.space)}; they may: {_may(role(user, app))}']
    for table in app.tables.all():
        fields = data.fields(table)
        lines.append(f'  - Table "{table.name}": ' + '; '.join(_field_line(data, f) for f in fields))
        if with_records:
            records = data.records(table)
            shown = [f for f in fields if f.type not in ('attachment', 'button', 'json')][:8]
            for r in records[:SAMPLE_RECORDS]:
                values = {f.name: data.text(r, f) for f in shown}
                lines.append('      ' + '; '.join(f'{k}: {v}' for k, v in values.items() if v))
            if len(records) > SAMPLE_RECORDS:
                lines.append(f'      … {len(records) - SAMPLE_RECORDS} more records')
    return lines


def _where(space):
    if space is None:
        return 'no space'
    return 'their personal space' if space.is_personal else f'the space {space.key}'


def _may(app_role):
    return {'viewer': 'only look', 'editor': 'change records', 'creator': 'change records, tables and fields'}.get(app_role, 'nothing')


def workspace(user, space=None, app=None, page=None, with_records=False):
    """The part of the prompt that describes what the person can see and do."""
    data = Data(user)
    lines = ['## Their workspace (only what they may see)', '']
    lines.append(f'They {"may" if can_make_spaces(user) else "may not"} make new spaces. They may always make apps in their '
                 'personal space ("personal").')
    lines += ['', 'Spaces:']
    for s in visible_spaces(user):
        if s.is_personal and s.owner_id != user.pk:
            continue
        r = space_role(user, s)
        may = {'admin': 'build apps and write pages', 'editor': 'write pages and change records', 'viewer': 'only look'}[r]
        name = 'personal (their own space)' if s.is_personal else f'{s.key} "{s.name}" ({s.kind})'
        lines.append(f'- {name}; they may: {may}')
    # every app they can see with its fields, the ones the request is about first (with records if asked),
    # until the prompt is big enough; past that, just names
    apps = [a for a in visible_apps(user) if not a.is_space]
    focus = [app] if app else [a for a in apps if space is not None and a.space_id == space.pk]
    lines += ['', 'Apps, with their tables and fields:' if apps else 'Apps: none yet.']
    size, names_only = 0, []
    for a in focus + [a for a in apps if a not in focus]:
        block = _app_block(user, data, a, with_records and a in focus)
        size += sum(len(x) for x in block)
        if size > MAX_CONTEXT:
            names_only.append(a)
            continue
        lines += block
    if names_only:
        lines += ['', 'More apps they can see (too many to list their fields here; to change one, ask them in a question to '
                      'pick it in Osmia as the app the request is about):']
        lines += [f'- "{a.name}" in {_where(a.space)}; they may: {_may(role(user, a))}' for a in names_only[:100]]
    if space is not None:
        try:
            from extensions.pages.models import Page
        except ImportError:
            Page = None
        if Page is not None:
            titles = list(Page.objects.filter(space=space).values_list('title', flat=True)[:100])
            if titles:
                lines += ['', f'Pages in {_where(space)}: ' + '; '.join(f'"{t}"' for t in titles)]
    if page is not None:
        lines += ['', f'The page to change: "{page.title}" in {_where(page.space)}. Its HTML now:', page.body[:MAX_PAGE]]
    return '\n'.join(lines)


def build(user, request_text, space=None, app=None, page=None, with_records=False):
    where = f'They are working in {_where(space)}.' if space else ''
    if app:
        where = f'They are working on the app "{app.name}".'
    if page:
        where = f'They are working on the page "{page.title}".'
    return '\n'.join([
        '# A change to an Osmia workspace',
        '',
        'Osmia is a no-code workspace. Spaces (company, departments, teams, projects, and everyone\'s personal space) hold '
        'apps and pages. An app has tables; a table has typed fields and records (like a spreadsheet or Airtable). '
        'Pages are documents, like Confluence.',
        '',
        '## What they want',
        '',
        request_text.strip(),
        '',
        where,
        '',
        _fmt(),
        workspace(user, space, app, page, with_records),
    ]).strip() + '\n'
