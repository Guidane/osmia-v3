"""Home, spaces and app home pages: pages made of blocks that the people who may edit them change with the
slash editor. Everyone lands on Home: a page of their own, with a tab for each role they hold (a role is a
space: its page is the role's, and stays with the role).

A page starts from a default layout until someone edits it (``default_home_body``, ``default_space_body``,
``default_app_body``)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_POST

from . import space as spaces
from .canvas.render import render as render_body
from .canvas.sanitize import clean
from .canvas.views import editor_config
from .data import Data
from .extensions import registry
from .models import App, Layout, Tag
from .permissions import can, require
from .trees import Tree


def _block(key):
    block = registry.blocks.get(key)
    if block is None:
        return ''
    return f'<div class="live-block" data-block="{key}">{block.icon} {block.label}</div>'


def _grid(*cells):
    return (f'<div class="grid-block" data-cols="{len(cells)}">'
            + ''.join(f'<div class="grid-cell">{c or "<p><br></p>"}</div>' for c in cells) + '</div>')


def _app_cards(request):
    """Every app the person can open, a heading for each group and a card for each app: pieces of the page
    to rename, move or take away, where the Apps block is one piece that always shows them all."""
    out = ''
    for group, apps in spaces.app_groups(request):
        cards = ''.join(f'<a class="app-card" data-app="{a.slug}" href="{escape(a.get_absolute_url())}">'
                        f'{escape(a.icon)} {escape(a.name)}</a> ' for a in apps)
        out += (f'<h3>{escape(group)}</h3>' if group else '') + f'<p>{cards}</p>'
    return out


def default_home_body(request):
    """Someone's own page: their work, notifications and pinned pages, and their apps by group."""
    return (_grid(_block('my_work'), _block('notifications') + _block('pinned_pages'))
            + _app_cards(request) + '<p><br></p>')


def default_space_body(request, record):
    """A space's page (a role's too): what links to it, the spaces under it, its pages."""
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


def home_tabs(request, data, current=None, page=None):
    """Home's tabs: your own page, the tabs you added, then a tab for each role you hold. ``current`` is the
    role shown, ``page`` the added tab shown (neither: your own page)."""
    tabs = [{'label': 'Me', 'icon': '🏠', 'url': reverse('core:home'), 'on': current is None and page is None,
             'where': ''}]
    for own in Layout.objects.filter(user=request.user).exclude(title='').order_by('position', 'pk'):
        tabs.append({'label': own.title, 'icon': '📌', 'url': reverse('core:home_page', args=[own.pk]),
                     'on': page is not None and page.pk == own.pk, 'where': ''})
    for role in spaces.roles_of(request.user):
        seen = data.record(role.pk)
        if seen is None:   # tags on it that the holder doesn't hold
            continue
        parent = Tree(data, seen.table_id).ancestors(seen.pk)
        tabs.append({'label': data.label(seen), 'icon': '💼', 'url': reverse('core:space', args=[seen.pk]),
                     'on': current is not None and current.pk == seen.pk,
                     'where': data.label(parent[-1]) if parent else ''})
    return tabs


def _space_context(request, data, record, table):
    tree = Tree(data, table)
    kind = next((f for f in data.fields(table) if f.key == 'kind' and f.type == 'select'), None)
    return {
        'space': record, 'space_label': data.label(record), 'space_table': table,
        'home_tabs': home_tabs(request, data, record) if spaces.holds(request.user, record) else None,
        'ancestors': [(a, data.label(a)) for a in tree.ancestors(record.pk)],
        'kind': data.text(record, kind) if kind else '',
        'can_edit': spaces.can_edit_page(request.user, record, data),
        'tags': Tag.objects.filter(pk__in=record.access or []),
    }


def show_space(request, data, record, table):
    context = _space_context(request, data, record, table)
    layout = spaces.layout_of(record=record)
    body = layout.body if layout else default_space_body(request, record)
    context['body'] = render_body(body, request, {'space': record})
    context['layout'] = layout
    return render(request, 'core/space.html', context)


def _added_tab(request, pk):
    """A tab someone added to their Home: theirs only."""
    return get_object_or_404(Layout, pk=pk, user=request.user, title__gt='')


@login_required
def home(request, pk=None):
    """Your own page (or a tab you added, ``pk``), with the tabs you added and a tab for each role you hold."""
    data = Data(request.user)
    page = _added_tab(request, pk) if pk else None
    layout = page or spaces.layout_of(user=request.user)
    body = layout.body if layout else default_home_body(request)
    return render(request, 'core/home.html', {
        'tabs': home_tabs(request, data, page=page), 'page': page, 'layout': layout,
        'body': render_body(body, request, {}),
        'can_hold_roles': any(spaces.holder_field(t) for t in spaces.space_tables())})


@login_required
def home_edit(request, pk=None):
    """Change your own page, or a tab you added (rename it, or take it away); only you do."""
    page = _added_tab(request, pk) if pk else None
    layout = page or spaces.layout_of(user=request.user)
    if request.method == 'POST':
        if page is not None and 'remove' in request.POST:
            page.delete()
            messages.success(request, f'The tab {page.title} is taken away.')
            return redirect('core:home')
        if page is None and 'reset' in request.POST:
            if layout:
                layout.delete()
            messages.success(request, 'Your page is back to the default.')
            return redirect('core:home')
        body = clean(request.POST.get('body', ''))
        if page is not None:
            page.title = request.POST.get('title', '').strip()[:60] or page.title
            page.body, page.updated_by = body, request.user
            page.save()
            messages.success(request, f'{page.title} is saved.')
            return redirect('core:home_page', page.pk)
        Layout.objects.update_or_create(user=request.user, title='', defaults={'body': body, 'updated_by': request.user})
        messages.success(request, 'Your page is saved.')
        return redirect('core:home')
    body = layout.body if layout else default_home_body(request)
    return render(request, 'core/home_edit.html', {'body': body, 'layout': layout, 'page': page,
                                                   'editor': editor_config(request, where='page')})


@login_required
@require_POST
def home_tab_new(request):
    """Add a tab to your Home: a page of your own to fill, after your other tabs."""
    title = request.POST.get('title', '').strip()[:60] or 'New tab'
    last = Layout.objects.filter(user=request.user).order_by('-position').first()
    page = Layout.objects.create(user=request.user, title=title, position=(last.position + 1) if last else 1,
                                 body='<p><br></p>', updated_by=request.user)
    return redirect('core:home_page_edit', page.pk)


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
            messages.success(request, 'The page is back to the default.')
        else:
            Layout.objects.update_or_create(record=record, defaults={'body': clean(request.POST.get('body', '')),
                                                                     'updated_by': request.user})
            messages.success(request, 'The page is saved.')
        return redirect('core:space', record.pk)
    body = layout.body if layout else default_space_body(request, record)
    return render(request, 'core/space_edit.html', {**context, 'body': body, 'layout': layout,
                                                    'editor': editor_config(request, where='space')})


# -- The launcher and app home pages -----------------------------------------------------------

@login_required
def launcher(request):
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
    return render(request, 'core/launcher.html', {'groups': spaces.app_groups(request), 'trees': trees})


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
            messages.success(request, 'The home page is back to the default.')
        else:
            Layout.objects.update_or_create(app=app, defaults={'body': clean(request.POST.get('body', '')),
                                                               'updated_by': request.user})
            messages.success(request, f'The home page of {app.name} is saved.')
        return redirect('core:app', app.slug)
    body = layout.body if layout else default_app_body(app)
    return render(request, 'core/app_home_edit.html', {**app_context(app, request.user), 'app_home': True, 'layout': layout,
                                                       'body': body, 'editor': editor_config(request, where='app')})
