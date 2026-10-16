"""What a page uses: views, records, fields and apps (so they aren't removed from under it)."""
import re

from ..models import App, Layout, Record

VIEWS = re.compile(r'\bdata-view="(\d+)"')
RECORDS = re.compile(r'\bdata-record="(\d+)"')
FIELD = re.compile(r'\bdata-field="(\d+)"')
FIELDS = re.compile(r'\bdata-fields="([\d,]+)"')
APPS = re.compile(r'\bdata-app="([a-z0-9-]+)"')


def record_ids(body):
    return {int(x) for x in RECORDS.findall(body or '')}


def uses(body, removal, gone, removed_records, removed_slugs):
    """Whether ``body`` shows something ``removal`` takes away."""
    body = body or ''
    if removal.views and {int(x) for x in VIEWS.findall(body)} & removal.views:
        return True
    if removed_records and record_ids(body) & removed_records:
        return True
    if gone:
        used = {int(x) for x in FIELD.findall(body)}
        for group in FIELDS.findall(body):
            used |= {int(x) for x in group.split(',') if x}
        if used & set(gone):
            return True
    return bool(removed_slugs and set(APPS.findall(body)) & removed_slugs)


def targets(removal):
    """(record ids, app slugs) a removal takes away."""
    removed_records = set(Record.objects.filter(table_id__in=removal.tables).values_list('pk', flat=True)) if removal.tables else set()
    removed_slugs = set(App.objects.filter(pk__in=removal.apps).values_list('slug', flat=True)) if removal.apps else set()
    return removed_records, removed_slugs


def used_in(removal, gone):
    """Space pages and app home pages that show something being removed."""
    removed_records, removed_slugs = targets(removal)
    out = []
    for layout in Layout.objects.select_related('record__table', 'app'):
        if layout.app_id and layout.app_id in removal.apps:
            continue
        if layout.record_id and layout.record.table_id in removal.tables:
            continue
        if uses(layout.body, removal, gone, removed_records, removed_slugs):
            if layout.app_id:
                out.append(f'The home page of the app {layout.app.name} shows it.')
            else:
                from ..data import Data
                out.append(f'The page of the space {Data().label(layout.record)} shows it.')
    return out
