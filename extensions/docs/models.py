"""Documentation: pages in a tree, a section of it for each space.

A page belongs to a space (a record of a space table, see core.space) and
carries access tags like a record: its own (``tags``) and its space's
(``access`` is both), so a page in a tagged project is seen only by people who
hold the project's tags.

The body is HTML cleaned by ``core.canvas.sanitize``; live parts (views,
records, cards, values, calculations, app cards, blocks) are filled in when
the page is shown (``core.canvas.render``).
"""
from django.conf import settings
from django.db import models
from django.urls import reverse


class Page(models.Model):
    space = models.ForeignKey('core.Record', on_delete=models.CASCADE, related_name='doc_pages')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    title = models.CharField(max_length=200)
    emoji = models.CharField(max_length=8, blank=True)
    body = models.TextField(blank=True)
    labels = models.CharField(max_length=300, blank=True, help_text='Comma separated.')
    tags = models.JSONField(default=list, blank=True)
    access = models.JSONField(default=list, blank=True)
    position = models.IntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('docs:page', args=[self.pk])

    @property
    def label_list(self):
        return [l.strip() for l in self.labels.split(',') if l.strip()]

    def ancestors(self):
        chain, seen, node = [], {self.pk}, self.parent
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def descendant_ids(self):
        ids, frontier = set(), [self.pk]
        while frontier:
            frontier = [pk for pk in Page.objects.filter(parent_id__in=frontier).values_list('pk', flat=True) if pk not in ids]
            ids.update(frontier)
        return ids


class PageVersion(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['page', 'version'], name='unique_page_version')]


class PageComment(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class PagePin(models.Model):
    """A page someone pinned (shown by the "Pinned pages" block)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pinned_pages')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='pins')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'page'], name='unique_page_pin')]


class PageReference(models.Model):
    """A record a page mentions (a link, a card or a value), so the record can show the pages that mention it.
    Kept in step with the page's body each time it is saved (see ``references.sync``)."""
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='references')
    record = models.ForeignKey('core.Record', on_delete=models.CASCADE, related_name='page_references')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['page', 'record'], name='unique_page_reference')]


class PageFile(models.Model):
    """A picture or file put on a page."""
    page = models.ForeignKey(Page, null=True, blank=True, on_delete=models.SET_NULL, related_name='files')
    space = models.ForeignKey('core.Record', on_delete=models.CASCADE, related_name='+')
    file = models.FileField(upload_to='pages/%Y/%m/', max_length=300)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        return reverse('docs:file', args=[self.pk])
