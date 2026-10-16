"""Which records a page mentions, so a record can list the pages that mention it."""
from core.canvas.references import record_ids
from core.models import Record


def sync(page):
    """Make the page's references match its body."""
    from .models import PageReference
    wanted = set(Record.objects.filter(pk__in=record_ids(page.body)).values_list('pk', flat=True))
    have = set(page.references.values_list('record_id', flat=True))
    page.references.filter(record_id__in=have - wanted).delete()
    PageReference.objects.bulk_create([PageReference(page=page, record_id=pk) for pk in wanted - have], ignore_conflicts=True)
