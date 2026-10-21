"""Writing pages, and who may read and write them.

A page is read by whoever can see its space (the record) and holds the page's
tags; it is written by the people who may edit its space's page (core.space).
Writing goes through ``write_page``, the one way pages are made and changed
(the editor, the AI prompt generator)."""
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from core.access import allows, user_tags
from core.canvas.sanitize import clean
from core.data import Data
from core.models import Record, Tag
from core.permissions import can

from .models import Page, PageFile, PageVersion
from .references import sync as sync_references


def space_of(user, space_id):
    """The space (record) if ``user`` can see it and its app, else None."""
    data = Data(user)
    record = data.record(space_id)
    if record is None or not record.table.is_space or not can(user, record.table.app, 'viewer'):
        return None
    return record


def can_read(user, page):
    return allows(user, page.access or []) and space_of(user, page.space_id) is not None


def can_write(user, space):
    from core.space import can_edit_page
    return can_edit_page(user, space, Data(user))


def visible_pages(user, pages):
    spaces = {}
    out = []
    for p in pages:
        if p.space_id not in spaces:
            spaces[p.space_id] = space_of(user, p.space_id) is not None
        if spaces[p.space_id] and allows(user, p.access or []):
            out.append(p)
    return out


def refresh_access(space_ids):
    """A page carries its space's tags as well as its own (called when spaces' tags change)."""
    spaces = dict(Record.objects.filter(pk__in=space_ids).values_list('pk', 'access'))
    changed = []
    for page in Page.objects.filter(space_id__in=space_ids):
        new = sorted(set(page.tags or []) | set(spaces.get(page.space_id) or []))
        if new != sorted(page.access or []):
            page.access = new
            changed.append(page)
    Page.objects.bulk_update(changed, ['access'])


def _file_ids(body):
    return [int(x) for x in re.findall(r'/x/docs/files/(\d+)/', body)]


def _clean_tags(tag_ids, user, old=()):
    tag_ids = sorted({int(t) for t in tag_ids or []})
    if len(Tag.objects.filter(pk__in=tag_ids)) != len(tag_ids):
        raise ValidationError('One of those tags no longer exists.')
    touched = set(old) ^ set(tag_ids)
    if user is not None and not touched <= user_tags(user):
        raise ValidationError('Only people who hold a tag can put it on a page or take it off.')
    return tag_ids


@transaction.atomic
def write_page(space, user, title, body, page=None, parent=None, emoji='', labels='', note='', tags=None):
    """Make a page (``page`` None) or save a new version of it. Returns (page, changed)."""
    title = (title or '').strip()[:200]
    if not title:
        raise ValidationError('Give the page a title.')
    body = clean(body or '')
    labels = ', '.join(l.strip() for l in (labels or '').split(',') if l.strip())[:300]
    emoji = (emoji or '').strip()[:8]
    new_tags = _clean_tags(tags, user, page.tags if page else ()) if tags is not None else (page.tags if page else [])
    if page is None:
        top = Page.objects.filter(space=space, parent=parent).count()
        page = Page.objects.create(space=space, parent=parent, title=title, emoji=emoji, body=body, labels=labels,
                                   tags=new_tags, position=top, created_by=user, updated_by=user)
        note = 'Created'
    else:
        if (page.title, page.body, page.labels, page.emoji, page.tags) == (title, body, labels, emoji, new_tags):
            return page, False
        page.version += 1
        page.title, page.body, page.labels, page.emoji, page.tags = title, body, labels, emoji, new_tags
        page.updated_by = user
        page.save()
    page.access = sorted(set(page.tags) | set(space.access or []))
    page.save(update_fields=['access'])
    PageVersion.objects.create(page=page, version=page.version, title=title, body=body, note=(note or '')[:200], created_by=user)
    PageFile.objects.filter(space=space, page__isnull=True, uploaded_by=user, pk__in=_file_ids(body)).update(page=page)
    sync_references(page)
    return page, True
