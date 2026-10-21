from django.db import migrations

DELIVERY = ('=IF(ISBLANK({Delivery date}), IF(ISBLANK({Supplier.Lead time (days)}), BLANK(), '
            'DATEADD(TODAY(), {Supplier.Lead time (days)}, "days")), {Delivery date})')


def delivery_date(apps, schema_editor):
    """Orders get a delivery date (as the template has from here on): placing an order fills it in from the
    supplier's lead time when it's empty; the order list and board show it, and a calendar of deliveries.

    It adds a field with Osmia's own schema code; it only runs where an Orders app is installed, at the time this
    migration is applied."""
    App = apps.get_model('core', 'App')
    for app_id in App.objects.filter(blueprint='orders').values_list('pk', flat=True):
        _upgrade(app_id)


def _upgrade(app_id):
    from core import schema
    from core.models import Automation, Table, View

    orders = Table.objects.filter(app_id=app_id, key='orders').first()
    if orders is None or orders.fields.filter(key='delivery_date').exists():
        return
    placed = orders.fields.filter(key='placed_at').first()
    schema.add_field(orders, 'Delivery date' if not orders.fields.filter(name__iexact='Delivery date').exists() else 'Delivery date (order)',
                     'date', key='delivery_date', position=placed.position + 1 if placed else None,
                     description="When it is to arrive. Placing the order fills it in from the supplier's lead time, "
                                 "if it's still empty.")
    vendors = orders.fields.filter(key='supplier').first()
    lead_time = vendors is not None and Table.objects.filter(pk=vendors.opt('target'), fields__key='lead_time').exists()
    place = Automation.objects.filter(table=orders, key='place').first()
    if place is not None and lead_time:
        actions = list(place.actions or [])
        for step in actions:
            if step.get('type') == 'update_record' and step.get('target', 'this') == 'this' and 'placed_at' in (step.get('values') or {}):
                step['values'] = {**step['values'], 'delivery_date': DELIVERY}
        place.actions = actions
        place.save(update_fields=['actions'])
    for view in View.objects.filter(table=orders):
        cfg = dict(view.config or {})
        fields = list(cfg.get('fields') or [])
        if view.type == 'grid' and 'placed_at' in fields and 'delivery_date' not in fields:
            fields.insert(fields.index('placed_at') + 1, 'delivery_date')
        elif view.type == 'kanban' and fields and 'delivery_date' not in fields:
            fields.append('delivery_date')
        else:
            continue
        cfg['fields'] = fields
        view.config = cfg
        view.save(update_fields=['config'])
    if not orders.views.filter(name='Deliveries').exists():
        View.objects.create(table=orders, name='Deliveries', type='calendar', position=orders.views.count(),
                            config={'date_field': 'delivery_date', 'color_field': 'status'})


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_harness_sides'),
    ]

    operations = [
        migrations.RunPython(delivery_date, migrations.RunPython.noop),
    ]
