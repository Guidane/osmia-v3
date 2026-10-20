from django.db import migrations


def pairs(text):
    """"Resistance: 10 kΩ" lines (or "Resistance = 10 kΩ") as name-value pairs; a name used twice keeps its first."""
    out, seen = [], set()
    for line in str(text or '').replace(';', '\n').splitlines():
        name, value = line, ''
        for sep in (':', '='):
            if sep in line:
                name, value = line.split(sep, 1)
                break
        name, value = ' '.join(name.split())[:60], ' '.join(value.split())[:200]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append({'name': name, 'value': value})
    return out


def to_pairs(apps, schema_editor):
    """The Parts template's Attributes were text, one "Name: value" per line; now they are name-value pairs."""
    Field = apps.get_model('core', 'Field')
    Record = apps.get_model('core', 'Record')
    for field in Field.objects.filter(table__app__blueprint='parts', table__key='parts', key='attributes', type='longtext'):
        for record in Record.objects.filter(table_id=field.table_id):
            value = (record.data or {}).get(field.key)
            if isinstance(value, str):
                record.data[field.key] = pairs(value)
                record.save(update_fields=['data'])
        field.type = 'attributes'
        if field.description.startswith('e.g. Resistance: 10 kΩ, one per line'):
            field.description = "Name-value pairs, e.g. Resistance 10 kΩ; the part's category lists the ones to fill in."
        field.save(update_fields=['type', 'description'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_personal_pages'),
    ]

    operations = [
        migrations.RunPython(to_pairs, migrations.RunPython.noop),
    ]
