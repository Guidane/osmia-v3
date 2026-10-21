from django.db import migrations

# (template, table, link to the record it belongs to, the parts of its "show" option to add)
LISTS = [
    ('orders', 'lines', 'order', {'link_existing': False, 'add_by': 'part', 'add_quantity': 'quantity'}),
    ('harnesses', 'connectors', 'harness', {'link_existing': False, 'add_by': 'part', 'add_quantity': 'quantity'}),
    ('harnesses', 'wires', 'harness', {'link_existing': False}),
]


def add_by_picking(apps, schema_editor):
    """An order's lines, and a harness's parts, are added by picking parts (with how many) rather than linking
    lines that are there already; a harness's pinout isn't linked either: as the templates are from here on."""
    Field = apps.get_model('core', 'Field')
    for blueprint, table_key, link_key, show in LISTS:
        for link in Field.objects.filter(table__app__blueprint=blueprint, table__key=table_key, key=link_key, type='link'):
            listed = Field.objects.filter(pk=(link.options or {}).get('inverse')).first()
            if listed is None:
                continue
            listed.options = {**(listed.options or {}), 'show': {**((listed.options or {}).get('show') or {}), **show}}
            listed.save(update_fields=['options'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_harness_parts_pinout'),
    ]

    operations = [
        migrations.RunPython(add_by_picking, migrations.RunPython.noop),
    ]
