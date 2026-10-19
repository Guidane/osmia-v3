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


def where(layout):
    """Which page a Layout is, for people: "the page of the space Engineering", "Alice's Home (tab Week plan)"."""
    if layout.app_id:
        return f'the home page of the app {layout.app.name}'
    if layout.user_id:
        who = layout.user.get_full_name() or layout.user.username
        return f"{who}'s Home" + (f' (the tab {layout.title})' if layout.title else '')
    from ..data import Data
    return f'the page of the space {Data().label(layout.record)}'


def used_in(removal, gone):
    """Space pages and app home pages that show something being removed."""
    removed_records, removed_slugs = targets(removal)
    out = []
    for layout in Layout.objects.select_related('record__table', 'app', 'user'):
        if layout.app_id and layout.app_id in removal.apps:
            continue
        if layout.record_id and layout.record.table_id in removal.tables:
            continue
        if uses(layout.body, removal, gone, removed_records, removed_slugs):
            page = where(layout)
            out.append(f'{page[0].upper()}{page[1:]} shows it.')
    return out
