"""Static file URLs with a version: /static/core/osmia.css?v=1760000000.

The version is the file's modification time, so a browser loads the new file
as soon as it changes (an update, an edited extension) instead of showing a
page with yesterday's styles and scripts."""
import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class VersionedStaticStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        path = finders.find(name)
        if isinstance(path, list):
            path = path[0] if path else None
        if path and os.path.exists(path):
            url += ('&' if '?' in url else '?') + f'v={int(os.path.getmtime(path))}'
        return url
