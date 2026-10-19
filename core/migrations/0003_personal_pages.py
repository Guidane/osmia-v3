import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def split_homes(apps, schema_editor):
    """Everyone's home was their node of a tree of spaces (a Person in Organisation). Now a node someone is named
    on is a role they hold, and their Home is a page of their own: a page they had made on their node becomes
    their own page, and the Organisation's Person nodes become Roles held by the same people."""
    Field = apps.get_model('core', 'Field')
    Layout = apps.get_model('core', 'Layout')
    Record = apps.get_model('core', 'Record')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    for field in Field.objects.filter(type='user', table__is_space=True):
        if not (field.options or {}).get('home'):
            continue
        for layout in Layout.objects.filter(record__table_id=field.table_id):
            held = layout.record.data.get(field.key)
            ids = held if isinstance(held, list) else [held]
            people = [i for i in ids if isinstance(i, int)]
            if len(people) == 1 and not Layout.objects.filter(user_id=people[0], title='').exists() \
                    and User.objects.filter(pk=people[0]).exists():
                layout.record = None
                layout.user_id = people[0]
                layout.save()
    # the Organisation template: Person → Role, held by the person named on it
    for field in Field.objects.filter(table__app__blueprint='departments', table__key='departments'):
        options = dict(field.options or {})
        if field.key == 'kind' and field.type == 'select':
            options['choices'] = [{**c, 'value': 'Role'} if c.get('value') == 'Person' else c
                                  for c in options.get('choices') or []]
            field.options = options
            field.save(update_fields=['options'])
            for record in Record.objects.filter(table_id=field.table_id, data__kind='Person'):
                record.data['kind'] = 'Role'
                record.save(update_fields=['data'])
        elif field.key == 'person' and field.type == 'user' and field.name == 'Person':
            field.name = 'Held by'
            field.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_app_group'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='layout',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='home_pages', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='layout',
            name='title',
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name='layout',
            name='position',
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(split_homes, migrations.RunPython.noop),
    ]
