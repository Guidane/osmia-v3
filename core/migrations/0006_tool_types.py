from django.db import migrations

# The Tools template's types from here on: nested, each listing what its tools fill in (with a hint for the value),
# and the demo tools filling them in. Written into records still as the demo left them.
PARENTS = {'Crimp tool': 'Hand tools', 'Insertion / extraction': 'Hand tools', 'Stripper': 'Hand tools',
           'Meter': 'Test equipment'}
TYPES = {
    'Crimp tool': [('Wire size', 'AWG'), ('Contact type', 'e.g. D-sub'), ('Ratchet', 'yes or no')],
    'Insertion / extraction': [('Contact type', 'e.g. D-sub'), ('Contact size', 'e.g. 20')],
    'Stripper': [('Wire size', 'AWG'), ('Cable type', 'e.g. round')],
    'Meter': [('Measures', 'e.g. V, A, Ω'), ('Accuracy', '%'), ('Digits', 'e.g. 6½')],
}
TOOLS = {
    'D-sub crimp tool': [('Wire size', '20-24 AWG'), ('Contact type', 'D-sub'), ('Ratchet', 'yes')],
    'Contact extraction tool': [('Contact type', 'D-sub'), ('Contact size', '20')],
    'Precision wire stripper': [('Wire size', '10-24 AWG'), ('Cable type', 'round')],
    'Bench multimeter': [('Measures', 'V, A, Ω, Hz'), ('Accuracy', '0.0035%'), ('Digits', '6½')],
}


def as_pairs(items):
    return [{'name': n, 'value': v} for n, v in items]


def tool_types(apps, schema_editor):
    """An installed Tools app whose Type is still a list of choices: the choices become a tree of tool types (as
    in the template), each with the attributes its tools fill in, and the tools get Attributes.

    This works on the app's tables and fields as records of Osmia (Table, Field, Record), so it uses Osmia's own
    schema code; it only runs where a Tools app is installed, at the time this migration is applied."""
    App = apps.get_model('core', 'App')
    Field = apps.get_model('core', 'Field')
    for app_id in App.objects.filter(blueprint='tools').values_list('pk', flat=True):
        if not Field.objects.filter(table__app_id=app_id, table__key='tools', key='type', type='select').exists():
            continue
        _upgrade(app_id)


def _upgrade(app_id):
    from core import schema
    from core.models import Field, Link, Record, Table, View

    tools = Table.objects.get(app_id=app_id, key='tools')
    types = schema.choices_to_table(tools.fields.get(key='type'), 'Tool types', tree=True, icon='🗂', key='tool_types')
    inverse = Field.objects.get(table=types, type='link', options__target=tools.pk)
    schema.add_field(types, 'Tools here', 'rollup', {'link': inverse.pk, 'func': 'count'}, key='tool_count')
    listed = schema.add_field(types, 'Attributes to fill in', 'attributes', key='attribute_names',
                              description='The attributes its tools fill in, each with a hint for the value: '
                                          'a unit (AWG) or an example (e.g. D-sub).')
    if not tools.fields.filter(key='attributes').exists():
        schema.add_field(tools, 'Attributes', 'attributes', {'names_from': 'type.attribute_names'}, key='attributes',
                         description="Name-value pairs, e.g. Wire size 20-24 AWG; the tool's type lists the ones to fill in.")
    attrs = tools.fields.get(key='attributes')
    View.objects.create(table=types, name='Tool types', type='tree', position=types.views.count(),
                        config={'parent_field': 'parent', 'fields': ['name', 'tool_count', 'attribute_names']})
    view = tools.views.filter(name='Tools', type='grid').first()
    if view is not None and 'attributes' not in (view.config or {}).get('fields', ['attributes']):
        fields = list(view.config['fields'])
        fields.insert(fields.index('type') + 1 if 'type' in fields else len(fields), 'attributes')
        view.config = {**view.config, 'fields': fields}
        view.save(update_fields=['config'])
    # the demo: nested types that list what to fill in, and tools filling it in
    by_name = {(r.data or {}).get('name'): r for r in Record.objects.filter(table=types)}
    parent = types.fields.get(key='parent')
    for name, records in [(n, by_name.get(n)) for n in TYPES]:
        if records is None:
            continue
        records.data[listed.key] = as_pairs(TYPES[name])
        records.save(update_fields=['data'])
        group = PARENTS[name]
        if group not in by_name:
            by_name[group] = Record.objects.create(table=types, data={'name': group}, position=len(by_name) + 1)
        Link.objects.get_or_create(field=parent, source=records, target=by_name[group])
    for record in Record.objects.filter(table=tools):
        data = record.data or {}
        if data.get('name') in TOOLS and not data.get(attrs.key):
            data[attrs.key] = as_pairs(TOOLS[data['name']])
            record.data = data
            record.save(update_fields=['data'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_category_attributes'),
    ]

    operations = [
        migrations.RunPython(tool_types, migrations.RunPython.noop),
    ]
