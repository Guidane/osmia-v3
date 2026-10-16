"""Blocks: live parts of a page that aren't a view or a record, put on with the
slash menu (``/my work``, ``/child spaces``, ...). Core has the ones below;
extensions add their own with ``registry.block``.

A block is a function ``fn(request, context) -> html`` (or '' to show
nothing); ``context`` has ``data`` and, on a space's page, ``space`` (the
record), on an app's home, ``app``.
"""
from django.template.loader import render_to_string
from django.utils.html import escape

from ..extensions import registry


def render_block(key, request, context):
    block = registry.blocks.get(key)
    if block is None:
        return ''
    try:
        html = block.fn(request, context)
    except Exception:   # one broken block never breaks the page around it
        import logging
        logging.getLogger(__name__).exception('Block %s failed', key)
        return f'<div class="embed-missing">The block "{escape(block.label)}" could not be shown.</div>'
    if not html:
        return ''
    return f'<section class="live-block live"><h3 class="block-title">{block.icon} {escape(block.label)}</h3>{html}</section>'


def my_work(request, context):
    from .. import space
    from ..permissions import visible_apps
    data = context['data']
    apps = visible_apps(request.user)
    return render_to_string('core/canvas/_my_work.html', {
        'assigned': space.assigned(request.user, data, apps), 'recent': space.recent(request.user, data),
        'starred': space.starred(request.user, data)}, request=request)


def notifications(request, context):
    from ..models import Notification
    items = list(Notification.objects.filter(user=request.user, read=False)[:8])
    return render_to_string('core/canvas/_notifications.html', {'items': items}, request=request)


def apps(request, context):
    from ..permissions import visible_apps
    found = visible_apps(request.user)
    return render_to_string('core/canvas/_apps.html', {'apps': found, 'extension_apps': registry.apps_for(request)},
                            request=request)


def children(request, context):
    from ..trees import Tree
    record, data = context.get('space'), context['data']
    if record is None:
        return ''
    tree = Tree(data, record.table_id)
    kids = tree.kids(record.pk)
    return render_to_string('core/canvas/_children.html', {'kids': [(k, data.label(k)) for k in kids], 'record': record},
                            request=request)


def linked(request, context):
    from .. import space
    from ..permissions import can
    from ..trees import Tree
    record, data = context.get('space'), context['data']
    if record is None:
        return ''
    groups = []
    for field, table, records in space.linked_here(data, record, Tree(data, record.table_id)):
        if not can(request.user, table.app, 'viewer'):
            continue
        groups.append({'field': field, 'table': table, 'rows': [(r, data.label(r)) for r in records[:12]],
                       'more': max(0, len(records) - 12), 'count': len(records)})
    return render_to_string('core/canvas/_linked.html', {'groups': groups, 'record': record}, request=request)


def tables(request, context):
    app = context.get('app')
    if app is None:
        return ''
    return render_to_string('core/canvas/_tables.html', {'app': app, 'tables': list(app.tables.all())}, request=request)


def register_core_blocks():
    registry.block('my_work', 'My work', my_work, icon='☑', help='What is assigned to you, what you opened lately, what you starred.')
    registry.block('notifications', 'Notifications', notifications, icon='🔔', help='Your unread notifications.')
    registry.block('apps', 'Apps', apps, icon='▦', help='Every app you can open, as small cards.')
    registry.block('child_spaces', 'Spaces under this one', children, icon='🌳', where='space',
                   help='The spaces under this space in its tree.')
    registry.block('linked', 'Linked to this space', linked, icon='⇄', where='space',
                   help='Records that link to this space or to the spaces under it.')
    registry.block('tables', 'Tables of this app', tables, icon='▤', where='app', help='The app\'s tables as cards.')
