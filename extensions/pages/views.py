"""Pages: a space's page tree, reading, writing, history, comments and pins.

Who may do what follows the space: viewers read and comment, editors write
pages, space admins (and a page's author) also delete and move them."""
import mimetypes
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.models import App, Space, Table, View
from core.permissions import can, can_space, require_space, visible_apps
from core.space_views import get_space, space_sidebar

from .models import Page, PageComment, PageFile, PagePin, PageVersion
from .render import TEMPLATES, render as render_body
from .sanitize import clean, text_of


def _page(request, pk, needed='viewer'):
    page = get_object_or_404(Page.objects.select_related('space', 'parent', 'updated_by'), pk=pk)
    require_space(request.user, page.space, needed)
    return page


def tree(space, current=None):
    """The space's pages as nested rows: [{'page', 'depth', 'open', 'current'}]."""
    pages = list(Page.objects.filter(space=space).only('pk', 'title', 'emoji', 'parent_id', 'position'))
    children = {}
    for p in pages:
        children.setdefault(p.parent_id, []).append(p)
    open_ids = {a.pk for a in current.ancestors()} | {current.pk} if current else set()
    rows = []

    def walk(parent, depth):
        for p in sorted(children.get(parent, []), key=lambda x: (x.position, x.title.lower())):
            rows.append({'page': p, 'depth': depth, 'has_children': p.pk in children, 'current': current and p.pk == current.pk,
                         'open': p.pk in open_ids})
            walk(p.pk, depth + 1)
    walk(None, 0)
    return rows


def _context(request, space, current=None):
    return {**space_sidebar(request, space), 'tree': tree(space, current),
            'can_write': can_space(request.user, space, 'editor'), 'can_admin': can_space(request.user, space, 'admin')}


@login_required
def space_pages(request, space_key):
    space = get_space(request, space_key)
    label = request.GET.get('label', '').strip()
    pages = Page.objects.filter(space=space).select_related('updated_by').order_by('-updated_at')
    if label:
        pages = [p for p in pages if label.lower() in [l.lower() for l in p.label_list]]
    labels = sorted({l for p in Page.objects.filter(space=space) for l in p.label_list}, key=str.lower)
    return render(request, 'pages/space.html', {**_context(request, space), 'pages': list(pages)[:50], 'label': label,
                                                'labels': labels, 'templates': TEMPLATES})


@login_required
def page_new(request, space_key):
    space = get_space(request, space_key, 'editor')
    parent = Page.objects.filter(pk=request.GET.get('parent') or request.POST.get('parent') or 0, space=space).first()
    tpl = request.GET.get('template', 'blank')
    title, emoji, body = TEMPLATES.get(tpl, TEMPLATES['blank'])
    if request.method == 'POST':
        return _save(request, space, None, parent)
    return render(request, 'pages/edit.html', {**_context(request, space, parent), 'page': None, 'parent': parent,
                                               'title': '' if tpl == 'blank' else title, 'emoji': emoji if tpl != 'blank' else '',
                                               'body': body.strip(), 'labels': '', 'embed_choices': _embed_choices(request.user)})


@login_required
def page_edit(request, pk):
    page = _page(request, pk, 'editor')
    if request.method == 'POST':
        return _save(request, page.space, page, page.parent)
    return render(request, 'pages/edit.html', {**_context(request, page.space, page), 'page': page, 'parent': page.parent,
                                               'title': page.title, 'emoji': page.emoji, 'body': page.body, 'labels': page.labels,
                                               'embed_choices': _embed_choices(request.user)})


def _save(request, space, page, parent):
    title = request.POST.get('title', '').strip()[:200]
    if not title:
        messages.error(request, 'Give the page a title.')
        return redirect(request.path)
    body = clean(request.POST.get('body', ''))
    labels = ', '.join(l.strip() for l in request.POST.get('labels', '').split(',') if l.strip())[:300]
    with transaction.atomic():
        if page is None:
            top = Page.objects.filter(space=space, parent=parent).count()
            page = Page.objects.create(space=space, parent=parent, title=title, emoji=request.POST.get('emoji', '').strip()[:8],
                                       body=body, labels=labels, position=top, created_by=request.user, updated_by=request.user)
            note = 'Created'
        else:
            if (page.title, page.body, page.labels, page.emoji) == (title, body, labels, request.POST.get('emoji', '').strip()[:8]):
                return redirect(page)
            page.version += 1
            page.title, page.body, page.labels = title, body, labels
            page.emoji = request.POST.get('emoji', '').strip()[:8]
            page.updated_by = request.user
            page.save()
            note = request.POST.get('note', '').strip()[:200]
        PageVersion.objects.create(page=page, version=page.version, title=title, body=body, note=note, created_by=request.user)
        PageFile.objects.filter(space=space, page__isnull=True, uploaded_by=request.user, pk__in=_file_ids(body)).update(page=page)
    messages.success(request, f'"{page.title}" is saved.')
    return redirect(page)


def _file_ids(body):
    import re
    return [int(x) for x in re.findall(r'/x/pages/files/(\d+)/', body)]


def _embed_choices(user):
    """Views the writer may put on a page: [(label, view id)]."""
    out = []
    for app in visible_apps(user):
        if app.is_space:
            continue
        for table in app.tables.all():
            for view in table.views.all():
                if view.type in ('grid', 'tree', 'kanban', 'gallery', 'calendar', 'gantt'):
                    out.append((f'{app.name} › {table.name} › {view.name}', view.pk))
    return out


@login_required
def page_view(request, pk):
    page = _page(request, pk)
    version = None
    if request.GET.get('version', '').isdigit():
        version = PageVersion.objects.filter(page=page, version=int(request.GET['version'])).first()
    body = render_body(version.body if version else page.body, request.user)
    return render(request, 'pages/page.html', {
        **_context(request, page.space, page), 'page': page, 'body': body, 'version': version,
        'ancestors': page.ancestors(), 'children': page.children.all(),
        'comments': page.comments.select_related('user'), 'pinned': PagePin.objects.filter(user=request.user, page=page).exists(),
        'versions': page.versions.select_related('created_by')[:30],
        'can_delete': can_space(request.user, page.space, 'admin') or page.created_by_id == request.user.pk,
        'move_targets': [p for p in Page.objects.filter(space=page.space).exclude(pk__in={page.pk} | page.descendant_ids())],
    })


@login_required
@require_POST
def page_restore(request, pk, version):
    page = _page(request, pk, 'editor')
    old = get_object_or_404(PageVersion, page=page, version=version)
    with transaction.atomic():
        page.version += 1
        page.title, page.body, page.updated_by = old.title, old.body, request.user
        page.save()
        PageVersion.objects.create(page=page, version=page.version, title=old.title, body=old.body,
                                   note=f'Back to version {version}', created_by=request.user)
    messages.success(request, f'"{page.title}" is back to version {version}.')
    return redirect(page)


@login_required
@require_POST
def page_delete(request, pk):
    page = _page(request, pk)
    if not (can_space(request.user, page.space, 'admin') or page.created_by_id == request.user.pk):
        raise PermissionDenied('Only the space\'s admins and the page\'s author can delete it.')
    space, parent = page.space, page.parent
    count = 1 + len(page.descendant_ids())
    page.delete()
    messages.success(request, f'"{page.title}" is deleted' + (f', with {count - 1} page{"s" if count > 2 else ""} under it.' if count > 1 else '.'))
    return redirect(parent or ('pages:space', space.key))


@login_required
@require_POST
def page_move(request, pk):
    page = _page(request, pk, 'editor')
    target = request.POST.get('parent', '')
    if target == '':
        page.parent = None
    else:
        parent = get_object_or_404(Page, pk=target, space=page.space)
        if parent.pk == page.pk or parent.pk in page.descendant_ids():
            messages.error(request, 'A page can\'t go under itself.')
            return redirect(page)
        page.parent = parent
    page.save(update_fields=['parent'])
    messages.success(request, f'"{page.title}" is moved.')
    return redirect(page)


@login_required
@require_POST
def page_comment(request, pk):
    page = _page(request, pk)
    text = request.POST.get('text', '').strip()
    if text:
        PageComment.objects.create(page=page, user=request.user, text=text[:5000])
    return redirect(page.get_absolute_url() + '#comments')


@login_required
@require_POST
def page_pin(request, pk):
    page = _page(request, pk)
    pin, created = PagePin.objects.get_or_create(user=request.user, page=page)
    if not created:
        pin.delete()
    return redirect(page)


IMAGES = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
FILES = IMAGES | {'.pdf', '.txt', '.csv', '.docx', '.xlsx', '.pptx', '.zip', '.step', '.stp', '.dxf'}


@login_required
@require_POST
def upload(request, space_key):
    """A picture or file for a page being written (the editor puts it in)."""
    space = get_space(request, space_key, 'editor')
    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'error': 'No file.'}, status=400)
    name = get_valid_filename(os.path.basename(upload.name)) or 'file'
    ext = os.path.splitext(name)[1].lower()
    if ext not in FILES or upload.size > 20 * 1024 * 1024:
        return JsonResponse({'error': f'{name}: only pictures and common documents up to 20 MB.'}, status=400)
    if ext in IMAGES and ext != '.gif':
        from core.uploads import _prepare_image
        content, name, ctype, _ = _prepare_image(upload, name, mimetypes.guess_type(name)[0])
    else:
        content, ctype = upload, mimetypes.guess_type(name)[0] or 'application/octet-stream'
    f = PageFile(space=space, name=name, content_type=ctype, uploaded_by=request.user)
    f.file.save(name, content, save=True)
    return JsonResponse({'url': f.get_absolute_url(), 'name': f.name, 'image': ctype.startswith('image/')})


@login_required
def page_file(request, pk):
    f = get_object_or_404(PageFile.objects.select_related('space'), pk=pk)
    require_space(request.user, f.space, 'viewer')
    try:
        handle = f.file.open('rb')
    except FileNotFoundError:
        raise Http404
    inline = f.content_type.startswith('image/') or f.content_type == 'application/pdf'
    return FileResponse(handle, content_type=f.content_type, as_attachment=not inline, filename=f.name)


@login_required
def records_for_link(request):
    """Records to link to from a page: ?q= across the tables the writer can see."""
    from core.data import Data
    q = request.GET.get('q', '').strip()
    data = Data(request.user)
    out = []
    if q:
        for app in visible_apps(request.user):
            if app.is_space:
                continue
            for table in app.tables.all():
                for r in data.search(table, q, limit=5):
                    out.append({'id': r.pk, 'label': data.label(r), 'where': f'{app.name} › {table.name}'})
                if len(out) >= 30:
                    break
    return JsonResponse({'records': out[:30]})
