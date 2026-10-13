"""Extensions: code that adds what tables, fields and automations can't.

An app (tables, fields, views, automations) is made on the website. When an
app needs more graphics or behaviour than that, e.g. the harness designer's
drawing canvas, that part is an extension: a Django app in
``extensions/<name>/`` with

    extension.json     {"name", "title", "version", "description", "icon", "blueprints": ["harness"]}
    apps.py            class Config(ExtensionConfig): name = 'extensions.<name>'
    extension.py       def register(registry): ...
    urls.py            (optional) mounted at /x/<name>/, namespace <name>
    blueprints/*.json  (optional) app templates the extension works with

``register`` can add:

    registry.view_type(MyViewType)                 a new kind of view (see core.viewtypes.ViewType)
    registry.field_type(MyFieldType)               a new kind of field (see core.fieldtypes.FieldType)
    registry.action('key', 'Label', params)(fn)    a new automation action (see core.automation)
    registry.record_panel(fn, tables=[...])        a box on record pages: fn(request, record, data) -> Panel | None
    registry.page('Title', 'name:url', icon, app='harness')   a link in an app's sidebar (or the top bar)
    registry.space_section(fn)                     a section on a space's overview: fn(request, space) -> Panel | None
    registry.space_nav(fn)                         links in a space's sidebar: fn(request, space) -> [(icon, title, url)]
    registry.home_section(key, label, fn)          a section on people's home page: fn(request) -> Panel | None
    registry.search(fn)                            more search results: fn(request, q) -> (heading, [(title, url, where)]) | None

Extensions find their tables by the template keys, e.g.
``registry.table('harness', 'devices')``, so they work with any app made from
their template, whatever the administrator renamed it to.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from django.apps import AppConfig
from django.conf import settings


@dataclass
class Panel:
    title: str
    html: str
    order: int = 100


@dataclass
class Page:
    title: str
    url_name: str
    icon: str = '◆'
    app: str = ''        # an app template key: shown in that app's sidebar; '' = the top bar
    extension: str = ''


@dataclass
class Extension:
    name: str
    title: str
    version: str
    description: str = ''
    icon: str = '◆'
    blueprints: list = field(default_factory=list)
    path: Path = None
    enabled: bool = True


class Registry:
    def __init__(self):
        self.panels = []       # (fn, tables)
        self.pages = []
        self.extensions = {}
        self.space_sections = []
        self.space_navs = []
        self.home_sections = {}   # key -> (label, fn)
        self.searches = []

    def view_type(self, cls):
        from .viewtypes import register
        register(cls)
        return cls

    def field_type(self, cls):
        from .fieldtypes import register
        register(cls)
        return cls

    def action(self, key, label, params=(), icon='◆', help='', source='extension'):
        from .automation import action
        return action(key, label, params, icon=icon, help=help, source=source)

    def record_panel(self, fn, tables=None):
        """``tables``: [(app template key, table key)], or None for every table."""
        self.panels.append((fn, tables))
        return fn

    def page(self, title, url_name, icon='◆', app='', extension=''):
        self.pages.append(Page(title, url_name, icon, app, extension))

    def space_section(self, fn):
        self.space_sections.append(fn)
        return fn

    def space_nav(self, fn):
        self.space_navs.append(fn)
        return fn

    def home_section(self, key, label, fn):
        self.home_sections[key] = (label, fn)
        return fn

    def search(self, fn):
        self.searches.append(fn)
        return fn

    def sections_for_space(self, request, space):
        out = [p for p in (fn(request, space) for fn in self.space_sections) if p is not None]
        return sorted(out, key=lambda p: p.order)

    def nav_for_space(self, request, space):
        return [item for fn in self.space_navs for item in (fn(request, space) or [])]

    # -- lookups for extensions ----------------------------------------------------

    def table(self, app_key, table_key):
        """The table made from template ``app_key``'s table ``table_key`` (or None)."""
        from .models import Table
        return Table.objects.select_related('app').filter(app__blueprint=app_key, key=table_key).order_by('pk').first()

    def panels_for(self, request, record, table, data):
        out = []
        for fn, tables in self.panels:
            if tables is not None and (table.app.blueprint, table.key) not in {tuple(t) for t in tables}:
                continue
            panel = fn(request, record, data)
            if panel is not None:
                out.append(panel)
        return sorted(out, key=lambda p: p.order)

    def pages_for_app(self, app):
        return [p for p in self.pages if p.app and p.app == app.blueprint]

    def topbar_pages(self):
        return [p for p in self.pages if not p.app]


registry = Registry()


def read_manifest(path):
    data = json.loads((path / 'extension.json').read_text('utf-8'))
    return Extension(name=data.get('name') or path.name, title=data.get('title') or path.name,
                     version=str(data.get('version', '1.0.0')), description=data.get('description', ''),
                     icon=data.get('icon', '◆'), blueprints=list(data.get('blueprints') or []), path=path)


def all_extensions():
    """Every extension in extensions/, enabled or not."""
    out = []
    for manifest in sorted(Path(settings.EXTENSIONS_DIR).glob('*/extension.json')):
        ext = read_manifest(manifest.parent)
        ext.enabled = ext.name in settings.OSMIA_EXTENSIONS
        out.append(ext)
    return out


def set_enabled(name, enabled):
    path = Path(settings.EXTENSIONS_STATE)
    try:
        state = json.loads(path.read_text('utf-8'))
    except (OSError, ValueError):
        state = {}
    disabled = set(state.get('disabled', []))
    (disabled.discard if enabled else disabled.add)(name)
    state['disabled'] = sorted(disabled)
    path.write_text(json.dumps(state, indent=2), 'utf-8')


class ExtensionConfig(AppConfig):
    """Base class for an extension's AppConfig: reads extension.json and calls
    ``extension.register(registry)`` when Django is ready."""
    default = False  # Django picks the extension's own subclass, not this base it imports
    default_auto_field = 'django.db.models.BigAutoField'

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.default = cls.__dict__.get('default', True)

    def ready(self):
        import importlib
        ext = read_manifest(Path(self.path))
        registry.extensions[ext.name] = ext
        module = importlib.import_module(f'{self.name}.extension')
        module.register(registry)
