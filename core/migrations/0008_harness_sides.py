from django.db import migrations

SET_TYPES = [{'value': 'Straight', 'color': '#e5e7eb'}, {'value': 'Twisted', 'color': '#bfdbfe'},
             {'value': 'Shielded twisted', 'color': '#c4b5fd'}, {'value': 'Shielded', 'color': '#a5b4fc'}]
SHOW = {'fields': ['a_function', 'source_contact', 'target_contact', 'b_function', 'set_type', 'colour', 'awg', 'length', 'part'],
        'sort': ['source_contact'], 'group_by': ['from', 'to'], 'group_join': ' → ',
        'group_columns': {'from': ['a_function', 'source_contact'], 'to': ['target_contact', 'b_function']},
        'column_groups': [{'label': 'A', 'fields': ['a_function', 'source_contact']},
                          {'label': 'B', 'fields': ['target_contact', 'b_function']},
                          {'label': 'Wire details', 'fields': ['set_type', 'colour', 'awg', 'length', 'part']}]}
# the demo harness's wires, by "A contact → B contact": set type and the wire's part
DEMO = {('1', '1'): ('Twisted', 'WIRE-22-RED', '+24 V in'), ('2', '3'): ('Twisted', 'WIRE-22-BLK', '0 V in'),
        ('3', '5'): ('Straight', '', 'Enable in'), ('6', '2'): ('Shielded twisted', '', ''),
        ('7', '7'): ('Shielded twisted', '', ''), ('9', '3'): ('Straight', '', '')}


def sides(apps, schema_editor):
    """An installed Harnesses app as the template is from here on: connectors on side A or B; wires with a function at
    each end (what was the Signal), a set type and the wire's part; and the harness's page laid out A | B | wire details.

    This works on the app's tables and fields as records of Osmia, so it uses Osmia's own schema code; it only runs
    where a Harnesses app is installed, at the time this migration is applied."""
    App = apps.get_model('core', 'App')
    for app_id in App.objects.filter(blueprint='harnesses').values_list('pk', flat=True):
        _upgrade(app_id)


def _upgrade(app_id):
    from core import schema
    from core.models import Field, Link, Record, Table

    connectors = Table.objects.get(app_id=app_id, key='connectors')
    wires = Table.objects.get(app_id=app_id, key='wires')
    if wires.fields.filter(key='a_function').exists():
        return
    side = connectors.fields.filter(key='side', type='select').first()
    if side is not None and [c['value'] for c in side.opt('choices') or []] == ['Source', 'Target']:
        schema.update_field(side, options={'default': 'A', 'choices': [{'value': 'A', 'color': '#dbeafe'},
                                                                       {'value': 'B', 'color': '#fde68a'}]})
    names = {'from': 'A connector', 'source_contact': 'A contact', 'to': 'B connector', 'target_contact': 'B contact'}
    for key, name in names.items():
        f = wires.fields.filter(key=key).first()
        if f is not None and f.name != name and not wires.fields.filter(name__iexact=name).exists():
            schema.update_field(f, name=name)
    a_function = schema.add_field(wires, 'A function', 'text', key="a_function",
                                  description='What it carries at the A end, e.g. +24 V.')
    b_function = schema.add_field(wires, 'B function', 'text', key="b_function",
                                  description='What it carries at the B end.')
    set_type = schema.add_field(wires, 'Set type', 'select', {'default': 'Straight', 'choices': SET_TYPES}, key='set_type')
    parts = Table.objects.filter(app__blueprint='parts', key='parts').first()
    part = None
    if parts is not None and not wires.fields.filter(key='part').exists():
        part = schema.add_field(wires, 'Part', 'link', {'target': parts.pk, 'multiple': False}, key='part',
                                description='The wire itself, from Parts.', inverse_name='Used as wire',
                                inverse_key='harness_wires', inverse_multiple=True)
    # what was the Signal is the function at both ends
    signal = wires.fields.filter(key='signal').first()
    keys = {f.key: f.key for f in wires.fields.all()}
    for record in Record.objects.filter(table=wires):
        data = record.data or {}
        value = data.get('signal')
        if value:
            data['a_function'] = data['b_function'] = value
        data.setdefault('set_type', 'Straight')
        record.data = data
        record.save(update_fields=['data'])
    if signal is not None:
        schema.delete_field(signal, checked=True)
    # the demo: set types, the wire's part, the function at the B end
    harness = Table.objects.get(app_id=app_id, key='harnesses')
    demo = next((r for r in Record.objects.filter(table=harness) if (r.data or {}).get('name') == 'Burn-in rack loom'), None)
    if demo is not None:
        owner = Field.objects.get(table=wires, key='harness')
        wire_parts = {r.data.get('part_number'): r for r in Record.objects.filter(table=parts)} if parts is not None else {}
        for link in Link.objects.filter(field=owner, target=demo).select_related('source'):
            record = link.source
            found = DEMO.get((record.data.get('source_contact'), record.data.get('target_contact')))
            if found is None:
                continue
            set_value, part_number, b_value = found
            record.data['set_type'] = set_value
            if b_value:
                record.data['b_function'] = b_value
            record.save(update_fields=['data'])
            if part is not None and part_number in wire_parts:
                Link.objects.get_or_create(field=part, source=record, target=wire_parts[part_number])
    # the harness's page: A | B | wire details
    listed = Field.objects.filter(table=harness, key='wires', type='link').first()
    if listed is not None:
        listed.options = {**(listed.options or {}), 'show': SHOW}
        listed.save(update_fields=['options'])
    view = wires.views.filter(name='Wires', type='grid').first()
    if view is not None:
        view.config = {**(view.config or {}), 'fields': [
            'from', 'a_function', 'source_contact', 'to', 'target_contact', 'b_function', 'set_type', 'colour', 'awg',
            'length', 'part']}
        view.save(update_fields=['config'])
    # the fields in the template's order (forms follow it); any others after them, as they were
    order = ['label', 'harness', 'from', 'a_function', 'source_contact', 'to', 'target_contact', 'b_function', 'set_type',
             'colour', 'awg', 'length', 'part', 'from_designator', 'to_designator']
    rest = [f for f in wires.fields.order_by('position', 'pk') if f.key not in order]
    for at, f in enumerate([wires.fields.get(key=k) for k in order if wires.fields.filter(key=k).exists()] + rest):
        f.position = at
        f.save(update_fields=['position'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_remove_harness_designer'),
    ]

    operations = [
        migrations.RunPython(sides, migrations.RunPython.noop),
    ]
