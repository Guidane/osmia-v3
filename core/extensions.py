"""Extensions: code that adds what tables, fields and automations can't.

An app (tables, fields, views, automations) is made on the website, and its
screens are built from the same parts as every app's: tabs, views and a home
page made of blocks. An **extension app** is made in code and has its own
fixed screens, e.g. the harness designer's drawing canvas. It lives in
``extensions/<name>/``:

    extension.json     {"name", "title", "version", "description", "icon",
                        "blueprints": ["harness"],                          app templates it brings
                        "requires": ["parts", "parts.parts.manufacturer"],  what must be there
                        "optional": ["stock"]}                              what it works with if it's there
    apps.py            class Config(ExtensionConfig): name = 'extensions.<name>'
    extension.py       def register(registry): ...
    urls.py            (optional) mounted at /x/<name>/, namespace <name>
    blueprints/*.json  (optional) app templates the extension works with

A requirement names a template (``parts``), one of its tables
(``parts.parts``) or a field of that table (``parts.parts.manufacturer``), by
the template's keys, so renaming never breaks it. Switching an extension on
lists what is missing and offers to install it; while it is on, nothing it
requires can be removed (core.dependencies). Switching it off removes only its
code: everything it stored stays, as ordinary apps and fields.

An extension reads and writes records only through core.data and
core.service, so access tags, validation, history and automations apply.
``register`` can add:

    registry.app('Title', 'name:url', icon, description, group='Workspace')    a card in the launcher: the extension app itself
    registry.block('key', 'Label', fn, icon, where, help)    a block for pages' slash menu: fn(request, context) -> html
    registry.page('Title', 'name:url', icon, app='harness')  a tab of the apps made from that template
    registry.view_type(MyViewType)                 a new kind of view (see core.viewtypes.ViewType)
    registry.field_type(MyFieldType)               a new kind of field (see core.fieldtypes.FieldType)
    registry.action('key', 'Label', params)(fn)    a new automation action (see core.automation)
    registry.record_panel(fn, tables=[...])        a box on record pages: fn(request, record, data) -> Panel | None
    registry.search(fn)                            more search results: fn(request, q) -> (heading, [(title, url, where)]) | None
    registry.on_access_change(fn)                  fn(record ids) after records' access tags changed
    registry.dependency_check(fn)                  fn(removal, gone fields) -> [what would break]
    registry.page_source(fn)                       fn() -> [(where, html)]: pages it keeps (for the blocks on them)

Switching an extension off is refused while something uses what it brings (a
view of its view type, a field of its field type, an automation step of its
action, its block on a page): see ``in_use``.

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
    app: str = ''        # an app template key: a tab of the apps made from it
    extension: str = ''


@dataclass
class ExtensionApp:
    title: str
    url_name: str
    icon: str = '◆'
    description: str = ''
    color: str = '#475569'
    extension: str = ''
    visible: object = None   # fn(request) -> bool, or None: everyone
    group: str = ''          # shown under it in the launcher and on home pages, like an App's

    @property
    def url(self):
        from django.urls import reverse
        return reverse(self.url_name)

    # the same names as an App's, so one card shows both
    @property
    def name(self):
        return self.title

    @property
    def slug(self):
        """How a page names its card (data-app), next to the apps' slugs."""
        return 'x-ext-' + self.url_name.replace(':', '-').replace('_', '-')

    def get_absolute_url(self):
        return self.url


@dataclass
class Block:
    key: str
    label: str
    fn: object
    icon: str = '◆'
    where: str = 'any'   # 'any', 'space' (a space's page) or 'app' (an app's home)
    help: str = ''


@dataclass
class Extension:
    name: str
    title: str
    version: str
    description: str = ''
    icon: str = '◆'
    blueprints: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    optional: list = field(default_factory=list)
    path: Path = None
    enabled: bool = True


def requirement_parts(req):
    """'parts' / 'parts.parts' / 'parts.parts.manufacturer' -> (template, table or '', field or '')."""
    parts = (str(req).split('.') + ['', ''])[:3]
    return parts[0], parts[1], parts[2]


class Registry:
    def __init__(self):
        self.panels = []       # (fn, tables)
        self.pages = []
        self.apps = []
        self.blocks = {}
        self.extensions = {}
        self.searches = []
        self.access_listeners = []
        self.dependency_checks = []
        self.page_sources = []   # fn() -> [(where, body)]: pages extensions keep, for finding the blocks on them
        self.provided = {}     # extension name -> {'view_types': [...], 'field_types': [...], 'actions': [...], 'blocks': [...]}
        self._current = None   # the extension whose register() is running

    def _provides(self, kind, key):
        if self._current:
            self.provided.setdefault(self._current, {}).setdefault(kind, []).append(key)

    def view_type(self, cls):
        from .viewtypes import register
        register(cls)
        self._provides('view_types', cls.key)
        return cls

    def field_type(self, cls):
        from .fieldtypes import register
        register(cls)
        self._provides('field_types', cls.key)
        return cls

    def action(self, key, label, params=(), icon='◆', help='', source='extension'):
        from .automation import action
        self._provides('actions', key)
        return action(key, label, params, icon=icon, help=help, source=source)

    def record_panel(self, fn, tables=None):
        """``tables``: [(app template key, table key)], or None for every table."""
        self.panels.append((fn, tables))
        return fn

    def page(self, title, url_name, icon='◆', app='', extension=''):
        self.pages.append(Page(title, url_name, icon, app, extension))

    def app(self, title, url_name, icon='◆', description='', color='#475569', extension='', visible=None, group=''):
        self.apps.append(ExtensionApp(title, url_name, icon, description, color, extension, visible, group))

    def block(self, key, label, fn, icon='◆', where='any', help=''):
        self.blocks[key] = Block(key, label, fn, icon, where, help)
        self._provides('blocks', key)
        return fn

    def search(self, fn):
        self.searches.append(fn)
        return fn

    def on_access_change(self, fn):
        self.access_listeners.append(fn)
        return fn

    def dependency_check(self, fn):
        self.dependency_checks.append(fn)
        return fn

    def page_source(self, fn):
        self.page_sources.append(fn)
        return fn

    def apps_for(self, request):
        return [a for a in self.apps if a.visible is None or a.visible(request)]

    def blocks_for(self, where):
        return [b for b in self.blocks.values() if b.where in ('any', where)]

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


registry = Registry()


def read_manifest(path):
    data = json.loads((path / 'extension.json').read_text('utf-8'))
    return Extension(name=data.get('name') or path.name, title=data.get('title') or path.name,
                     version=str(data.get('version', '1.0.0')), description=data.get('description', ''),
                     icon=data.get('icon', '◆'), blueprints=list(data.get('blueprints') or []),
                     requires=list(data.get('requires') or []), optional=list(data.get('optional') or []), path=path)


def all_extensions():
    """Every extension in extensions/, enabled or not."""
    out = []
    for manifest in sorted(Path(settings.EXTENSIONS_DIR).glob('*/extension.json')):
        ext = read_manifest(manifest.parent)
        ext.enabled = ext.name in settings.OSMIA_EXTENSIONS
        out.append(ext)
    return out


def extension_blueprints(ext):
    """{key: template} of the templates an extension brings (read from its folder, on or off)."""
    out = {}
    folder = ext.path / 'blueprints' if ext.path else None
    if folder and folder.is_dir():
        for p in sorted(folder.glob('*.json')):
            try:
                bp = json.loads(p.read_text('utf-8'))
            except ValueError:
                continue
            bp['_path'] = str(p)
            bp.setdefault('key', p.stem)
            out[bp['key']] = bp
    return out


def missing(ext):
    """What ``ext`` requires that isn't there: [(requirement, why, template key that would bring it, or '')]."""
    from . import blueprints
    from .models import Field, Table
    catalog = {**blueprints.available(include_hidden=True), **extension_blueprints(ext)}
    installed = blueprints.installed_keys()
    out = []
    for req in ext.requires:
        app_k, table_k, field_k = requirement_parts(req)
        if app_k not in installed:
            name = (catalog.get(app_k) or {}).get('name', app_k)
            out.append((req, f'the app {name} is not installed', app_k if app_k in catalog else ''))
            continue
        if not table_k:
            continue
        table = Table.objects.select_related('app').filter(app__blueprint=app_k, key=table_k).first()
        if table is None:
            out.append((req, f'there is no table "{table_k}" in the app made from {app_k}', ''))
        elif field_k and not Field.objects.filter(table=table, key=field_k).exists():
            out.append((req, f'{table.label} has no field "{field_k}"', ''))
    return out


def to_install(ext):
    """Templates switching ``ext`` on installs: the missing ones it requires, then its own."""
    from . import blueprints
    installed = blueprints.installed_keys()
    keys = [key for _, _, key in missing(ext) if key]
    return keys + [k for k in ext.blueprints if k not in installed and k not in keys]


def in_use(name):
    """What uses the code of the (switched on) extension ``name``: switching it off would break these."""
    import re

    from .models import Automation, Field, Layout, View
    provided = registry.provided.get(name) or {}
    out = []
    for v in View.objects.filter(type__in=provided.get('view_types') or []).select_related('table__app'):
        out.append(f'The view {v.name} of {v.table.label} is a {v.type.replace("_", " ")} view.')
    for f in Field.objects.filter(type__in=provided.get('field_types') or []).select_related('table__app'):
        out.append(f'The field {f.name} of {f.table.label} is of a type it brings.')
    actions = set(provided.get('actions') or [])
    if actions:
        for a in Automation.objects.select_related('table__app'):
            if any(step.get('type') in actions for step in a.actions or []):
                out.append(f'The automation "{a.name}" of {a.table.app.name} uses an action it brings.')
    blocks = set(provided.get('blocks') or [])
    if blocks:
        used = re.compile(r'data-block="(' + '|'.join(re.escape(b) for b in blocks) + r')"')
        from .canvas.references import where as page_name
        for layout in Layout.objects.select_related('app', 'record', 'user'):
            if used.search(layout.body or ''):
                out.append(f'A block it brings is on {page_name(layout)}.')
        for source in registry.page_sources:
            for where, body in source():
                if used.search(body or ''):
                    out.append(f'A block it brings is on {where}.')
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
        registry._current = ext.name
        try:
            module.register(registry)
        finally:
            registry._current = None
