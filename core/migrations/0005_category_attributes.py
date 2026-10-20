from django.db import migrations

# The Parts template's demo data as it is from here on: the attributes each category's parts fill in (with a hint
# for the value), and the demo parts filling them in. Written into records still as the demo left them.
CATEGORIES = {
    'Resistors': [('Resistance', 'Ω'), ('Power', 'W'), ('Tolerance', '%'), ('Package', 'e.g. 0603')],
    'Capacitors': [('Capacitance', 'F'), ('Voltage', 'V'), ('Dielectric', 'e.g. X7R'), ('Package', 'e.g. 0603')],
    'Connectors': [('Positions', 'how many'), ('Gender', 'male or female')],
    'D-sub': [('Positions', 'how many'), ('Gender', 'male or female'), ('Mounting', 'cable or panel')],
    'Contacts': [('Gender', 'male or female'), ('Wire size', 'AWG'), ('Plating', 'e.g. gold')],
    'Wire': [('Wire size', 'AWG'), ('Colour', ''), ('Insulation', 'e.g. PVC')],
}
PARTS = {
    'RES-10K-0603': [('Resistance', '10 kΩ'), ('Power', '0.1 W'), ('Tolerance', '1%'), ('Package', '0603')],
    'CAP-100N-0603': [('Capacitance', '100 nF'), ('Voltage', '50 V'), ('Dielectric', 'X7R'), ('Package', '0603')],
    'DSUB-9-CONTACT': [('Gender', 'male'), ('Wire size', '20-24 AWG'), ('Plating', 'gold')],
    'DSUB-9-PLUG': [('Positions', '9'), ('Gender', 'male'), ('Mounting', 'cable')],
    'DSUB-9-RECEPT': [('Positions', '9'), ('Gender', 'female'), ('Mounting', 'panel')],
    'WIRE-22-RED': [('Wire size', '22 AWG'), ('Colour', 'red'), ('Insulation', 'PVC')],
    'WIRE-22-BLK': [('Wire size', '22 AWG'), ('Colour', 'black'), ('Insulation', 'PVC')],
}
# What the demo had before: anything else was changed by someone, and is kept
OLD_CATEGORIES = {'Resistors': 'Resistance\nPower\nTolerance', 'Capacitors': 'Capacitance\nVoltage'}
OLD_PARTS = {'RES-10K-0603': [('Resistance', '10 kΩ'), ('Power', '0.1 W'), ('Tolerance', '1%')]}


def as_pairs(items):
    return [{'name': n, 'value': v} for n, v in items]


def names(text):
    """Lines of names (the old "Attributes to fill in") as pairs without a hint."""
    out, seen = [], set()
    for line in str(text or '').splitlines():
        name = ' '.join(line.split(':')[0].split())[:60]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append({'name': name, 'value': ''})
    return out


def upgrade(apps, schema_editor):
    Field = apps.get_model('core', 'Field')
    Record = apps.get_model('core', 'Record')
    for listed in Field.objects.filter(table__app__blueprint='parts', table__key='categories', key='attribute_names'):
        name_key = next((f.key for f in Field.objects.filter(table_id=listed.table_id, key='name')), 'name')
        was_text = listed.type == 'longtext'
        for record in Record.objects.filter(table_id=listed.table_id):
            data = record.data or {}
            value = data.get(listed.key)
            label = data.get(name_key)
            if label in CATEGORIES and (value in (None, '', []) or value == OLD_CATEGORIES.get(label)):
                data[listed.key] = as_pairs(CATEGORIES[label])
            elif was_text and isinstance(value, str):
                data[listed.key] = names(value)
            else:
                continue
            record.data = data
            record.save(update_fields=['data'])
        if was_text:
            listed.type = 'attributes'
            listed.description = ('The attributes its parts fill in, each with a hint for the value: '
                                  'a unit (Ω) or an example (e.g. 0603).')
            listed.save(update_fields=['type', 'description'])
        # the parts' Attributes: what to fill in comes from their category
        for attrs in Field.objects.filter(table__app_id=listed.table.app_id, table__key='parts', key='attributes',
                                          type='attributes'):
            options = dict(attrs.options or {})
            if not options.get('names_from'):
                options['names_from'] = 'category.attribute_names'
                attrs.options = options
                attrs.save(update_fields=['options'])
            number_key = next((f.key for f in Field.objects.filter(table_id=attrs.table_id, key='part_number')), 'part_number')
            for record in Record.objects.filter(table_id=attrs.table_id):
                data = record.data or {}
                number, value = data.get(number_key), data.get(attrs.key)
                if number in PARTS and (value in (None, '', []) or value == as_pairs(OLD_PARTS.get(number, []))):
                    data[attrs.key] = as_pairs(PARTS[number])
                    record.data = data
                    record.save(update_fields=['data'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_part_attributes'),
    ]

    operations = [
        migrations.RunPython(upgrade, migrations.RunPython.noop),
    ]
