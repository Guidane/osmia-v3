"""Spaces and home pages: everyone lands in their home space; every space and
every app has a page made of blocks that the people who may edit it change
with the slash editor.

A space's page and an app's home start from a default layout until someone
edits them (``default_space_body``, ``default_app_body``)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import space as spaces
from .canvas.render import render as render_body
from .canvas.sanitize import clean
from .canvas.views import editor_config
from .data import Data
from .extensions import registry
from .models import App, Layout, Tag
from .permissions import can, require, visible_apps
from .trees import Tree


def _block(key):
    block = registry.blocks.get(key)
    if block is None:
        return ''
    return f'<div class="live-block" data-block="{key}">{block.icon} {block.label}</div>'


def _grid(*cells):
    return (f'<div class="grid-block" data-cols="{len(cells)}">'
            + ''.join(f'<div class="grid-cell">{c or "<p><br></p>"}</div>' for c in cells) + '</div>')


def default_space_body(record, user, is_home):
    if is_home:
        return (_grid(_block('my_work'), _block('notifications') + _block('pinned_pages'))
                + _block('apps') + '<p><br></p>')
    return (_grid(_block('linked'), _block('child_spaces')) + _block('space_pages') + '<p><br></p>')


def default_app_body(app):
    about = f'<p>{app.description}</p>' if app.description else ''
    return about + _block('tables') + '<p><br></p>'


# -- Spaces ------------------------------------------------------------------------------

def get_space(request, pk):
    data = Data(request.user)
    record = data.record(pk)
    if record is None:
        raise Http404('There is no such space.')
    table = data.table(record.table_id)
    if not (table.is_space and table.tree_field_id):
        raise Http404('That record is not a space.')
    require(request.user, table.app, 'viewer')
    return data, record, table


def _space_context(request, data, record, table):
    tree = Tree(data, table)
    home = spaces.home_node(request.user, create=False)
    is_home = home is not None and home.pk == record.pk
    kind = next((f for f in data.fields(table) if f.key == 'kind' and f.type == 'select'), None)
    return {
        'space': record, 'space_label': data.label(record), 'space_table': table, 'is_home': is_home,
        'ancestors': [(a, data.label(a)) for a in tree.ancestors(record.pk)],
        'kind': data.text(record, kind) if kind else '',
        'can_edit': spaces.can_edit_page(request.user, record, data),
        'tags': Tag.objects.filter(pk__in=record.access or []),
    }


def show_space(request, data, record, table):
    context = _space_context(request, data, record, table)
    layout = spaces.layout_of(record=record)
    body = layout.body if layout else default_space_body(record, request.user, context['is_home'])
    context['body'] = render_body(body, request, {'space': record})
    context['layout'] = layout
    return render(request, 'core/space.html', context)


@login_required
def home(request):
    """Your home space; made for you the first time."""
    record = spaces.home_node(request.user)
    if record is None:
        return launcher(request, first_time=True)
    data = Data(request.user)
    seen = data.record(record.pk)
    if seen is None:   # someone put tags on it that the person doesn't hold
        return launcher(request, first_time=False)
    return show_space(request, data, seen, data.table(seen.table_id))


@login_required
def space_page(request, pk):
    data, record, table = get_space(request, pk)
    return show_space(request, data, record, table)


@login_required
def space_edit(request, pk):
    data, record, table = get_space(request, pk)
    if not spaces.can_edit_page(request.user, record, data):
        raise PermissionDenied('You can look at this space, not change its page.')
    context = _space_context(request, data, record, table)
    layout = spaces.layout_of(record=record)
    if request.method == 'POST':
        if 'reset' in request.POST:
            if layout:
                layout.delete()
            messages.success(request, 'The page is back to how it started.')
        else:
            Layout.objects.update_or_create(record=record, defaults={'body': clean(request.POST.get('body', '')),
                                                                     'updated_by': request.user})
            messages.success(request, 'The page is saved.')
        return redirect('core:home' if context['is_home'] else 'core:space', *([] if context['is_home'] else [record.pk]))
    body = layout.body if layout else default_space_body(record, request.user, context['is_home'])
    return render(request, 'core/space_edit.html', {**context, 'body': body, 'layout': layout,
                                                    'editor': editor_config(request, where='space')})


# -- The launcher and app home pages -----------------------------------------------------------

@login_required
def launcher(request, first_time=False):
    data = Data(request.user)
    trees = []
    for table in spaces.space_tables():
        if can(request.user, table.app, 'viewer'):
            t = Tree(data, table)
            rows = []

            def walk(node, depth):
                rows.append((node, data.label(node), depth))
                if depth < 2:
                    for kid in t.kids(node.pk):
                        walk(kid, depth + 1)
            for root in t.roots():
                walk(root, 0)
            trees.append({'table': table, 'rows': rows})
    return render(request, 'core/launcher.html', {'apps': visible_apps(request.user),
                                                  'extension_apps': registry.apps_for(request),
                                                  'trees': trees, 'first_time': first_time})


def app_context(app, user):
    """What the app bar needs: the app's tabs and what the person may do."""
    return {'app': app, 'tables': list(app.tables.prefetch_related('views')), 'can_build': can(user, app, 'creator'),
            'can_edit': can(user, app, 'editor'), 'app_pages': registry.pages_for_app(app)}


@login_required
def app_home(request, app_slug):
    app = get_object_or_404(App, slug=app_slug)
    require(request.user, app, 'viewer')
    layout = spaces.layout_of(app=app)
    body = layout.body if layout else default_app_body(app)
    return render(request, 'core/app_home.html', {**app_context(app, request.user), 'app_home': True, 'layout': layout,
                                                  'body': render_body(body, request, {'app': app})})


@login_required
def app_home_edit(request, app_slug):
    app = get_object_or_404(App, slug=app_slug)
    require(request.user, app, 'creator')
    layout = spaces.layout_of(app=app)
    if request.method == 'POST':
        if 'reset' in request.POST:
            if layout:
                layout.delete()
            messages.success(request, 'The home page is back to how it started.')
        else:
            Layout.objects.update_or_create(app=app, defaults={'body': clean(request.POST.get('body', '')),
                                                               'updated_by': request.user})
            messages.success(request, f'The home page of {app.name} is saved.')
        return redirect('core:app', app.slug)
    body = layout.body if layout else default_app_body(app)
    return render(request, 'core/app_home_edit.html', {**app_context(app, request.user), 'app_home': True, 'layout': layout,
                                                       'body': body, 'editor': editor_config(request, where='app')})
