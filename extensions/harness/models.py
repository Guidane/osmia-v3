from django.conf import settings
from django.db import models


class DrawingVersion(models.Model):
    """Every save of a harness project's drawing (the project itself is a record
    of the Harness app's "Harness projects" table)."""
    record_id = models.BigIntegerField(db_index=True)
    version = models.PositiveIntegerField()
    data = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['record_id', 'version'], name='unique_drawing_version')]
