"""The Documentation app: every space's section of the page tree, reading, writing,
history, comments and pins.

Who may do what follows the page's space (core.space.can_edit_page): whoever
can see the space reads and comments (if they hold the page's tags), the
people who may edit the space's page write pages, and a page's author or the
creators of the space's app also delete them."""
import mimetypes
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core.canvas.render import render as render_body
from core.canvas.sanitize import text_of
from core.data import Data
from core.models import Tag
from core.permissions import can
from core.space import space_tables
from core.trees import Tree
from core.canvas.views import editor_config

from .models import Page, PageComment, PageFile, PagePin, PageVersion
from .references import sync as sync_references
from .service import can_read, can_write, space_of, visible_pages, write_page
from .starters import TEMPLATES


def _space(request, space_id, write=False):
    space = space_of(request.user, space_id)
    if space is None:
        raise Http404('There is no such space.')
    if write and not can_write(request.user, space):
        raise PermissionDenied('You can read the pages of this space, not write them.')
    return space


def _page(request, pk, write=False):
    page = get_object_or_404(Page.objects.select_related('space__table', 'parent', 'updated_by'), pk=pk)
    if not can_read(request.user, page):
        raise Http404('There is no such page.')
    if write and not can_write(request.user, page.space):
        raise PermissionDenied('You can read this page, not change it.')
    return page


def tree(user, space, current=None):
    """The space's pages as nested rows: [{'page', 'depth', 'current'}]."""
    pages = visible_pages(user, Page.objects.filter(space=space).only('pk', 'title', 'emoji', 'parent_id', 'position',
                                                                      'access', 'space_id'))
    ids = {p.pk for p in pages}
    children = {}
    for p in pages:
        children.setdefault(p.parent_id if p.parent_id in ids else None, []).append(p)
    rows = []

    def walk(parent, depth):
        for p in sorted(children.get(parent, []), key=lambda x: (x.position, x.title.lower())):
            rows.append({'page': p, 'depth': depth, 'current': current is not None and p.pk == current.pk})
            walk(p.pk, depth + 1)
    walk(None, 0)
    return rows


def _crumbs(user, space):
    data = Data(user)
    t = Tree(data, space.table_id)
    return [(a, data.label(a)) for a in t.ancestors(space.pk)] + [(space, data.label(space))]


def _context(request, space, current=None):
    data = Data(request.user)
    return {'space': space, 'space_label': data.label(space), 'tree': tree(request.user, space, current),
            'space_crumbs': _crumbs(request.user, space), 'can_write': can_write(request.user, space)}


@login_required
def index(request):
    """The Documentation app: a section for each space the reader can see, and recent pages."""
    data = Data(request.user)
    sections = []
    counts = {}
    for p in visible_pages(request.user, Page.objects.only('pk', 'space_id', 'access')):
        counts[p.space_id] = counts.get(p.space_id, 0) + 1
    for table in space_tables():
        if not can(request.user, table.app, 'viewer'):
            continue
        t = Tree(data, table)

        def walk(node, depth):
            sections.append({'space': node, 'label': data.label(node), 'depth': depth, 'count': counts.get(node.pk, 0),
                             'table': table})
            for kid in t.kids(node.pk):
                walk(kid, depth + 1)
        for root in t.roots():
            walk(root, 0)
    recent = visible_pages(request.user, Page.objects.select_related('space', 'updated_by').order_by('-updated_at')[:60])[:15]
    return render(request, 'docs/index.html', {'sections': sections, 'recent': recent, 'labels': {p.space_id: data.label(p.space)
                                                                                                for p in recent}})


@login_required
def space_pages(request, space_id):
    space = _space(request, space_id)
    label = request.GET.get('label', '').strip()
    pages = visible_pages(request.user, Page.objects.filter(space=space).select_related('updated_by').order_by('-updated_at'))
    labels = sorted({l for p in pages for l in p.label_list}, key=str.lower)
    if label:
        pages = [p for p in pages if label.lower() in [l.lower() for l in p.label_list]]
    return render(request, 'docs/space.html', {**_context(request, space), 'pages': pages[:50], 'label': label,
                                               'labels': labels, 'templates': TEMPLATES})


def _tag_choices(user, chosen=()):
    from core.access import user_tags
    mine = user_tags(user)
    return [{'tag': t, 'on': t.pk in chosen, 'mine': t.pk in mine} for t in Tag.objects.all() if t.pk in mine or t.pk in chosen]


@login_required
def page_new(request, space_id):
    space = _space(request, space_id, write=True)
    parent = Page.objects.filter(pk=request.GET.get('parent') or request.POST.get('parent') or 0, space=space).first()
    tpl = request.GET.get('template', 'blank')
    title, emoji, body = TEMPLATES.get(tpl, TEMPLATES['blank'])
    if request.method == 'POST':
        return _save(request, space, None, parent)
    return render(request, 'docs/edit.html', {**_context(request, space, parent), 'page': None, 'parent': parent,
                                              'title': '' if tpl == 'blank' else title, 'emoji': emoji if tpl != 'blank' else '',
                                              'body': body.strip(), 'labels': '', 'tag_choices': _tag_choices(request.user),
                                              'editor': editor_config(request, where='page', upload_url=reverse('docs:upload', args=[space.pk]))})


@login_required
def page_edit(request, pk):
    page = _page(request, pk, write=True)
    if request.method == 'POST':
        return _save(request, page.space, page, page.parent)
    return render(request, 'docs/edit.html', {**_context(request, page.space, page), 'page': page, 'parent': page.parent,
                                              'title': page.title, 'emoji': page.emoji, 'body': page.body, 'labels': page.labels,
                                              'tag_choices': _tag_choices(request.user, page.tags),
                                              'editor': editor_config(request, where='page',
                                                                      upload_url=reverse('docs:upload', args=[page.space_id]))})


def _save(request, space, page, parent):
    try:
        page, changed = write_page(space, request.user, request.POST.get('title', ''), request.POST.get('body', ''),
                                   page=page, parent=parent, emoji=request.POST.get('emoji', ''),
                                   labels=request.POST.get('labels', ''), note=request.POST.get('note', ''),
                                   tags=[t for t in request.POST.getlist('tags') if t.isdigit()])
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect(request.path)
    if changed:
        messages.success(request, f'"{page.title}" is saved.')
    return redirect(page)


@login_required
def page_view(request, pk):
    page = _page(request, pk)
    version = None
    if request.GET.get('version', '').isdigit():
        version = PageVersion.objects.filter(page=page, version=int(request.GET['version'])).first()
    body = render_body(version.body if version else page.body, request, {'space': page.space})
    ancestors = [a for a in page.ancestors() if can_read(request.user, a)]
    return render(request, 'docs/page.html', {
        **_context(request, page.space, page), 'page': page, 'body': body, 'version': version,
        'ancestors': ancestors, 'children': visible_pages(request.user, page.children.all()),
        'comments': page.comments.select_related('user'), 'pinned': PagePin.objects.filter(user=request.user, page=page).exists(),
        'versions': page.versions.select_related('created_by')[:30],
        'tags': Tag.objects.filter(pk__in=page.access or []),
        'can_delete': page.created_by_id == request.user.pk or can(request.user, page.space.table.app, 'creator'),
        'move_targets': [p for p in visible_pages(request.user, Page.objects.filter(space=page.space))
                         if p.pk not in {page.pk} | page.descendant_ids()],
    })


@login_required
@require_POST
def page_restore(request, pk, version):
    page = _page(request, pk, write=True)
    old = get_object_or_404(PageVersion, page=page, version=version)
    with transaction.atomic():
        page.version += 1
        page.title, page.body, page.updated_by = old.title, old.body, request.user
        page.save()
        PageVersion.objects.create(page=page, version=page.version, title=old.title, body=old.body,
                                   note=f'Back to version {version}', created_by=request.user)
        sync_references(page)
    messages.success(request, f'"{page.title}" is back to version {version}.')
    return redirect(page)


@login_required
@require_POST
def page_delete(request, pk):
    page = _page(request, pk)
    if not (page.created_by_id == request.user.pk or can(request.user, page.space.table.app, 'creator')):
        raise PermissionDenied('Only the page\'s author and the builders of its space\'s app can delete it.')
    space, parent = page.space, page.parent
    count = 1 + len(page.descendant_ids())
    page.delete()
    messages.success(request, f'"{page.title}" is deleted' + (f', with {count - 1} page{"s" if count > 2 else ""} under it.' if count > 1 else '.'))
    return redirect(parent or ('docs:space', space.pk))


@login_required
@require_POST
def page_move(request, pk):
    page = _page(request, pk, write=True)
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
def upload(request, space_id):
    """A picture or file for a page being written (the editor puts it in)."""
    space = _space(request, space_id, write=True)
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
    f = get_object_or_404(PageFile.objects.select_related('page'), pk=pk)
    if f.page is not None and not can_read(request.user, f.page):
        raise Http404
    if f.page is None and (space_of(request.user, f.space_id) is None or f.uploaded_by_id != request.user.pk):
        raise Http404
    try:
        handle = f.file.open('rb')
    except FileNotFoundError:
        raise Http404
    inline = f.content_type.startswith('image/') or f.content_type == 'application/pdf'
    return FileResponse(handle, content_type=f.content_type, as_attachment=not inline, filename=f.name)


def search_pages(user, q):
    low = q.lower()
    out = []
    for page in visible_pages(user, Page.objects.select_related('space').order_by('-updated_at')[:2000]):
        if low in page.title.lower() or low in text_of(page.body).lower() or low in page.labels.lower():
            out.append(page)
        if len(out) >= 20:
            break
    return out
