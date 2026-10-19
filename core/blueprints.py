"""App templates ("blueprints"): an app's tables, fields, views and
automations (and sample records) as one JSON file.

The templates that come with Osmia are in ``blueprints/``; extensions bring
their own. Administrators install them on the Templates page, upload others,
and download any app as a template to install it on another Osmia.

    {"key": "orders", "name": "Orders", "icon": "🧾", "version": "1.0.0",
     "requires": ["parts", "vendors"],            templates that must be installed first
     "tables": [{"key": "orders", "name": "Orders", "display": "number",
                 "tree": "parent", "spaces": true,          a tree by its "parent" link; its records are spaces
                 "fields": [{"key": "supplier", "name": "Supplier", "type": "link",
                             "options": {"target": "vendors.vendors", "multiple": false,
                                         "inverse": {"key": "orders", "name": "Orders", "multiple": true}}},
                            {"key": "total", "name": "Total", "type": "rollup",
                             "options": {"link": "lines", "field": "total", "func": "sum"}}, ...],
                 "views": [{"name": "By status", "type": "kanban", "config": {"group_field": "status"}}]}],
     "extend": [{"table": "budgets.budgets", "fields": [...]}],     fields added to another app's table
     "automations": [{"key": "place", "table": "orders", "trigger": "button", "actions": [...]}],
     "records": {"orders": [{"Supplier": "Acme", "Status": "Draft"}]}}

A table is named by its key in the same template ("lines") or as
"<template>.<table>" in another one. A link with "optional": true is left out
when the other template isn't installed.

Fields a template adds to another app's table ("extend") remember where they
came from (``Field.origin``): removing the app later leaves the plain ones
there and takes the ones that only work with it. If that table already has a
field with the same key from somewhere else, the new one's key gets the
template's key in front ("stock_reorder_level"), so they never collide.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from . import schema
from .data import Data
from .models import App, Automation, Field, Table, View

COMPUTED = ('lookup', 'rollup', 'formula', 'button')


def directories():
    from .extensions import registry
    dirs = [Path(settings.BASE_DIR) / 'blueprints']
    for ext in registry.extensions.values():
        if ext.path and (ext.path / 'blueprints').is_dir():
            dirs.append(ext.path / 'blueprints')
    return dirs


def available(include_hidden=False):
    """{key: blueprint dict} for every template that comes with Osmia or an extension.
    Hidden ones only when asked for."""
    found = {}
    for d in directories():
        for path in sorted(d.glob('*.json')):
            try:
                bp = json.loads(path.read_text('utf-8'))
            except ValueError:
                continue
            if bp.get('hidden') and not include_hidden:
                continue
            bp['_path'] = str(path)
            bp.setdefault('key', path.stem)
            found[bp['key']] = bp
    return dict(sorted(found.items(), key=lambda kv: (kv[1].get('position', 100), kv[1].get('name', kv[0]))))


def installed_keys():
    return set(App.objects.exclude(blueprint='').values_list('blueprint', flat=True))


def order(keys, catalog):
    """``keys`` plus what they require, each after what it needs."""
    out, visiting = [], set()

    def visit(key):
        if key in out:
            return
        if key in visiting:
            raise ValidationError(f'Templates require each other in a circle ({key}).')
        visiting.add(key)
        bp = catalog.get(key)
        if bp is None:
            if key in installed_keys():
                visiting.discard(key)
                return
            raise ValidationError(f'The template "{key}" is not available.')
        for need in bp.get('requires') or []:
            if need not in installed_keys():
                visit(need)
        visiting.discard(key)
        out.append(key)
    wanted = set(keys)
    for k in keys:
        # "after": templates this one links to if they're there; installed first when asked for together
        for soft in (catalog.get(k) or {}).get('after') or []:
            if soft in wanted:
                visit(soft)
        visit(k)
    return out


def install_many(keys, user=None, sample=False, catalog=None):
    """Install ``keys`` and what they require (each after what it needs). Returns the new apps."""
    catalog = catalog or available(include_hidden=True)
    apps = []
    with transaction.atomic():
        for key in order(keys, catalog):
            if key in installed_keys():
                continue
            apps.append(install(catalog[key], user=user, sample=sample))
    return apps


def needed_for(keys, catalog=None):
    """The templates installing ``keys`` would install too (what they require that isn't there)."""
    catalog = catalog or available(include_hidden=True)
    return [k for k in order(keys, catalog) if k not in keys and k not in installed_keys()]


def _table_ref(ref, app, local):
    """'lines' (this template) or 'vendors.vendors' (another template) -> Table or None."""
    if not ref:
        return None
    if '.' in str(ref):
        app_key, table_key = str(ref).split('.', 1)
        if app_key == app.blueprint and table_key in local:
            return local[table_key]
        return Table.objects.filter(app__blueprint=app_key, key=table_key).order_by('pk').first()
    return local.get(ref)


def _field(table, key, origin=None):
    """A field by its key; a field ``origin`` added to another app's table may have had its key prefixed."""
    if origin:
        mine = Field.objects.filter(table=table, key=f'{origin}_{key}', origin=origin).first()
        if mine is not None:
            return mine
    return Field.objects.filter(table=table, key=key).first()


@transaction.atomic
def install(bp, user=None, sample=False, name=None, owner=None):
    """Make an app from a template (``owner``: someone's own app). Returns the App."""
    missing = [k for k in bp.get('requires') or [] if k not in installed_keys()]
    if missing:
        raise ValidationError(f'Install {", ".join(missing)} first; "{bp.get("name")}" needs it.')
    app = schema.create_app(name or bp.get('name') or bp['key'], user=user, icon=bp.get('icon', '▦'),
                            color=bp.get('color', '#2e7d5b'), description=bp.get('description', ''), group=bp.get('group', ''),
                            blueprint=bp.get('key', ''), blueprint_version=str(bp.get('version', '')),
                            owner=owner, default_role='none' if owner else 'viewer')
    local = {}
    for i, t in enumerate(bp.get('tables') or []):
        table = schema.create_table(app, t['name'], icon=t.get('icon', ''), key=t['key'], primary=None,
                                    description=t.get('description', ''))
        table.position = i
        table.save(update_fields=['position'])
        table.views.all().delete()
        local[t['key']] = table
    groups = [(local[t['key']], t.get('fields') or []) for t in bp.get('tables') or []]
    for ext in bp.get('extend') or []:
        target = _table_ref(ext['table'], app, local)
        if target is None:
            if ext.get('optional'):
                continue
            raise ValidationError(f'{bp.get("name")}: there is no table "{ext["table"]}" to add fields to.')
        groups.append((target, ext.get('fields') or []))
    # 1. stored fields and links (in order), 2. computed ones, which need the links
    key = bp.get('key', '')
    for computed in (False, True):
        for table, fields in groups:
            elsewhere = table.app_id != app.pk
            base = (table.fields.count() if elsewhere else 0)
            for pos, f in enumerate(fields):
                if (f['type'] in COMPUTED) != computed:
                    continue
                existing = _field(table, f['key'], key if elsewhere else None)
                if existing is not None and (not elsewhere or existing.origin == key):
                    continue   # there already (e.g. installed again after being switched off)
                if existing is not None:
                    f = {**f, 'key': f'{key}_{f["key"]}'}
                _add(app, table, f, local, base + pos, origin=key if elsewhere else '')
    for t in bp.get('tables') or []:
        table = local[t['key']]
        display = _field(table, t.get('display')) if t.get('display') else table.fields.first()
        table.display_field = display or table.fields.first()
        if t.get('tree'):
            table.tree_field = _field(table, t['tree'])
            table.is_space = bool(t.get('spaces')) and table.tree_field is not None
        table.save(update_fields=['display_field', 'tree_field', 'is_space'])
        for pos, v in enumerate(t.get('views') or [{'name': f'All {t["name"].lower()}', 'type': 'grid'}]):
            View.objects.create(table=table, name=v['name'], type=v.get('type', 'grid'), config=v.get('config') or {},
                                position=pos)
    autos, skipped = {}, set()
    for pos, a in enumerate(bp.get('automations') or []):
        if a.get('instead_of'):
            continue  # made below, only if the automation it stands in for couldn't be
        table = _table_ref(a.get('table'), app, local)
        if table is None:
            if a.get('optional'):
                continue
            raise ValidationError(f'{bp.get("name")}: automation "{a.get("name")}" is on a table that isn\'t there.')
        try:
            steps = [_resolve_step(s, app, local, table) for s in a.get('actions') or []]
        except ValidationError:
            if a.get('optional'):
                skipped.add(a.get('key'))
                continue  # it works with a template that isn't installed
            raise
        autos[a.get('key') or a['name']] = Automation.objects.create(
            table=table, name=a['name'], description=a.get('description', ''), active=a.get('active', True),
            trigger=a['trigger'], trigger_config=a.get('trigger_config') or {}, conditions=a.get('conditions') or {},
            actions=steps, position=pos, key=a.get('key', ''), origin=key if table.app_id != app.pk else '')
    for pos, a in enumerate(bp.get('automations') or []):
        if a.get('instead_of') in skipped:
            table = _table_ref(a.get('table'), app, local)
            autos[a['instead_of']] = Automation.objects.create(
                table=table, name=a['name'], description=a.get('description', ''), active=True, trigger=a['trigger'],
                trigger_config=a.get('trigger_config') or {}, conditions=a.get('conditions') or {},
                actions=[_resolve_step(s, app, local, table) for s in a.get('actions') or []], position=pos, key=a['instead_of'],
                origin=key if table.app_id != app.pk else '')
    for a in autos.values():  # "run another automation" steps name automations by key
        steps = [dict(s, automation=autos[s['automation']].pk) if s.get('type') == 'run_automation'
                 and s.get('automation') in autos else s for s in a.actions]
        if steps != a.actions:
            a.actions = steps
            a.save(update_fields=['actions'])
    for f in Field.objects.filter(table__in=list(local.values()) + [t for t, _ in groups], type='button'):
        ref = f.opt('automation')
        if isinstance(ref, str) and ref in autos:
            f.options = {**f.options, 'automation': autos[ref].pk}
            f.save(update_fields=['options'])
    from .automation import prime_states
    for a in autos.values():
        prime_states(a)
    if sample and bp.get('records'):
        load_records(bp, app, local, user)
    return app


def _add(app, table, f, local, position, origin=''):
    options = dict(f.get('options') or {})
    ftype = f['type']
    inverse = {}
    bp_key = app.blueprint
    if ftype == 'link':
        target = _table_ref(options.get('target'), app, local)
        if target is None:
            if options.get('optional'):
                return None
            raise ValidationError(f'{table.name}.{f["name"]}: there is no table "{options.get("target")}" to link to.')
        inverse = options.pop('inverse', None) or {}
        options.pop('optional', None)
        options['target'] = target.pk
    elif ftype in ('lookup', 'rollup'):
        link = _field(table, options.get('link'), bp_key if table.app_id != app.pk else None)
        if link is None:
            if f.get('optional'):
                return None
            raise ValidationError(f'{table.name}.{f["name"]}: there is no link field "{options.get("link")}".')
        options['link'] = link.pk
        if options.get('field'):
            target_field = _field(Table.objects.get(pk=link.opt('target')), options['field'])
            if target_field is None:
                if f.get('optional'):
                    return None
                raise ValidationError(f'{table.name}.{f["name"]}: the linked table has no field "{options["field"]}".')
            options['field'] = target_field.pk
    name = f['name']
    if origin and table.fields.filter(name__iexact=name).exists():
        name = f'{name} ({app.name})'
    return schema.add_field(table, name, ftype, options, key=f['key'], required=f.get('required', False),
                            description=f.get('description', ''), position=position,
                            inverse_name=inverse.get('name'), inverse_key=inverse.get('key', ''),
                            inverse_multiple=inverse.get('multiple', True), origin=origin or bp_key)


def _resolve_step(step, app, local, auto_table=None):
    step = dict(step)
    if step.get('table') and not str(step['table']).isdigit():
        table = _table_ref(step['table'], app, local)
        if table is None:
            raise ValidationError(f'An automation step works on a table that isn\'t there ({step["table"]}).')
        step['table'] = table.pk
    # leave out values for fields that weren't made (optional links to templates that aren't installed)
    target = Table.objects.filter(pk=step['table']).first() if step.get('table') else \
        (auto_table if step.get('type') == 'update_record' and step.get('target', 'this') == 'this' else None)
    if target is not None:
        keys = set(target.fields.values_list('key', flat=True))
        for name in ('values', 'match', 'update'):
            if isinstance(step.get(name), dict):
                step[name] = {k: v for k, v in step[name].items() if k in keys}
    return step


def load_records(bp, app, local, user=None):
    from django.contrib.auth import get_user_model
    from . import service
    data = Data(user, system=True)
    usernames = set(get_user_model().objects.values_list('username', flat=True))

    def usable(table, row):
        # leave out what isn't there: demo users not made, fields of templates not installed
        out = {}
        for name, value in row.items():
            field = service._field_for(data, table, name)
            if field is None:
                continue
            if isinstance(value, str) and value.startswith('='):  # e.g. "=TODAY()+3" for dates relative to today
                from datetime import date as _date
                from decimal import Decimal as _Decimal
                value = data.evaluate(value, None)
                value = value.isoformat() if isinstance(value, _date) else str(value) if isinstance(value, _Decimal) else value
            if field.type == 'user':
                names = value if isinstance(value, list) else [value]
                names = [n for n in names if n in usernames]
                if not names:
                    continue
                value = names if field.opt('multiple') else names[0]
            out[name] = value
        return out

    for table_ref, rows in (bp.get('records') or {}).items():
        table = _table_ref(table_ref, app, local)
        if table is None:
            continue
        for row in rows:
            row = dict(row)
            later = row.pop('_then', None)  # values set after creating, so "changed" automations run
            presses = row.pop('_press', [])  # buttons to press afterwards, e.g. "Place order"
            find = row.pop('_find', None)  # {"Part number": "R1"}: change that record (of another template) instead
            record = None
            if find:
                name, wanted = next(iter(find.items()))
                f = service._field_for(data, table, name)
                record = next((r for r in data.records(table) if f and data.text(r, f) == str(wanted)), None)
                if record is None:
                    continue
                service.update_record(record, usable(table, row), user=user, data=data, force=True)
            else:
                record = service.create_record(table, usable(table, row), user=user, data=data, force=True)
            for step in (later if isinstance(later, list) else [later] if later else []):
                service.update_record(record, usable(table, step), user=user, data=data, force=True)
            for key in presses:
                button = service._field_for(data, table, key)
                if button is not None and button.type == 'button':
                    service.press_button(record, button, user, data)
    # then buttons to press on records made above, e.g. place an order once its lines are in
    for step in bp.get('after_records') or []:
        table = _table_ref(step.get('table'), app, local)
        if table is None:
            continue
        name, wanted = next(iter(step['find'].items()))
        f = service._field_for(data, table, name)
        record = next((r for r in data.records(table) if f and data.text(r, f) == str(wanted)), None)
        if record is not None and step.get('set'):
            service.update_record(record, usable(table, step['set']), user=user, data=data, force=True)
        for key in step.get('press') or [] if record is not None else []:
            button = service._field_for(data, table, key)
            if button is not None and button.type == 'button':
                service.press_button(record, button, user, data)
                data.invalidate()


def export(app, with_records=False):
    """The app as a template dict."""
    data = Data()
    tables = list(app.tables.all())
    own = {t.pk for t in tables}

    def table_ref(table_id):
        t = data.table(table_id)
        if t is None:
            return None
        if t.pk in own:
            return t.key or t.slug
        return f'{t.app.blueprint or t.app.slug}.{t.key or t.slug}'

    out = {'key': app.blueprint or app.slug, 'name': app.name, 'icon': app.icon, 'color': app.color,
           'description': app.description, **({'group': app.group} if app.group else {}),
           'version': app.blueprint_version or '1.0.0', 'requires': [], 'tables': [],
           'automations': []}
    requires = set()
    for t in tables:
        fields = []
        for f in data.fields(t):
            options = dict(f.options or {})
            if f.type == 'link':
                if not options.get('owner', True):
                    continue  # the pair is made from its owner
                target = data.table(options.get('target'))
                if target and target.pk not in own:
                    requires.add(target.app.blueprint or target.app.slug)
                inverse = data.field(options.get('inverse'))
                options = {'target': table_ref(options.get('target')), 'multiple': bool(options.get('multiple'))}
                if inverse is not None:
                    options['inverse'] = {'key': inverse.key, 'name': inverse.name, 'multiple': bool(inverse.opt('multiple'))}
            elif f.type in ('lookup', 'rollup'):
                link = data.field(options.get('link'))
                target = data.field(options.get('field'))
                options['link'] = link.key if link else None
                if target is not None:
                    options['field'] = target.key
            elif f.type == 'button':
                auto = Automation.objects.filter(pk=options.get('automation')).first()
                if auto:
                    options['automation'] = auto.key or f'automation_{auto.pk}'
            fields.append({'key': f.key, 'name': f.name, 'type': f.type, 'options': options,
                           **({'required': True} if f.required else {}),
                           **({'description': f.description} if f.description else {})})
        primary = data.primary_field(t)
        tree = data.field(t.tree_field_id) if t.tree_field_id else None
        out['tables'].append({'key': t.key or t.slug, 'name': t.name, 'icon': t.icon, 'display': primary.key if primary else '',
                              **({'tree': tree.key} if tree else {}), **({'spaces': True} if t.is_space else {}),
                              'fields': fields,
                              'views': [{'name': v.name, 'type': v.type, 'config': v.config} for v in t.views.all()]})
    for a in Automation.objects.filter(table__in=tables):
        steps = []
        for s in a.actions:
            s = dict(s)
            if s.get('table'):
                s['table'] = table_ref(s['table'])
            if s.get('type') == 'run_automation':
                other = Automation.objects.filter(pk=s.get('automation')).first()
                s['automation'] = (other.key or f'automation_{other.pk}') if other else None
            steps.append(s)
        out['automations'].append({'key': a.key or f'automation_{a.pk}', 'table': table_ref(a.table_id), 'name': a.name,
                                   'description': a.description, 'active': a.active, 'trigger': a.trigger,
                                   'trigger_config': {k: v for k, v in a.trigger_config.items() if k != 'last_run'},
                                   'conditions': a.conditions, 'actions': steps})
    out['requires'] = sorted(requires)
    if with_records:
        out['records'] = {}
        for t in tables:
            rows = []
            for r in data.records(t):
                row = {}
                for f in data.fields(t):
                    if f.type == 'link' and f.opt('owner', True):
                        names = data.value(r, f)
                        if names:
                            row[f.key] = list(names) if f.opt('multiple') else names[0]
                    elif f.kind.stored and f.type != 'autonumber' and (r.data or {}).get(f.key) not in (None, '', []):
                        row[f.key] = r.data[f.key]
                        if f.type == 'user':
                            users = data.users()
                            ids = r.data[f.key] if isinstance(r.data[f.key], list) else [r.data[f.key]]
                            row[f.key] = [users[i].username for i in ids if i in users]
                rows.append(row)
            out['records'][t.key or t.slug] = rows
    return out
