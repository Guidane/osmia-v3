"""Writing a page: the one way pages are made and changed (the editor, the AI assistant).
Whoever calls it has checked that ``user`` may write in ``space``."""
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Page, PageFile, PageVersion
from .references import sync as sync_references
from .sanitize import clean


def _file_ids(body):
    return [int(x) for x in re.findall(r'/x/pages/files/(\d+)/', body)]


@transaction.atomic
def write_page(space, user, title, body, page=None, parent=None, emoji='', labels='', note=''):
    """Make a page (``page`` None) or save a new version of it. Returns (page, changed)."""
    title = (title or '').strip()[:200]
    if not title:
        raise ValidationError('Give the page a title.')
    body = clean(body or '')
    labels = ', '.join(l.strip() for l in (labels or '').split(',') if l.strip())[:300]
    emoji = (emoji or '').strip()[:8]
    if page is None:
        top = Page.objects.filter(space=space, parent=parent).count()
        page = Page.objects.create(space=space, parent=parent, title=title, emoji=emoji, body=body, labels=labels,
                                   position=top, created_by=user, updated_by=user)
        note = 'Created'
    else:
        if (page.title, page.body, page.labels, page.emoji) == (title, body, labels, emoji):
            return page, False
        page.version += 1
        page.title, page.body, page.labels, page.emoji = title, body, labels, emoji
        page.updated_by = user
        page.save()
    PageVersion.objects.create(page=page, version=page.version, title=title, body=body, note=(note or '')[:200], created_by=user)
    PageFile.objects.filter(space=space, page__isnull=True, uploaded_by=user, pk__in=_file_ids(body)).update(page=page)
    sync_references(page)
    return page, True
