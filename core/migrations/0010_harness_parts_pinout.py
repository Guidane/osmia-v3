from django.db import migrations

LABEL = ('IF(ISBLANK({Designator}), {Part}, {Designator} & IF(ISBLANK({Part}), "", " · " & {Part}) '
         '& IF(ISBLANK({Gender}), "", " · " & {Gender}))')
PARTS_SHOW = {'fields': ['part', 'quantity', 'unit', 'designator', 'side', 'gender'], 'sort': ['designator']}
DEMO_ITEMS = [('DSUB-9-CONTACT', 6), ('WIRE-22-RED', 0.5), ('WIRE-22-BLK', 0.5), ('TIE-100', 4)]


def parts_and_pinout(apps, schema_editor):
    """An installed Harnesses app as the template is from here on: a harness has Parts (a bill of materials:
    connectors, contacts, wire, cable ties, ..., with how many; connectors have a designator and a side) and a
    Pinout (what were its Wires), and a build time: a time per wire times its wires. The demo harness gets its
    contacts, wire and cable ties (and Parts a cable tie).

    It changes the app's tables and fields with Osmia's own schema code; it only runs where a Harnesses app is
    installed, at the time this migration is applied."""
    App = apps.get_model('core', 'App')
    for app_id in App.objects.filter(blueprint='harnesses').values_list('pk', flat=True):
        _upgrade(app_id)


def _upgrade(app_id):
    from core import schema, service
    from core.data import Data
    from core.models import Field, Record, Table

    harnesses = Table.objects.get(app_id=app_id, key='harnesses')
    items = Table.objects.get(app_id=app_id, key='connectors')
    pinout = Table.objects.get(app_id=app_id, key='wires')
    if items.fields.filter(key='quantity').exists():
        return

    def rename(field, name):
        if field is not None and field.name != name and not field.table.fields.filter(name__iexact=name).exists():
            schema.update_field(field, name=name)

    # the tables and the harness's two lists
    items.name, items.icon = 'Harness parts', '📦'
    items.save(update_fields=['name', 'icon'])
    pinout.name = 'Pinout'
    pinout.save(update_fields=['name'])
    rename(harnesses.fields.filter(key='connectors').first(), 'Parts')
    rename(harnesses.fields.filter(key='wires').first(), 'Pinout')
    listed = harnesses.fields.filter(key='connectors', type='link').first()
    if listed is not None:
        listed.options = {**(listed.options or {}), 'show': PARTS_SHOW}
        listed.save(update_fields=['options'])
    for view, name in ((items.views.filter(name='Connectors').first(), 'Harness parts'),
                       (pinout.views.filter(name='Wires').first(), 'Pinout')):
        if view is not None:
            view.name = name
            view.save(update_fields=['name'])

    # harness parts: a quantity and its unit; a designator and a side only for connectors
    part = items.fields.get(key='part')
    quantity = schema.add_field(items, 'Quantity', 'number', {'default': '1'}, key='quantity',
                                description="How many, in the part's unit (pieces, metres, ...).")
    unit_field = Field.objects.filter(table_id=part.opt('target'), key='unit').first()
    if unit_field is not None:
        schema.add_field(items, 'Unit', 'lookup', {'link': part.pk, 'field': unit_field.pk}, key='unit')
    designator = items.fields.get(key='designator')
    designator.required = False
    designator.description = 'For a connector: its name on the harness, e.g. X1. The pinout wires between the parts that have one.'
    designator.save(update_fields=['required', 'description'])
    side = items.fields.filter(key='side').first()
    if side is not None:
        side.options = {k: v for k, v in (side.options or {}).items() if k != 'default'}
        side.description = 'For a connector: the side it is on.'
        side.save(update_fields=['options', 'description'])
    label = items.fields.get(key='label')
    schema.update_field(label, name='Harness part' if not items.fields.filter(name__iexact='Harness part').exists() else None,
                        options={**(label.options or {}), 'expression': LABEL})
    for record in Record.objects.filter(table=items):
        record.data.setdefault(quantity.key, 1)
        record.save(update_fields=['data'])
    rename(pinout.fields.filter(key='label').first(), 'Wire')

    # build time: a time per wire, times every wire
    time = schema.add_field(harnesses, 'Time per wire (min)', 'number', {'default': '3'}, key='time_per_wire',
                            description='How long making one wire of the pinout takes, both ends and all.')
    count = harnesses.fields.filter(key='wire_count').first()
    if count is not None:
        schema.add_field(harnesses, 'Build time (min)', 'formula', {'expression': f'{{{time.name}}} * {{{count.name}}}'},
                         key='build_time', description='The time per wire, times every wire of the pinout.')
    order = ['name', 'number', 'status', 'description', 'wire_count', 'time_per_wire', 'build_time', 'total_length']
    order_items = ['label', 'harness', 'part', 'quantity', 'unit', 'designator', 'side', 'part_attributes', 'gender', 'notes']
    for table, keys in ((harnesses, order), (items, order_items)):
        rest = [f for f in table.fields.order_by('position', 'pk') if f.key not in keys]
        for at, f in enumerate([table.fields.get(key=k) for k in keys if table.fields.filter(key=k).exists()] + rest):
            f.position = at
            f.save(update_fields=['position'])
    view = harnesses.views.filter(type='grid').first()
    if view is not None and 'build_time' not in (view.config or {}).get('fields', []):
        fields = list((view.config or {}).get('fields') or [])
        fields.insert(fields.index('wire_count') + 1 if 'wire_count' in fields else len(fields), 'build_time')
        view.config = {**(view.config or {}), 'fields': fields}
        view.save(update_fields=['config'])

    # the demo: its parts besides the connectors, and a time per wire
    demo = next((r for r in Record.objects.filter(table=harnesses) if (r.data or {}).get('name') == 'Burn-in rack loom'), None)
    parts = Table.objects.filter(pk=part.opt('target')).first()
    if demo is None or parts is None:
        return
    demo.data.setdefault(time.key, 3)
    demo.save(update_fields=['data'])
    data = Data()
    by_number = {(r.data or {}).get('part_number'): r for r in Record.objects.filter(table=parts)}
    if 'TIE-100' not in by_number and 'DSUB-9-PLUG' in by_number:
        by_number['TIE-100'] = _cable_tie(parts, data, service, Field, Record)
    fields = {f.key: f for f in data.fields(items)}
    for number, amount in DEMO_ITEMS:
        if number in by_number and by_number[number] is not None:
            service.create_record(items, {fields['harness'].pk: [demo.pk], fields['part'].pk: [by_number[number].pk],
                                          fields['quantity'].pk: amount}, data=data, force=True, run_automations=False)


def _cable_tie(parts, data, service, Field, Record):
    """The Parts demo's cable tie, in a category of harness accessories."""
    fields = {f.key: f for f in data.fields(parts)}
    category = fields.get('category')
    values = {fields['part_number'].pk: 'TIE-100', fields['description'].pk: 'Cable tie 100 x 2.5 mm, nylon'}
    if 'attributes' in fields:
        values[fields['attributes'].pk] = [{'name': 'Length', 'value': '100 mm'}, {'name': 'Width', 'value': '2.5 mm'},
                                           {'name': 'Material', 'value': 'nylon'}]
    if category is not None:
        categories = category.opt('target')
        found = next((r for r in Record.objects.filter(table_id=categories) if (r.data or {}).get('name') == 'Harness accessories'), None)
        if found is None:
            cat_fields = {f.key: f for f in Field.objects.filter(table_id=categories)}
            cat_values = {cat_fields['name'].pk: 'Harness accessories'}
            if 'attribute_names' in cat_fields:
                cat_values[cat_fields['attribute_names'].pk] = [{'name': 'Length', 'value': 'mm'}, {'name': 'Width', 'value': 'mm'},
                                                                {'name': 'Material', 'value': 'e.g. nylon'}]
            found = service.create_record(cat_fields['name'].table, cat_values, data=data, force=True, run_automations=False)
        values[category.pk] = [found.pk]
    return service.create_record(parts, values, data=data, force=True, run_automations=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_order_delivery_date'),
    ]

    operations = [
        migrations.RunPython(parts_and_pinout, migrations.RunPython.noop),
    ]
