"""Building and changing the workspace: apps, tables, fields and views.

Used by the schema pages, templates (core.blueprints) and extensions. Link
fields come in pairs: adding "Supplier" (orders → vendors) also adds
"Orders" to vendors, and deleting either deletes both.
"""
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from . import formula
from .fieldtypes import TYPES, get_type
from .models import App, Automation, Field, Link, Record, Table, View, unique_slug


def create_app(name, user=None, icon='▦', color='#2e7d5b', description='', blueprint='', blueprint_version='',
               owner=None, default_role=App.Role.VIEWER, group=''):
    slug = unique_slug(name, {s.replace('-', '_') for s in App.objects.values_list('slug', flat=True)}, 'app').replace('_', '-')
    top = App.objects.aggregate(m=Max('position'))['m'] or 0
    return App.objects.create(name=name, slug=slug, icon=icon or '▦', color=color or '#2e7d5b', description=description,
                              group=(group or '').strip()[:60], blueprint=blueprint, blueprint_version=blueprint_version, created_by=user, position=top + 10,
                              owner=owner, default_role=default_role)


@transaction.atomic
def create_table(app, name, icon='', key='', primary='Name', primary_type='text', description=''):
    slug = unique_slug(name, {s.replace('-', '_') for s in app.tables.values_list('slug', flat=True)}, 'table').replace('_', '-')
    top = app.tables.aggregate(m=Max('position'))['m'] or 0
    table = Table.objects.create(app=app, name=name, slug=slug, icon=icon, key=key or slug.replace('-', '_'),
                                 position=top + 1, description=description)
    if primary:
        first = add_field(table, primary, primary_type)
        table.display_field = first
        table.save(update_fields=['display_field'])
    View.objects.create(table=table, name=f'All {name.lower()}', type='grid', position=0)
    return table


def _key_for(table, name, key=''):
    taken = set(table.fields.values_list('key', flat=True))
    if key and key not in taken:
        return key
    return unique_slug(key or name, taken, 'field')


def validate_options(table, ftype, options):
    """Check what a field type needs; returns cleaned options."""
    options = dict(options or {})
    if ftype in ('select', 'multiselect'):
        seen, choices = set(), []
        for c in options.get('choices') or []:
            value = str(c.get('value') if isinstance(c, dict) else c).strip()
            if value and value not in seen:
                seen.add(value)
                choices.append({'value': value, 'color': (c.get('color') if isinstance(c, dict) else '') or ''})
        options['choices'] = choices
        transitions = options.get('transitions') or {}
        options['transitions'] = {k: [v for v in vs if v in seen] for k, vs in transitions.items() if k in seen}
        if not options['transitions']:
            options.pop('transitions')
    if ftype == 'formula':
        problem = formula.check(options.get('expression', ''))
        if problem:
            raise ValidationError(f'The formula has a mistake: {problem}')
    if ftype in ('lookup', 'rollup'):
        link = Field.objects.filter(pk=options.get('link'), table=table, type='link').first()
        if link is None:
            raise ValidationError('Pick a link field of this table to look through.')
        if ftype == 'lookup' or options.get('func', 'sum') != 'count':
            target = Field.objects.filter(pk=options.get('field'), table_id=link.opt('target')).first()
            if target is None:
                raise ValidationError('Pick a field of the linked table.')
        if options.get('filter'):
            problem = formula.check(options['filter'])
            if problem:
                raise ValidationError(f'The filter formula has a mistake: {problem}')
    if ftype == 'link':
        if not Table.objects.filter(pk=options.get('target')).exists():
            raise ValidationError('Pick the table to link to.')
    return options


@transaction.atomic
def app_key(app):
    return app.blueprint or app.slug


def add_field(table, name, ftype='text', options=None, key='', required=False, description='', position=None,
              inverse_name=None, inverse_key='', inverse_multiple=True, origin=''):
    """Add a field. For a link, also adds its pair to the other table
    (named ``inverse_name``, by default the table's name). ``origin``: the app
    adding it, when that isn't the table's own app (see Field.origin)."""
    if ftype not in TYPES:
        raise ValidationError(f'There is no field type "{ftype}".')
    name = (name or '').strip()
    if not name:
        raise ValidationError('A field needs a name.')
    if table.fields.filter(name__iexact=name).exists():
        raise ValidationError(f'{table.name} already has a field called "{name}".')
    options = validate_options(table, ftype, options)
    if position is None:
        position = (table.fields.aggregate(m=Max('position'))['m'] or 0) + 1
    if origin == app_key(table.app):
        origin = ''
    field = Field.objects.create(table=table, name=name, key=_key_for(table, name, key), type=ftype, options=options,
                                 required=required, description=description, position=position, origin=origin)
    if ftype == 'link':
        target = Table.objects.get(pk=options['target'])
        if options.get('inverse') and Field.objects.filter(pk=options['inverse']).exists():
            return field  # pairing with an existing field (templates do this)
        if target.pk == table.pk and inverse_name is None:
            inverse_name = f'{name} of'
        inv_name = inverse_name or table.name
        n, base = 2, inv_name
        while target.fields.filter(name__iexact=inv_name).exists():
            inv_name, n = f'{base} {n}', n + 1
        # the other half belongs with this one: to the app that made the link
        maker = origin or app_key(table.app)
        inverse = Field.objects.create(
            table=target, name=inv_name, key=_key_for(target, inv_name, inverse_key), type='link',
            options={'target': table.pk, 'multiple': inverse_multiple, 'inverse': field.pk, 'owner': False},
            position=(target.fields.aggregate(m=Max('position'))['m'] or 0) + 1,
            origin='' if maker == app_key(target.app) else maker)
        field.options = {**options, 'inverse': inverse.pk, 'owner': True}
        field.save(update_fields=['options'])
    return field


def _convert(field, old_type, new_type):
    """Turn stored values into the new type where they fit; the rest become empty."""
    if old_type == new_type or not get_type(new_type).stored:
        return
    kind = get_type(new_type)
    for record in Record.objects.filter(table=field.table):
        raw = (record.data or {}).get(field.key)
        if raw in (None, '', []):
            continue
        if old_type == 'attributes' and isinstance(raw, list):   # name-value pairs as lines of text
            raw = [{'name': p.get('name', ''), 'value': p.get('value', '')} for p in raw if isinstance(p, dict)]
            if new_type != 'json':
                raw = '\n'.join(f"{p['name']}: {p['value']}" if p['value'] else p['name'] for p in raw)
        if isinstance(raw, list) and new_type not in ('multiselect', 'user', 'json', 'attributes'):
            raw = ', '.join(str(x) for x in raw)
        try:
            value = kind.clean(field, raw)
        except (ValidationError, ValueError, TypeError):
            value = None
        record.data[field.key] = value
        record.save(update_fields=['data'])


@transaction.atomic
def update_field(field, name=None, ftype=None, options=None, required=None, description=None):
    old_name, old_type, old_options = field.name, field.type, dict(field.options or {})
    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError('A field needs a name.')
        if field.table.fields.filter(name__iexact=name).exclude(pk=field.pk).exists():
            raise ValidationError(f'{field.table.name} already has a field called "{name}".')
        field.name = name
    if ftype is not None and ftype != old_type:
        if old_type == 'link' or ftype == 'link':
            raise ValidationError('A link field can\'t change type (and a field can\'t become a link); add a new field instead.')
        field.type = ftype
    if options is not None:
        if field.type == 'link':  # only "multiple" and the label may change
            options = {**old_options, 'multiple': bool(options.get('multiple', old_options.get('multiple')))}
        else:
            options = validate_options(field.table, field.type, options)
        field.options = options
    if required is not None:
        field.required = required
    if description is not None:
        field.description = description
    field.save()
    if field.type != old_type:
        _convert(field, old_type, field.type)
    if field.type in ('select', 'multiselect') and options is not None:
        _rename_choices(field, old_options, field.options)
    if old_name != field.name:
        rename_references(field, old_name, field.name)
    return field


def _rename_choices(field, old_options, new_options):
    """A choice renamed in place (same position, same count) is renamed on every record."""
    old = [c['value'] for c in old_options.get('choices') or []]
    new = [c['value'] for c in new_options.get('choices') or []]
    if len(old) != len(new):
        return
    renames = {a: b for a, b in zip(old, new) if a != b}
    if not renames:
        return
    for record in Record.objects.filter(table=field.table):
        value = (record.data or {}).get(field.key)
        if isinstance(value, list):
            changed = [renames.get(v, v) for v in value]
        else:
            changed = renames.get(value, value)
        if changed != value:
            record.data[field.key] = changed
            record.save(update_fields=['data'])


def _replace_refs(text, old, new):
    if not text or old not in text:
        return text
    # {Old}, {Old.x}, {x.Old}, {x.Old.y}, {old.Old}, {this.Old}, ...
    pattern = re.compile(r'\{([^{}]*)\}')

    def fix(m):
        parts = m.group(1)
        segments = parts.split('.')
        if old in segments:
            return '{' + '.'.join(new if s == old else s for s in segments) + '}'
        if parts == old:
            return '{' + new + '}'
        return m.group(0)
    return pattern.sub(fix, text)


def _walk_strings(value, old, new):
    if isinstance(value, str):
        return _replace_refs(value, old, new)
    if isinstance(value, list):
        return [_walk_strings(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _walk_strings(v, old, new) for k, v in value.items()}
    return value


def rename_references(field, old, new):
    """Keep formulas, rollup filters and automation values working after a rename
    (best effort: any {…} that names the old field by name)."""
    for f in Field.objects.filter(type__in=['formula', 'rollup']):
        changed = _walk_strings(f.options, old, new)
        if changed != f.options:
            f.options = changed
            f.save(update_fields=['options'])
    for a in Automation.objects.all():
        conditions, actions = _walk_strings(a.conditions, old, new), _walk_strings(a.actions, old, new)
        if conditions != a.conditions or actions != a.actions:
            a.conditions, a.actions = conditions, actions
            a.save(update_fields=['conditions', 'actions'])


@transaction.atomic
def delete_field(field, checked=False):
    """Delete a field (a link: both halves). Refused while anything else uses it (core.dependencies)."""
    from . import dependencies
    if not checked:
        dependencies.check(dependencies.field_removal(field))
    _drop_fields(Field.objects.filter(pk__in=dependencies.field_removal(field).fields))


def _drop_fields(fields):
    doomed = list(fields)
    tables = {f.table_id for f in doomed}
    for f in doomed:
        Link.objects.filter(field=f).delete()
        if f.kind.stored:
            for record in Record.objects.filter(table=f.table):
                if f.key in (record.data or {}):
                    record.data.pop(f.key)
                    record.save(update_fields=['data'])
        if f.table.display_field_id == f.pk:
            f.table.display_field = None
            f.table.save(update_fields=['display_field'])
        f.delete()
    for view in View.objects.filter(table_id__in=tables):
        keys = {f.key for f in doomed if f.table_id == view.table_id}
        if keys:
            view.config = _drop_keys(view.config or {}, keys)
            view.save(update_fields=['config'])


def _drop_keys(cfg, keys):
    cfg = dict(cfg)
    for name in ('fields', 'hidden'):
        if isinstance(cfg.get(name), list):
            cfg[name] = [k for k in cfg[name] if k not in keys]
    if isinstance(cfg.get('filters'), dict):
        cfg['filters'] = {**cfg['filters'], 'rules': [r for r in cfg['filters'].get('rules') or [] if r.get('field') not in keys]}
    if isinstance(cfg.get('sorts'), list):
        cfg['sorts'] = [s for s in cfg['sorts'] if s.get('field') not in keys]
    for name in ('group_by', 'group_field', 'start_field', 'end_field', 'date_field', 'parent_field', 'cover_field',
                 'color_field', 'progress_field', 'dependency_field', 'label_field'):
        if cfg.get(name) in keys:
            cfg.pop(name)
    return cfg


@transaction.atomic
def delete_table(table, checked=False):
    """Delete a table and its records. Refused while anything outside it uses it."""
    from . import dependencies
    removal = dependencies.table_removal(table)
    if not checked:
        dependencies.check(removal)
    _drop_fields(Field.objects.filter(pk__in=removal.fields).exclude(table=table))
    table.delete()


@transaction.atomic
def delete_app(app):
    """Delete an app: its tables and records, and what it added to other apps that only works with it.
    The plain fields it added to other apps' tables stay there, as theirs. Refused while
    anything else uses it."""
    from . import dependencies
    removal = dependencies.app_removal(app)
    dependencies.check(removal)
    Field.objects.filter(pk__in=removal.kept).update(origin='')
    Automation.objects.filter(pk__in=removal.automations).exclude(table__app=app).delete()
    _drop_fields(Field.objects.filter(pk__in=removal.fields).exclude(table__app=app))
    for table in list(app.tables.all()):
        table.delete()
    app.delete()


def delete_view(view):
    from . import dependencies
    if view.table.views.count() <= 1:
        raise ValidationError('A table keeps at least one view.')
    dependencies.check(dependencies.view_removal(view))
    view.delete()


def delete_automation(auto):
    from . import dependencies
    dependencies.check(dependencies.automation_removal(auto))
    auto.delete()


def reorder(model, ids):
    for position, pk in enumerate(ids):
        model.objects.filter(pk=pk).update(position=position)
