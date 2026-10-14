"""Changes an AI proposes, as JSON, checked and made with the person's own permissions.

    {"osmia": 1, "summary": "Adds a suppliers app", "changes": [{"do": "create_app", ...}, ...]}

``run(plan, user)`` tries every change for real inside a transaction, with automations
paused, and then undoes it all: what it reports is what applying will do, problems
included. ``run(plan, user, apply=True)`` makes them all, or none if one fails.

Everything goes through the code the website uses (templates, core.schema,
core.service, Pages' write_page), so the same rules and checks apply. A change never
deletes anything: there is no change for it.
"""
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from core import automation, blueprints, schema, service, space as spaces
from core.data import Data
from core.fieldtypes import ROLLUPS, TYPES
from core.models import App, Space, Table, View
from core.permissions import can, can_make_spaces, can_space, visible_apps

MAX_ANSWER = 300_000      # characters of a pasted answer
MAX_CHANGES = 50          # changes in one answer
MAX_RECORDS = 200         # records one change adds or changes
COMPUTED = ('lookup', 'rollup', 'formula')
VIEWS = ('grid', 'kanban', 'gallery', 'calendar')
SPACE_KINDS = [k for k in Space.Kind.values if k != Space.Kind.PERSONAL]
SOURCE = 'AI assistant'   # what the history says made the change


def field_types():
    """The field types an AI may add (buttons need automations; JSON is for programs)."""
    return [k for k in TYPES if k not in ('button', 'json')]


def _type_of(spec):
    return str(spec.get('type') or 'text').strip().lower() if isinstance(spec, dict) else ''


class PlanError(Exception):
    """The answer (or one change in it) isn't something Osmia can do."""


class _Undo(Exception):
    pass


@dataclass
class Step:
    n: int
    do: str
    text: str = ''
    url: str = ''
    error: str = ''

    @property
    def ok(self):
        return not self.error


# -- Reading the answer --------------------------------------------------------------------

def parse(answer):
    """The plan in an AI's answer (a ```json block, or the outermost {...})."""
    answer = (answer or '').strip()
    if not answer:
        raise PlanError('Paste the AI\'s answer first.')
    if len(answer) > MAX_ANSWER:
        raise PlanError(f'The answer is longer than {MAX_ANSWER:,} characters; ask for fewer changes at a time.')
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', answer, re.S)
    raw = m.group(1) if m else answer[answer.find('{'):answer.rfind('}') + 1]
    if not raw:
        raise PlanError('There is no JSON in the answer. The AI should answer with one JSON object.')
    try:
        plan = json.loads(raw)
    except ValueError as e:
        raise PlanError(f'The JSON has a mistake: {e}.')
    if not isinstance(plan, dict):
        raise PlanError('The answer should be one JSON object: {"osmia": 1, "changes": [...]}.')
    if isinstance(plan.get('question'), str) and plan['question'].strip() and not plan.get('changes'):
        return plan
    changes = plan.get('changes')
    if not isinstance(changes, list) or not changes:
        raise PlanError('The answer has no "changes" list.')
    if len(changes) > MAX_CHANGES:
        raise PlanError(f'The answer has {len(changes)} changes; at most {MAX_CHANGES} at a time.')
    for n, change in enumerate(changes, 1):
        if not isinstance(change, dict) or change.get('do') not in OPS:
            raise PlanError(f'Change {n}: "do" must be one of {", ".join(OPS)}.')
    return plan


# -- Finding things by name ----------------------------------------------------------------

def _text(change, key, required=True, limit=200):
    value = change.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise PlanError(f'"{key}" is missing.')
        return ''
    if not isinstance(value, (str, int, float)):
        raise PlanError(f'"{key}" should be text.')
    return str(value).strip()[:limit]


def _list(change, key, required=True):
    value = change.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        raise PlanError(f'"{key}" should be a list.')
    return value


def _same(a, b):
    return str(a).strip().lower() == str(b).strip().lower()


class Runner:
    def __init__(self, user):
        self.user = user
        self.made = []    # what this plan made, for the summary

    def data(self):
        return Data(self.user)   # fresh: earlier changes may have changed the schema

    def space(self, ref, needed):
        ref = str(ref or '').strip()
        if ref.lower() in ('', 'personal', 'my space', 'me'):
            space = spaces.ensure_personal(self.user)
        else:
            found = [s for s in Space.objects.exclude(kind=Space.Kind.PERSONAL)
                     if (_same(s.key, ref) or _same(s.name, ref)) and can_space(self.user, s, 'viewer')]
            if not found:
                raise PlanError(f'There is no space "{ref}" you can see.')
            if len(found) > 1:
                raise PlanError(f'More than one space is called "{ref}"; use its key: {", ".join(s.key for s in found)}.')
            space = found[0]
        if not can_space(self.user, space, needed):
            what = {'editor': 'write in', 'admin': 'build in (only its admins can)'}[needed]
            raise PermissionDenied(f'You may not {what} the space {space.name}.')
        return space

    def app(self, change, needed='creator'):
        ref = _text(change, 'app')
        found = [a for a in visible_apps(self.user) if not a.is_space and (_same(a.name, ref) or _same(a.slug, ref))]
        if len(found) > 1 and change.get('space'):
            found = [a for a in found if a.space and (_same(a.space.key, change['space']) or _same(a.space.name, change['space']))]
        if not found:
            raise PlanError(f'There is no app "{ref}" you can see.')
        if len(found) > 1:
            raise PlanError(f'More than one app is called "{ref}"; add "space" (one of '
                            f'{", ".join(a.space.key if a.space else "?" for a in found)}) or use its address name '
                            f'({", ".join(a.slug for a in found)}).')
        app = found[0]
        if not can(self.user, app, needed):
            what = {'editor': 'change records of', 'creator': 'change the tables and fields of'}[needed]
            raise PermissionDenied(f'You may not {what} {app.name}.')
        return app

    def table(self, app, ref):
        ref = str(ref or '').strip()
        found = next((t for t in app.tables.all() if _same(t.name, ref) or _same(t.key, ref) or _same(t.slug, ref)), None)
        if found is None:
            raise PlanError(f'{app.name} has no table "{ref}". Its tables: {", ".join(t.name for t in app.tables.all())}.')
        return found

    def table_anywhere(self, ref, here, needed='creator'):
        """'Table' (in app ``here``) or 'App › Table' / 'App > Table' / 'App / Table'."""
        ref = str(ref or '').strip()
        parts = re.split(r'\s*(?:›|>|/)\s*', ref, maxsplit=1)
        if len(parts) == 2:
            app = self.app({'app': parts[0]}, needed)
            return self.table(app, parts[1])
        return self.table(here, ref)

    def field(self, table, ref, data=None):
        data = data or self.data()
        found = data.field_named(table, str(ref or ''))
        if found is None:
            raise PlanError(f'{table.name} has no field "{ref}". Its fields: {", ".join(f.name for f in data.fields(table))}.')
        return found

    # -- fields --------------------------------------------------------------------------

    def field_options(self, table, spec):
        """(type, options, inverse name) of a field spec, with names turned into ids."""
        ftype = _type_of(spec)
        if ftype not in field_types():
            raise PlanError(f'Field "{spec.get("name")}": there is no field type "{ftype}". Types: {", ".join(field_types())}.')
        options = {k: v for k, v in (spec.get('options') or {}).items() if isinstance(v, (str, int, float, bool))}
        if ftype in ('select', 'multiselect'):
            choices = spec.get('choices', (spec.get('options') or {}).get('choices'))
            if not isinstance(choices, list) or not choices:
                raise PlanError(f'Field "{spec.get("name")}": a {ftype} field needs "choices": ["...", "..."].')
            options['choices'] = [c if isinstance(c, dict) else {'value': str(c)} for c in choices]
        elif ftype == 'link':
            target = self.table_anywhere(spec.get('target') or options.get('target'), table.app)
            options.update(target=target.pk, multiple=bool(spec.get('multiple', True)))
        elif ftype == 'formula':
            options['expression'] = str(spec.get('expression') or options.get('expression') or '')
        elif ftype in ('lookup', 'rollup'):
            data = self.data()
            link = self.field(table, spec.get('link') or options.get('link'), data)
            if link.type != 'link':
                raise PlanError(f'Field "{spec.get("name")}": "{link.name}" is not a link field.')
            options['link'] = link.pk
            func = str(spec.get('func') or options.get('func') or 'sum') if ftype == 'rollup' else None
            if func is not None:
                if func not in ROLLUPS:
                    raise PlanError(f'Field "{spec.get("name")}": "func" is one of {", ".join(ROLLUPS)}.')
                options['func'] = func
            if ftype == 'lookup' or func != 'count':
                target = Table.objects.get(pk=link.opt('target'))
                options['field'] = self.field(target, spec.get('field') or options.get('field'), data).pk
        elif ftype == 'user':
            options['multiple'] = bool(spec.get('multiple', False))
        return ftype, options, spec.get('inverse_name') or None

    def add_field(self, table, spec):
        if not isinstance(spec, dict):
            raise PlanError('A field is {"name": "...", "type": "..."}.')
        name = _text(spec, 'name', limit=100)
        ftype, options, inverse = self.field_options(table, spec)
        try:
            return schema.add_field(table, name, ftype, options, required=bool(spec.get('required')),
                                    description=str(spec.get('description') or '')[:300], inverse_name=inverse)
        except ValidationError as e:
            raise ValidationError([f'Field "{name}": {m}' for m in e.messages])

    def add_fields(self, tables_specs):
        """Fields for [(table, [spec])]: stored fields and links first, then the computed ones
        that look through them, in whatever order they depend on each other (a rollup of a
        rollup in another table)."""
        for table, specs in tables_specs:
            if not isinstance(specs, list):
                raise PlanError('"fields" should be a list of {"name": "...", "type": "..."}.')
            for spec in specs:
                if _type_of(spec) not in COMPUTED:
                    self.add_field(table, spec)
        pending = [(table, spec) for table, specs in tables_specs for spec in specs if _type_of(spec) in COMPUTED]
        while pending:
            left = []
            for table, spec in pending:
                try:
                    with transaction.atomic():
                        self.add_field(table, spec)
                except PlanError as e:   # e.g. it reads a computed field that isn't made yet
                    left.append((table, spec, e))
            if len(left) == len(pending):
                raise left[0][2]
            pending = [(table, spec) for table, spec, _ in left]

    # -- records -------------------------------------------------------------------------

    def add_records(self, table, rows):
        if not isinstance(rows, list):
            raise PlanError('"records" should be a list of {"Field name": value}.')
        if len(rows) > MAX_RECORDS:
            raise PlanError(f'At most {MAX_RECORDS} records in one change.')
        data = self.data()
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise PlanError(f'Record {i} should be {{"Field name": value}}.')
            try:
                service.create_record(table, row, user=self.user, data=data)
            except ValidationError as e:
                raise ValidationError([f'Record {i}: {m}' for m in e.messages])
        return len(rows)

    def view(self, table, spec):
        if not isinstance(spec, dict):
            raise PlanError('A view is {"name": "...", "type": "kanban", "group_by": "Status"}.')
        vtype = str(spec.get('type') or 'grid').lower()
        if vtype not in VIEWS:
            raise PlanError(f'View "{spec.get("name")}": the type is one of {", ".join(VIEWS)}.')
        config = {}
        if vtype == 'kanban':
            group = self.field(table, spec.get('group_by'))
            if group.type not in ('select', 'user', 'link'):
                raise PlanError(f'View "{spec.get("name")}": a kanban groups by a select, user or link field.')
            config['group_field'] = group.key
        if vtype == 'calendar':
            date = self.field(table, spec.get('date'))
            if date.type not in ('date', 'datetime'):
                raise PlanError(f'View "{spec.get("name")}": a calendar needs a date field in "date".')
            config['date_field'] = date.key
        name = _text(spec, 'name', required=False, limit=100) or vtype.title()
        return View.objects.create(table=table, name=name, type=vtype, config=config, position=table.views.count())


# -- The changes -------------------------------------------------------------------------
# Each takes (runner, change) and returns (what it did, a link to it).

def create_space(r, c):
    if not can_make_spaces(r.user):
        raise PermissionDenied('Making spaces needs the "Can make spaces" permission; ask an administrator.')
    name = _text(c, 'name', limit=100)
    key = _text(c, 'key', required=False, limit=20).upper()
    if key and not key.replace('_', '').isalnum():
        raise PlanError('A space key is letters and digits only, e.g. OPS.')
    if key and Space.objects.filter(key__iexact=key).exists():
        raise PlanError(f'The space key {key} is taken; pick another.')
    kind = str(c.get('kind') or 'team').lower()
    if kind not in SPACE_KINDS:
        raise PlanError(f'"kind" is one of {", ".join(SPACE_KINDS)}.')
    visibility = str(c.get('visibility') or 'internal').lower()
    if visibility not in Space.Visibility.values:
        raise PlanError('"visibility" is "internal" (everyone can look) or "private" (members only).')
    space = spaces.create_space(name, r.user, key=key, kind=kind, visibility=visibility,
                                description=str(c.get('description') or ''), icon=str(c.get('icon') or '')[:8])
    return f'Make the {kind} space {space.name} ({space.key}), {Space.Visibility(visibility).label.lower()}', space.get_absolute_url()


def create_app(r, c):
    name = _text(c, 'name', limit=100)
    target = r.space(c.get('space'), 'admin')
    personal = target.is_personal
    tables = _list(c, 'tables')
    names = set()
    for t in tables:
        if not isinstance(t, dict) or not str(t.get('name') or '').strip():
            raise PlanError('Each table needs a "name".')
        if t['name'].strip().lower() in names:
            raise PlanError(f'Two tables are called "{t["name"]}".')
        names.add(t['name'].strip().lower())
    app = schema.create_app(name, r.user, icon=str(c.get('icon') or '▦')[:8], description=str(c.get('description') or ''),
                            owner=r.user if personal else None,
                            default_role=App.Role.NONE if personal else App.Role.VIEWER, space=target)
    # every table first (links point at them), then fields, then views and records
    made = [(schema.create_table(app, str(t['name']).strip()[:100], icon=str(t.get('icon') or '')[:8], primary=None,
                                 description=str(t.get('description') or '')), t) for t in tables]
    r.add_fields([(table, t.get('fields') or [{'name': 'Name', 'type': 'text'}]) for table, t in made])
    for table, t in made:
        first = r.field(table, t['display']) if t.get('display') else table.fields.order_by('position', 'id').first()
        table.display_field = first
        table.save(update_fields=['display_field'])
    parts = []
    for table, t in made:
        for v in _list(t, 'views', required=False):
            r.view(table, v)
        n = r.add_records(table, t['records']) if t.get('records') else 0
        parts.append(f'{table.name} ({table.fields.count()} fields{f", {n} records" if n else ""})')
    where = 'your personal space' if personal else target.name
    return f'Make the app {app.name} in {where}: {", ".join(parts)}', app.get_absolute_url()


def change_app(r, c):
    app = r.app(c)
    old = app.name
    if c.get('name'):
        app.name = _text(c, 'name', limit=100)
    if c.get('icon'):
        app.icon = str(c['icon'])[:8]
    if 'description' in c:
        app.description = str(c.get('description') or '')
    app.save()
    return f'Change the app {old}' + (f' (now called {app.name})' if app.name != old else ''), app.get_absolute_url()


def add_table(r, c):
    app = r.app(c)
    name = _text(c, 'name', limit=100)
    if app.tables.filter(name__iexact=name).exists():
        raise PlanError(f'{app.name} already has a table called "{name}".')
    table = schema.create_table(app, name, icon=str(c.get('icon') or '')[:8], primary=None, description=str(c.get('description') or ''))
    r.add_fields([(table, c.get('fields') or [{'name': 'Name', 'type': 'text'}])])
    table.display_field = r.field(table, c['display']) if c.get('display') else table.fields.order_by('position', 'id').first()
    table.save(update_fields=['display_field'])
    for v in _list(c, 'views', required=False):
        r.view(table, v)
    n = r.add_records(table, c['records']) if c.get('records') else 0
    return (f'Add the table {table.name} to {app.name} ({table.fields.count()} fields{f", {n} records" if n else ""})',
            table.get_absolute_url())


def add_field(r, c):
    app = r.app(c)
    table = r.table(app, c.get('table'))
    spec = c.get('field') if isinstance(c.get('field'), dict) else c
    field = r.add_field(table, spec)
    return f'Add the field {field.name} ({TYPES[field.type].label}) to {app.name} › {table.name}', table.get_absolute_url()


def change_field(r, c):
    app = r.app(c)
    table = r.table(app, c.get('table'))
    field = r.field(table, c.get('field'))
    old = field.name
    ftype = str(c['type']).lower() if c.get('type') else None
    if ftype is not None and ftype not in field_types():
        raise PlanError(f'There is no field type "{ftype}".')
    options = None
    if 'choices' in c:
        colors = {ch['value']: ch.get('color', '') for ch in field.opt('choices') or []}
        options = {**(field.options or {}), 'choices': [{'value': str(v), 'color': colors.get(str(v), '')} for v in _list(c, 'choices')]}
    if 'expression' in c:
        options = {**(options or field.options or {}), 'expression': str(c['expression'])}
    schema.update_field(field, name=_text(c, 'name', limit=100) if c.get('name') else None, ftype=ftype, options=options,
                        required=bool(c['required']) if 'required' in c else None,
                        description=str(c['description'])[:300] if 'description' in c else None)
    what = [f'renamed to {field.name}'] if field.name != old else []
    what += [f'now {TYPES[field.type].label}'] if ftype else []
    what += ['new choices'] if 'choices' in c else []
    what += ['new formula'] if 'expression' in c else []
    return f'Change the field {old} of {app.name} › {table.name}' + (f' ({", ".join(what)})' if what else ''), table.get_absolute_url()


def add_view(r, c):
    app = r.app(c)
    table = r.table(app, c.get('table'))
    view = r.view(table, c)
    return f'Add the {view.type} view {view.name} to {app.name} › {table.name}', view.get_absolute_url()


def add_records(r, c):
    app = r.app(c, 'editor')
    table = r.table(app, c.get('table'))
    n = r.add_records(table, c.get('records'))
    return f'Add {n} record{"s" if n != 1 else ""} to {app.name} › {table.name}', table.get_absolute_url()


def update_records(r, c):
    app = r.app(c, 'editor')
    table = r.table(app, c.get('table'))
    where, values = c.get('where'), c.get('set')
    if not isinstance(where, dict) or not where:
        raise PlanError('"where" says which records: {"Field name": "value"}.')
    if not isinstance(values, dict) or not values:
        raise PlanError('"set" says what to change: {"Field name": "new value"}.')
    data = r.data()
    wanted = [(r.field(table, k, data), v) for k, v in where.items()]
    found = [rec for rec in data.records(table) if all(_same(data.text(rec, f), v) for f, v in wanted)]
    if not found:
        raise PlanError(f'No record of {table.name} has {", ".join(f"{f.name} = {v}" for f, v in wanted)}.')
    if len(found) > MAX_RECORDS:
        raise PlanError(f'{len(found)} records match; at most {MAX_RECORDS} in one change.')
    for rec in found:
        try:
            service.update_record(rec, values, user=r.user, data=data)
        except ValidationError as e:
            raise ValidationError([f'{data.label(rec)}: {m}' for m in e.messages])
    return (f'Change {len(found)} record{"s" if len(found) != 1 else ""} of {app.name} › {table.name}: '
            f'{", ".join(f"{k} → {v}" for k, v in values.items())}', table.get_absolute_url())


def _pages():
    from core.extensions import registry
    if 'pages' not in registry.extensions:
        raise PlanError('Pages are switched off on this Osmia.')
    from extensions.pages.models import Page
    from extensions.pages.service import write_page
    return Page, write_page


def _page(r, Page, c):
    space = r.space(c.get('space'), 'editor')
    ref = c.get('page')
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        page = Page.objects.filter(pk=int(ref), space=space).first()
    else:
        page = next((p for p in Page.objects.filter(space=space) if _same(p.title, ref)), None)
    if page is None:
        raise PlanError(f'The space {space.name} has no page "{ref}".')
    return space, page


def create_page(r, c):
    Page, write_page = _pages()
    space = r.space(c.get('space'), 'editor')
    parent = None
    if c.get('parent'):
        parent = next((p for p in Page.objects.filter(space=space) if _same(p.title, c['parent'])), None)
        if parent is None:
            raise PlanError(f'The space {space.name} has no page "{c["parent"]}" to put it under.')
    page, _ = write_page(space, r.user, _text(c, 'title'), str(c.get('body') or ''), parent=parent,
                         emoji=str(c.get('emoji') or ''), labels=str(c.get('labels') or ''))
    return f'Write the page {page.title} in {"your personal space" if space.is_personal else space.name}', page.get_absolute_url()


def update_page(r, c):
    Page, write_page = _pages()
    space, page = _page(r, Page, c)
    body = str(c['body']) if 'body' in c else page.body
    if c.get('append'):
        body += str(c['append'])
    title = _text(c, 'title') if c.get('title') else page.title
    page, changed = write_page(space, r.user, title, body, page=page, parent=page.parent,
                               emoji=str(c['emoji']) if 'emoji' in c else page.emoji,
                               labels=str(c['labels']) if 'labels' in c else page.labels, note=f'Changed by the {SOURCE}')
    return f'Change the page {page.title}' + ('' if changed else ' (nothing to change)'), page.get_absolute_url()


OPS = {
    'create_space': create_space, 'create_app': create_app, 'change_app': change_app,
    'add_table': add_table, 'add_field': add_field, 'change_field': change_field, 'add_view': add_view,
    'add_records': add_records, 'update_records': update_records,
    'create_page': create_page, 'update_page': update_page,
}


def _guess(change):
    """What a change meant to do, when it couldn't."""
    what = change.get('do', '').replace('_', ' ')
    name = change.get('name') or change.get('title') or change.get('page') or change.get('field') or change.get('table') or ''
    if isinstance(change.get('field'), dict):
        name = change['field'].get('name', '')
    return f'{what[:1].upper()}{what[1:]} {name}'.strip()


# -- Running ------------------------------------------------------------------------------

def run(plan, user, apply=False):
    """[Step] for every change. Checking (apply=False) undoes everything afterwards;
    applying keeps it only if every change worked."""
    runner, steps = Runner(user), []
    try:
        with transaction.atomic(), (nullcontext() if apply else automation.paused()), service.acting(SOURCE):
            for n, change in enumerate(plan['changes'], 1):
                step = Step(n, change['do'])
                try:
                    with transaction.atomic():
                        step.text, step.url = OPS[change['do']](runner, change)
                except PermissionDenied as e:
                    step.error = str(e) or 'You may not do that.'
                except ValidationError as e:
                    step.error = ' '.join(e.messages)
                except PlanError as e:
                    step.error = str(e)
                except IntegrityError:
                    step.error = 'It clashes with something that is already there (a name or a key that is taken).'
                except (TypeError, AttributeError, KeyError, ValueError) as e:
                    step.error = f'The change isn\'t in the right shape ({type(e).__name__}: {e}).'
                if step.error:
                    step.text = _guess(change)
                steps.append(step)
            if not apply or any(s.error for s in steps):
                raise _Undo
    except _Undo:
        pass
    if not apply:
        for s in steps:
            s.url = ''   # what checking made is gone again
    return steps


def fix_message(steps, problem=''):
    """What to tell the AI so it can fix its answer."""
    lines = ['Osmia could not use your answer.']
    if problem:
        lines.append(f'Problem: {problem}')
    for s in steps:
        if s.error:
            lines.append(f'- Change {s.n} ({s.do}): {s.error}')
    if any(s.ok for s in steps):
        lines.append('The other changes were fine.')
    lines.append('Send the whole JSON again with these fixed, in the same format.')
    return '\n'.join(lines)
