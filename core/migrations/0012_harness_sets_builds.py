from django.db import migrations

CHECK_SHOW = {
    'fields': ['a_function', 'a_contact', 'b_contact', 'b_function', 'set', 'placed', 'verified'],
    'sort': ['a_contact'], 'keep_together': 'set', 'link_existing': False, 'add': False,
    'group_lines': [['part'], ['designator', 'gender']],
    'group_by': ['a_connector', 'b_connector'], 'group_join': ' → ',
    'group_columns': {'a_connector': ['a_function', 'a_contact'], 'b_connector': ['b_contact', 'b_function']},
    'column_groups': [{'label': 'A', 'fields': ['a_function', 'a_contact']},
                      {'label': 'B', 'fields': ['b_contact', 'b_function']},
                      {'label': 'Build', 'fields': ['set', 'placed', 'verified']}]}
BUILDS = [
    {'key': 'harness_id', 'name': 'Harness ID', 'type': 'autonumber', 'options': {'prefix': 'SN-', 'digits': 5},
     'description': 'The ID of the harness built: write it on its label.'},
    {'key': 'harness', 'name': 'Harness', 'type': 'link', 'options': {
        'target': 'harnesses', 'multiple': False, 'inverse': {'key': 'builds', 'name': 'Builds', 'multiple': True, 'show': {
            'fields': ['harness_id', 'started', 'built_by', 'placed', 'verified', 'progress'], 'link_existing': False, 'add': False}}}},
    {'key': 'started', 'name': 'Started', 'type': 'created_time'},
    {'key': 'built_by', 'name': 'Built by', 'type': 'created_by'},
    {'key': 'wire_count', 'name': 'Wires', 'type': 'rollup', 'options': {'link': 'checks', 'func': 'count'}},
    {'key': 'placed', 'name': 'Placed', 'type': 'rollup', 'options': {'link': 'checks', 'field': 'placed', 'func': 'sum'}},
    {'key': 'verified', 'name': 'Verified', 'type': 'rollup', 'options': {'link': 'checks', 'field': 'verified', 'func': 'sum'}},
    {'key': 'progress', 'name': 'Progress', 'type': 'formula', 'options': {'expression':
        'IF({Wires} = 0, "", IF({Verified} = {Wires}, "Done", IF({Placed} = 0, "Not started", '
        '{Placed} & " of " & {Wires} & " placed, " & {Verified} & " verified")))'}},
    {'key': 'notes', 'name': 'Notes', 'type': 'longtext'},
]
CHECKS = [
    {'key': 'label', 'name': 'Check', 'type': 'formula', 'options': {'expression': '{Build} & " · " & {Wire}'}},
    {'key': 'build', 'name': 'Build', 'type': 'link', 'options': {
        'target': 'builds', 'multiple': False, 'inverse': {'key': 'checks', 'name': 'Checklist', 'multiple': True, 'show': CHECK_SHOW}}},
    {'key': 'wire', 'name': 'Wire', 'type': 'link', 'options': {
        'target': 'wires', 'multiple': False, 'inverse': {'key': 'checks', 'name': 'In builds', 'multiple': True}}},
    {'key': 'a_connector', 'name': 'A connector', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'from'}},
    {'key': 'a_function', 'name': 'A function', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'a_function'}},
    {'key': 'a_contact', 'name': 'A contact', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'source_contact'}},
    {'key': 'b_contact', 'name': 'B contact', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'target_contact'}},
    {'key': 'b_function', 'name': 'B function', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'b_function'}},
    {'key': 'b_connector', 'name': 'B connector', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'to'}},
    {'key': 'set', 'name': 'Set', 'type': 'lookup', 'options': {'link': 'wire', 'field': 'set'}},
    {'key': 'placed', 'name': 'Placed', 'type': 'checkbox'},
    {'key': 'verified', 'name': 'Verified', 'type': 'checkbox'},
]
BUILD_STEPS = [
    {'type': 'block', 'if': '{Wire count} = 0', 'message': '{Name} has no pinout yet: add its wires first.'},
    {'type': 'create_record', 'table': 'builds', 'values': {'harness': '=RECORD_ID()'}, 'save_as': 'build'},
    {'type': 'create_record', 'table': 'checks', 'for_each': 'wires',
     'values': {'build': '={build.Harness ID}', 'wire': '={item.Record id}'}},
]
DEMO_SETS = {'1': 'P1', '2': 'P1', '6': 'P2', '7': 'P2'}
GROUP_LINES = [['part'], ['designator', 'gender']]
ADD_BELOW = [{'band': 'A', 'label': 'Connector on A', 'link': 'connectors', 'values': {'side': 'A'}}, {'band': 'B', 'label': 'Connector on B', 'link': 'connectors', 'values': {'side': 'B'}}, {'band': 'Wire details', 'label': 'Wire'}]
SHIELD = {'value': 'Shield', 'color': '#d1d5db'}
SET_TYPE_HELP = "How the wires of a set go together. A shielded set's shield is a row of its own in the set, set type Shield: the contacts it is connected to (on A, on B or both)."


def sets_and_builds(apps, schema_editor):
    """An installed Harnesses app as the template is from here on: a pinout's wires have a set (P1, a twisted pair),
    kept together with an outline around them; a harness has a "Build harness" button that makes a build with a
    harness ID (SN-00001, ...) and a checklist of every wire, placed and verified.

    It changes the app with Osmia's own schema code; it only runs where a Harnesses app is installed."""
    App = apps.get_model('core', 'App')
    for app_id in App.objects.filter(blueprint='harnesses').values_list('pk', flat=True):
        _upgrade(app_id)


def _upgrade(app_id):
    from core import blueprints, schema, service
    from core.automation import prime_states
    from core.data import Data
    from core.models import App, Automation, Record, Table, View

    app = App.objects.get(pk=app_id)
    harnesses = Table.objects.get(app=app, key='harnesses')
    wires = Table.objects.get(app=app, key='wires')
    if Table.objects.filter(app=app, key='builds').exists() or not harnesses.fields.filter(key='wires').exists():
        return

    # the pinout: a set, kept together, and each wire's record id (for the checklist)
    if not wires.fields.filter(key='set').exists():
        set_type = wires.fields.filter(key='set_type').first()
        schema.add_field(wires, 'Set' if not wires.fields.filter(name__iexact='Set').exists() else 'Wire set', 'text', key='set',
                         description='Wires with the same set (P1, P2, ...) go together: twisted or shielded as their set type says.',
                         position=set_type.position if set_type else None)
    if not wires.fields.filter(type='record_id').exists():
        schema.add_field(wires, 'Record id', 'record_id', key='id')
    record_id = wires.fields.get(type='record_id')
    listed = harnesses.fields.get(key='wires')
    show = dict((listed.options or {}).get('show') or {})
    if show:
        for keys in [show.get('fields')] + [g.get('fields') for g in show.get('column_groups') or [] if g.get('label') == 'Wire details']:
            if isinstance(keys, list) and 'set' not in keys:
                keys.insert(keys.index('set_type') if 'set_type' in keys else len(keys), 'set')
        show.update({'keep_together': 'set', 'group_lines': GROUP_LINES, 'add_below': ADD_BELOW})
        listed.options = {**listed.options, 'show': show}
        listed.save(update_fields=['options'])
    for view in wires.views.filter(type='grid'):
        fields = (view.config or {}).get('fields')
        if isinstance(fields, list) and 'set' not in fields:
            fields.insert(fields.index('set_type') if 'set_type' in fields else len(fields), 'set')
            view.save(update_fields=['config'])

    # a shielded set's shield: a row of its own, set type Shield, on the contacts it is connected to
    set_type = wires.fields.filter(key='set_type', type='select').first()
    if set_type is not None and not any(c.get('value') == 'Shield' for c in set_type.opt('choices') or []):
        schema.update_field(set_type, options={**set_type.options, 'choices': list(set_type.opt('choices') or []) + [SHIELD]},
                            description=SET_TYPE_HELP)

    # builds and their checklists
    position = Table.objects.filter(app=app).count()
    local = {t.key: t for t in Table.objects.filter(app=app)}
    for i, (key, name, icon, display) in enumerate([('builds', 'Builds', '🛠', 'harness_id'), ('checks', 'Build checklist', '☑', 'label')]):
        table = schema.create_table(app, name, icon=icon, key=key, primary=None)
        table.position = position + i
        table.save(update_fields=['position'])
        table.views.all().delete()
        local[key] = table
    groups = [(local['builds'], BUILDS), (local['checks'], CHECKS)]
    for computed in (False, True):
        for table, fields in groups:
            for pos, f in enumerate(fields):
                if (f['type'] in blueprints.COMPUTED) == computed:
                    blueprints._add(app, table, f, local, pos)
    for table, display in ((local['builds'], 'harness_id'), (local['checks'], 'label')):
        table.display_field = table.fields.get(key=display)
        table.save(update_fields=['display_field'])
    View.objects.create(table=local['builds'], name='Builds', type='grid', position=0, config={
        'fields': ['harness_id', 'harness', 'started', 'built_by', 'progress'], 'sorts': [{'field': 'harness_id', 'dir': 'desc'}]})
    View.objects.create(table=local['checks'], name='Build checklist', type='grid', position=0,
                        config={'group_by': 'build', 'fields': ['wire', 'placed', 'verified']})

    # the button
    steps = [blueprints._resolve_step(s, app, local, harnesses) for s in BUILD_STEPS]
    steps[2]['values']['wire'] = '={item.%s}' % record_id.name
    auto = Automation.objects.create(
        table=harnesses, name='Build harness', key='build', trigger='button', conditions={'match': 'all', 'rules': []},
        description='A new build of the harness, with its harness ID, and a checklist of every wire: placed and verified.',
        actions=steps, position=Automation.objects.filter(table__app=app).count())
    prime_states(auto)
    pictures = harnesses.fields.filter(key='pictures').first()
    schema.add_field(harnesses, 'Build', 'button', {'label': 'Build harness', 'color': '#c2410c', 'automation': auto.pk},
                     key='build', position=pictures.position if pictures else None)

    # the demo harness: its twisted pairs as sets
    demo = next((r for r in Record.objects.filter(table=harnesses) if (r.data or {}).get('name') == 'Burn-in rack loom'), None)
    if demo is not None:
        data = Data()
        pinout = data.linked(demo, listed)
        for record in pinout:
            contact = str((record.data or {}).get('source_contact') or '')
            if contact in DEMO_SETS and not (record.data or {}).get('set'):
                record.data['set'] = DEMO_SETS[contact]
                record.save(update_fields=['data'])
        # and P2's shield, on contact 8 at both ends
        parts = harnesses.fields.filter(key='connectors', type='link').first()
        by_name = {(r.data or {}).get('designator'): r for r in data.linked(demo, parts)} if parts else {}
        if 'X1' in by_name and 'Y2' in by_name and not any((r.data or {}).get('set_type') == 'Shield' for r in pinout):
            fields = {f.key: f for f in data.fields(wires)}
            values = {'harness': [demo.pk], 'from': [by_name['X1'].pk], 'to': [by_name['Y2'].pk], 'source_contact': '8',
                      'target_contact': '8', 'a_function': 'Shield', 'b_function': 'Shield', 'set': 'P2',
                      'set_type': 'Shield', 'length': 300}
            service.create_record(wires, {fields[k].pk: v for k, v in values.items() if k in fields}, data=data, force=True,
                                  run_automations=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_add_by_picking'),
    ]

    operations = [
        migrations.RunPython(sets_and_builds, migrations.RunPython.noop),
    ]
