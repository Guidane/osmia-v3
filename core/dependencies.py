"""What uses what: nothing can be removed while something else still needs it.

Removing an app, a table, a field, a view or an automation is checked first.
If anything outside what's being removed uses it, the removal is refused, and
the message says what uses it, so the person knows what to change first:

    - lookups, rollups and formulas that read the field (by name, also through links)
    - links from other tables to a table being removed
    - automations: their triggers, conditions, steps and buttons
    - views: their filters and the fields they're built on (a kanban's column
      field, a calendar's date, a tree's parent, ...); shown fields and sorts
      are just dropped
    - a tree's parent field
    - pages and space pages showing the view, the record, the field or the app
    - apps installed from templates that need it, and switched-on extensions that need it

What goes *with* something is not in the way: a link's other half, the fields
an app added to other apps' tables that only work with it (links, lookups,
rollups, formulas). Plain fields an app added to another app's table stay
there, as that table's own (see ``app_removal``).
"""
import re
from dataclasses import dataclass, field as dc_field

from django.core.exceptions import ValidationError

from .models import App, Automation, Field, Record, Table, View

VIEW_FIELDS = ('group_by', 'group_field', 'start_field', 'end_field', 'date_field', 'parent_field', 'cover_field',
               'color_field', 'progress_field', 'dependency_field', 'label_field')
COMPUTED = ('lookup', 'rollup', 'formula')
PLACEHOLDER = re.compile(r'\{([^{}]+)\}')


@dataclass
class Removal:
    """What would go: apps, tables, fields, views, automations (ids)."""
    what: str
    apps: set = dc_field(default_factory=set)
    tables: set = dc_field(default_factory=set)
    fields: set = dc_field(default_factory=set)
    views: set = dc_field(default_factory=set)
    automations: set = dc_field(default_factory=set)
    kept: set = dc_field(default_factory=set)     # fields an app added elsewhere that stay behind


def _with_inverse(field):
    ids = {field.pk}
    if field.type == 'link' and field.opt('inverse'):
        ids.add(field.opt('inverse'))
    return ids


def field_removal(field):
    return Removal(what=f'the field {field.name} of {field.table.label}', fields=_with_inverse(field))


def table_removal(table):
    r = Removal(what=f'the table {table.label}', tables={table.pk},
                views=set(View.objects.filter(table=table).values_list('pk', flat=True)),
                automations=set(Automation.objects.filter(table=table).values_list('pk', flat=True)))
    for f in Field.objects.filter(table=table):
        r.fields.add(f.pk)
        if f.type == 'link' and f.opt('owner', True) and f.opt('inverse'):
            r.fields.add(f.opt('inverse'))   # its other half, wherever it is
    return r


def app_removal(app):
    from .schema import app_key
    tables = list(Table.objects.filter(app=app))
    r = Removal(what=f'the app {app.name}', apps={app.pk})
    for t in tables:
        tr = table_removal(t)
        r.tables |= tr.tables
        r.fields |= tr.fields
        r.views |= tr.views
        r.automations |= tr.automations
    key = app_key(app)
    r.automations |= set(Automation.objects.filter(origin=key).exclude(table__app=app).values_list('pk', flat=True))
    for f in Field.objects.filter(origin=key).exclude(table__app=app):
        if f.type in COMPUTED or f.type in ('link', 'button'):
            r.fields |= _with_inverse(f) if f.type == 'link' and f.opt('owner', True) else {f.pk}
        else:
            r.kept.add(f.pk)
    # an app's own link to a table of the app being removed goes with it when it was made by that app
    for f in Field.objects.filter(type='link').exclude(table__app=app):
        if f.opt('target') in r.tables and f.origin == key:
            r.fields |= _with_inverse(f)
    return r


def view_removal(view):
    return Removal(what=f'the view {view.name} of {view.table.label}', views={view.pk})


def automation_removal(auto):
    return Removal(what=f'the automation {auto.name}', automations={auto.pk})


# -- Finding what uses it ----------------------------------------------------------------

def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _names_in(text):
    """Every {a.b.c} in ``text``, as lists of names."""
    return [m.group(1).strip().split('.') for m in PLACEHOLDER.finditer(text or '')]


def _mentions(texts, field, table_ids):
    """Whether formulas/templates in ``texts`` (of a table in ``table_ids``) use ``field`` by name."""
    if not table_ids:
        return False
    for text in texts:
        for parts in _names_in(text):
            joined = '.'.join(parts)
            if field.name in parts or joined == field.name or ('.' in field.name and field.name in joined):
                return True
    return False


def _reachable(table_id, links):
    """Tables whose fields a formula of ``table_id`` can name: its own, and those it links to."""
    return {table_id} | {f.opt('target') for f in links if f.table_id == table_id}


def blockers(removal):
    """What would break: a list of sentences (empty: nothing is in the way)."""
    out = []
    fields = {f.pk: f for f in Field.objects.select_related('table__app')}
    gone = {pk: fields[pk] for pk in removal.fields if pk in fields}
    links = [f for f in fields.values() if f.type == 'link']

    def staying(f):
        return f.pk not in removal.fields and f.table_id not in removal.tables

    # Fields that read what goes
    for f in fields.values():
        if not staying(f):
            continue
        if f.type in ('lookup', 'rollup') and (f.opt('link') in gone or f.opt('field') in gone):
            out.append(f'The {f.type} field {f.name} of {f.table.label} reads it.')
            continue
        if f.type == 'link' and f.opt('target') in removal.tables and f.pk not in removal.fields:
            out.append(f'The link field {f.name} of {f.table.label} links to {fields_table(removal, f)}.')
            continue
        texts = []
        if f.type == 'formula':
            texts.append(f.opt('expression', ''))
        if f.type == 'rollup' and f.opt('filter'):
            texts.append(f.opt('filter'))
        if texts:
            for g in gone.values():
                if g.table_id in _reachable(f.table_id, links) or (f.type == 'rollup' and g.table_id == _target_of(fields, f)):
                    if _mentions(texts, g, {f.table_id}):
                        out.append(f'The {f.type} field {f.name} of {f.table.label} uses {g.name}.')
                        break

    # Trees
    for t in Table.objects.filter(tree_field_id__in=list(gone)).exclude(pk__in=removal.tables):
        out.append(f'{t.label} is a tree with {t.tree_field.name} as each record\'s parent (Table settings).')

    # Automations
    for a in Automation.objects.select_related('table__app'):
        if a.pk in removal.automations or a.table_id in removal.tables:
            continue
        why = _automation_uses(a, removal, gone, fields, links)
        if why:
            out.append(f'The automation "{a.name}" of {a.table.app.name} {why}.')
    for f in fields.values():
        if staying(f) and f.type == 'button' and f.opt('automation') in removal.automations:
            out.append(f'The button {f.name} of {f.table.label} runs it.')

    # Views
    for v in View.objects.select_related('table__app'):
        if v.pk in removal.views or v.table_id in removal.tables:
            continue
        cfg = v.config or {}
        keys = {g.key for g in gone.values() if g.table_id == v.table_id}
        if not keys:
            continue
        used = [cfg.get(n) for n in VIEW_FIELDS if cfg.get(n) in keys]
        used += [r.get('field') for r in (cfg.get('filters') or {}).get('rules') or [] if r.get('field') in keys]
        if used:
            out.append(f'The view {v.name} of {v.table.label} is built on it (its settings or filters).')

    # Pages
    from .canvas.references import used_in
    out.extend(used_in(removal, gone))
    from .extensions import registry
    for fn in registry.dependency_checks:
        out.extend(fn(removal, gone) or [])

    # Apps made from templates, and extensions, that need it
    out.extend(_needed_by_apps_and_extensions(removal))
    seen, unique = set(), []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def fields_table(removal, f):
    t = Table.objects.filter(pk=f.opt('target')).select_related('app').first()
    return t.label if t else 'it'


def _target_of(fields, rollup):
    link = fields.get(rollup.opt('link'))
    return link.opt('target') if link else None


def _automation_uses(a, removal, gone, fields, links):
    keys_here = {g.key for g in gone.values() if g.table_id == a.table_id}
    if set(a.trigger_config.get('fields') or []) & keys_here:
        return 'runs when it changes'
    rules = (a.conditions or {}).get('rules') or []
    if any(r.get('field') in keys_here for r in rules):
        return 'has a condition on it'
    for step in a.actions or []:
        table_id = step.get('table')
        if table_id in removal.tables:
            return 'makes or finds records in it'
        if step.get('type') == 'run_automation' and step.get('automation') in removal.automations:
            return 'runs it'
        step_keys = keys_here
        if table_id:
            step_keys = keys_here | {g.key for g in gone.values() if g.table_id == table_id}
        for name in ('values', 'match', 'update'):
            if isinstance(step.get(name), dict) and set(step[name]) & step_keys:
                return 'sets it'
        for name in ('for_each', 'save_to'):
            if step.get(name) in keys_here:
                return 'goes through it'
        target = step.get('target') or ''
        if target.startswith('link:') and target[5:].split('.')[-1] in keys_here:
            return 'changes records through it'
        if set(step.get('user_fields') or []) & keys_here:
            return 'tells the people in it'
    texts = list(_strings(a.conditions)) + list(_strings(a.actions))
    for g in gone.values():
        if g.table_id in _reachable(a.table_id, links) and _mentions(texts, g, {a.table_id}):
            return f'uses {g.name} in a formula or message'
    return ''


def _needed_by_apps_and_extensions(removal):
    from . import blueprints
    from .extensions import all_extensions, requirement_parts
    from .schema import app_key
    out = []
    removed_keys = {app_key(a) for a in App.objects.filter(pk__in=removal.apps)}
    tables = {t.pk: t for t in Table.objects.filter(pk__in=removal.tables).select_related('app')}
    fields = {f.pk: f for f in Field.objects.filter(pk__in=removal.fields).select_related('table__app')}
    if removed_keys:
        catalog = blueprints.available(include_hidden=True)
        for app in App.objects.exclude(pk__in=removal.apps).exclude(blueprint=''):
            needs = set((catalog.get(app.blueprint) or {}).get('requires') or [])
            if needs & removed_keys:
                out.append(f'The app {app.name} needs it (its template requires {", ".join(sorted(needs & removed_keys))}).')
    for ext in all_extensions():
        if not ext.enabled:
            continue
        for req in ext.requires:
            app_k, table_k, field_k = requirement_parts(req)
            hit = app_k in removed_keys
            hit = hit or any(app_key(t.app) == app_k and t.key == table_k and not field_k for t in tables.values())
            hit = hit or any(app_key(f.table.app) == app_k and f.table.key == table_k and f.key == field_k
                             for f in fields.values())
            if hit:
                out.append(f'The extension {ext.title} needs it ({req}). Switch the extension off first.')
                break
    return out


def check(removal):
    found = blockers(removal)
    if found:
        raise ValidationError([f'{removal.what[0].upper()}{removal.what[1:]} can\'t be removed while something uses it:']
                              + found)


def record_ids_of(removal):
    return set(Record.objects.filter(table_id__in=removal.tables).values_list('pk', flat=True))
