from django.db import migrations


def remove_harness_designer(apps, schema_editor):
    """The harness designer extension is gone (harnesses are an ordinary template now, Harnesses): the apps it
    brought (Harness, then Devices, which Harness needs) are deleted with their records, and so are the designer's
    own tables. An app something else still uses is left, to delete by hand.

    Deleting an app goes through Osmia's own schema code (it removes what the app added to other apps' tables);
    it only runs where those apps are installed, at the time this migration is applied."""
    App = apps.get_model('core', 'App')
    from django.core.exceptions import ValidationError
    for key in ('harness', 'devices'):
        for app_id in App.objects.filter(blueprint=key).values_list('pk', flat=True):
            from core import schema
            from core.models import App as LiveApp
            try:
                schema.delete_app(LiveApp.objects.get(pk=app_id))
            except ValidationError as exc:
                print(f'\n  The app made from the template "{key}" is kept: {" ".join(exc.messages)}')
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            if table.startswith('harness_'):
                cursor.execute(f'DROP TABLE {connection.ops.quote_name(table)}')
        cursor.execute("DELETE FROM django_migrations WHERE app = 'harness'")
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='harness').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_tool_types'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(remove_harness_designer, migrations.RunPython.noop),
    ]
