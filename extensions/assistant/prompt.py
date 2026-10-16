"""The prompt Osmia gives an AI: the person's request, how to answer, and their workspace.

Only what the person may see goes in: the trees of spaces and the apps they can
look at, the fields of the chosen app (or every app, as far as the prompt has room),
and, if they ask for it, some of the records and the page being changed. Records and
pages they can't see (access tags) are never in it. Whatever is in it goes to the AI
they paste it into, so the page says so.
"""
import re

from core import space as spaces
from core.data import Data
from core.fieldtypes import ROLLUPS, TYPES
from core.permissions import can, role, visible_apps
from core.trees import Tree

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

{"do": "add_space", "tree": "Organisation", "name": "Operations", "parent": "Company", "values": {"Kind": "Department"}}
    a space is a record of a tree of spaces (listed below); "parent" is the space it goes under (none: at the top).
{"do": "create_app", "name": "Suppliers", "icon": "🏭", "description": "...", "own": false,
 "tables": [{"name": "Suppliers", "fields": [FIELD, ...], "views": [VIEW, ...], "records": [RECORD, ...]}, ...]}
    own: true makes it the person's own app (only administrators make apps for everyone).
    The first field of a table is its name field. To tie records to a space, give the table a link to the tree of
    spaces (e.g. "target": "Projects › Projects"): records then carry that space's access tags.
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
{"do": "create_page", "space": "Operations", "title": "Supplier handbook", "parent": "title of a page to put it under", "emoji": "📘", "body": "HTML"}
{"do": "update_page", "space": "Operations", "page": "Supplier handbook", "title": "...", "body": "HTML (replaces it)", "append": "HTML (added at the end)"}
    pages are documentation (the Documentation app): explanations for people. Data that is listed, counted or
    linked belongs in an app's records, never in a page. space: a space's name, or "home" for the person's own.

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
    values = {'TYPES': ', '.join(f'{k} ({TYPES[k].label})' for k in field_types()),
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
    whose = f'the own app of {app.owner}' if app.owner_id else 'for everyone'
    lines = [f'- App "{app.name}" (address name {app.slug}), {whose}; they may: {_may(role(user, app))}']
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


def _label(data, space):
    return data.label(space) if space is not None else ''


def _may(app_role):
    return {'viewer': 'only look', 'editor': 'change records', 'creator': 'change records, tables and fields'}.get(app_role, 'nothing')


def workspace(user, space=None, app=None, page=None, with_records=False):
    """The part of the prompt that describes what the person can see and do."""
    data = Data(user)
    lines = ['## Their workspace (only what they may see)', '']
    home = spaces.home_node(user, create=False)
    if home is not None and data.record(home.pk) is not None:
        lines.append(f'Their home space is "{data.label(home)}".')
    trees = [t for t in spaces.space_tables() if can(user, t.app, 'viewer')]
    if trees:
        lines += ['', 'Trees of spaces (a space is a record; records of other tables link to spaces):']
        for table in trees:
            t = Tree(data, table)
            rows = []

            def walk(node, depth):
                if len(rows) < 80:
                    rows.append('  ' * depth + f'- {data.label(node)}')
                    for kid in t.kids(node.pk):
                        walk(kid, depth + 1)
            for root in t.roots():
                walk(root, 1)
            may = 'add spaces' if can(user, table.app, 'editor') else 'only look'
            lines.append(f'- "{table.name}" (in the app {table.app.name}); they may: {may}')
            lines += rows
    # every app they can see with its fields, the one the request is about first (with records if asked),
    # until the prompt is big enough; past that, just names
    apps = visible_apps(user)
    focus = [app] if app else []
    lines += ['', 'Apps, with their tables and fields:' if apps else 'Apps: none yet.']
    size, names_only = 0, []
    for a in focus + [a for a in apps if a not in focus]:
        block = _app_block(user, data, a, with_records and (a in focus or not focus))
        size += sum(len(x) for x in block)
        if size > MAX_CONTEXT:
            names_only.append(a)
            continue
        lines += block
    if names_only:
        lines += ['', 'More apps they can see (too many to list their fields here; to change one, ask them in a question to '
                      'pick it in Osmia as the app the request is about):']
        lines += [f'- "{a.name}"; they may: {_may(role(user, a))}' for a in names_only[:100]]
    if space is not None:
        try:
            from extensions.docs.models import Page
            from extensions.docs.service import visible_pages
        except ImportError:
            Page = None
        if Page is not None:
            titles = [p.title for p in visible_pages(user, Page.objects.filter(space=space))[:100]]
            if titles:
                lines += ['', f'Pages of the space "{_label(data, space)}": ' + '; '.join(f'"{t}"' for t in titles)]
    if page is not None:
        lines += ['', f'The page to change: "{page.title}" in the space "{_label(data, page.space)}". Its HTML now:', page.body[:MAX_PAGE]]
    return '\n'.join(lines)


def build(user, request_text, space=None, app=None, page=None, with_records=False):
    where = f'They are working in the space "{_label(Data(user), space)}".' if space else ''
    if app:
        where = f'They are working on the app "{app.name}".'
    if page:
        where = f'They are working on the page "{page.title}".'
    return '\n'.join([
        '# A change to an Osmia workspace',
        '',
        'Osmia is a no-code workspace. Apps hold the data: an app has tables, a table has typed fields and records, '
        'like a spreadsheet with links between tables. Trees give it structure: an organisation (company, departments, '
        'teams, people) and programmes and projects are trees of spaces, and records link to the spaces they belong '
        'with. Everyone has a home space. The Documentation app holds pages: explanations for people to read, which '
        'can show records and views live. Access tags decide who sees which records.',
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
