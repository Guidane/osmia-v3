from django.db import migrations, models

# The groups the templates came with when groups were added, for apps installed before.
TEMPLATE_GROUPS = {
    'departments': 'Management', 'projects': 'Management', 'tasks': 'Management', 'budgets': 'Management',
    'vendors': 'Purchasing', 'orders': 'Purchasing',
    'parts': 'Production', 'stock': 'Production', 'assemblies': 'Production', 'tools': 'Production',
    'devices': 'Production', 'harness': 'Production',
}


def group_template_apps(apps, schema_editor):
    App = apps.get_model('core', 'App')
    for key, group in TEMPLATE_GROUPS.items():
        App.objects.filter(blueprint=key, group='').update(group=group)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='group',
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.RunPython(group_template_apps, migrations.RunPython.noop),
    ]
