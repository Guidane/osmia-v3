"""The no-code workspace: everything an administrator builds is data here.

    App ─< Table ─< Field          the schema (made on the website, or from a template)
                 ─< Record          rows; stored field values live in ``Record.data``
                 ─< View            grid, tree, kanban, gallery, calendar, gantt, form, ...
                 ─< Automation      when <trigger>, if <conditions>, then <actions>
    Link                            a pair of linked records (link fields)
    Attachment, Comment, Change     files, discussion and the history of a record

``Record.data`` is keyed by ``Field.key`` (a slug that never changes when the
field is renamed). Computed fields (formula, lookup, rollup, ...) are not
stored; ``core.data`` works them out when they're read.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


def unique_slug(text, taken, fallback='item', max_length=50):
    base = slugify(text).replace('-', '_')[:max_length - 4] or fallback
    if base[0].isdigit():
        base = f'{fallback}_{base}'
    slug, n = base, 2
    while slug in taken:
        slug, n = f'{base}_{n}', n + 1
    return slug


class Space(models.Model):
    """A place for a team, department, project or person, like a Confluence or
    Jira space: what it's for, who's in it, its apps and pages.

    Apps live in one space (``App.space``) and can be added to others as
    shortcuts (``SpaceApp``); their tables link across spaces as usual.
    Everyone has a personal space (their home page).
    """

    class Kind(models.TextChoices):
        COMPANY = 'company', 'Company'
        DEPARTMENT = 'department', 'Department'
        TEAM = 'team', 'Team'
        PROJECT = 'project', 'Project'
        PERSONAL = 'personal', 'Personal'
        OTHER = 'other', 'Other'

    class Visibility(models.TextChoices):
        PRIVATE = 'private', 'Only members'
        INTERNAL = 'internal', 'Everyone who logs in can look'

    class Role(models.TextChoices):
        VIEWER = 'viewer', 'Can view'
        EDITOR = 'editor', 'Can edit records'
        ADMIN = 'admin', 'Space admin (builds apps, pages and the space)'

    name = models.CharField(max_length=100)
    key = models.CharField(max_length=20, unique=True, help_text='Short and unique, e.g. ENG. It is in the address.')
    icon = models.CharField(max_length=8, default='◼', blank=True)
    color = models.CharField(max_length=7, default='#2e7d5b')
    description = models.TextField(blank=True, help_text='What the space is for.')
    kind = models.CharField(max_length=12, choices=Kind, default=Kind.TEAM)
    visibility = models.CharField(max_length=10, choices=Visibility, default=Visibility.INTERNAL)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
                                 related_name='personal_space')  # personal spaces only
    config = models.JSONField(default=dict, blank=True)  # e.g. {"home": ["work", "todos", ...]} for a personal space
    position = models.IntegerField(default=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name

    @property
    def slug(self):
        return self.key.lower()

    @property
    def is_personal(self):
        return self.kind == self.Kind.PERSONAL

    def get_absolute_url(self):
        if self.is_personal:
            return reverse('core:home')
        return reverse('core:space', args=[self.slug])


class SpaceMember(models.Model):
    """A person or a team in a space, with their role there."""
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='space_memberships')
    group = models.ForeignKey('auth.Group', null=True, blank=True, on_delete=models.CASCADE, related_name='space_memberships')
    role = models.CharField(max_length=10, choices=Space.Role, default=Space.Role.EDITOR)

    class Meta:
        ordering = ['-role', 'id']


class App(models.Model):
    """A group of tables that belong together, e.g. "Orders" (orders and their lines)."""

    class Role(models.TextChoices):
        NONE = 'none', 'No access'
        VIEWER = 'viewer', 'Can view'
        EDITOR = 'editor', 'Can edit records'
        CREATOR = 'creator', 'Can change tables, views and automations'

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=60, unique=True)
    icon = models.CharField(max_length=8, default='▦', blank=True)
    color = models.CharField(max_length=7, default='#2e7d5b')
    description = models.TextField(blank=True)
    position = models.IntegerField(default=100)
    # What everyone logged in may do, unless AppAccess says more for them. Reading only,
    # unless an administrator explicitly lets everyone write.
    default_role = models.CharField(max_length=10, choices=Role, default=Role.VIEWER)
    # A person's own app (made from their home page): they build it; others can at most
    # look at it, unless an administrator gives them more. None: a workspace app.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='own_apps')
    # A person's "My space" (to-dos, pages, bookmarks): only its owner ever sees it, administrators included.
    is_space = models.BooleanField(default=False)  # the "My space" app (to-dos, bookmarks) of a personal space
    # The space the app lives in (other spaces can add it as a shortcut).
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.SET_NULL, related_name='apps')
    # The template it was made from (blueprints/<key>.json), so updates and extensions can find it.
    blueprint = models.CharField(max_length=60, blank=True, db_index=True)
    blueprint_version = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('core:app', args=[self.slug])


class AppAccess(models.Model):
    """What a person or a team may do in an app (more or less than the app's default)."""
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='access')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='app_access')
    group = models.ForeignKey('auth.Group', null=True, blank=True, on_delete=models.CASCADE, related_name='app_access')
    role = models.CharField(max_length=10, choices=App.Role, default=App.Role.EDITOR)

    def __str__(self):
        return f'{self.user or self.group} · {self.get_role_display()} in {self.app}'


class Table(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='tables')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=60)
    icon = models.CharField(max_length=8, blank=True)
    description = models.TextField(blank=True)
    position = models.IntegerField(default=0)
    # The field that names a record (in links, titles, ...). The first field if not set.
    display_field = models.ForeignKey('Field', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # The template's name for it (stable), e.g. "orders", so automations and extensions can find it.
    key = models.CharField(max_length=60, blank=True, db_index=True)

    class Meta:
        ordering = ['app__position', 'app__name', 'position', 'id']
        constraints = [models.UniqueConstraint(fields=['app', 'slug'], name='unique_table_slug')]

    def __str__(self):
        return self.name

    @property
    def label(self):
        return f'{self.app.name} › {self.name}'

    def get_absolute_url(self):
        return reverse('core:table', args=[self.app.slug, self.slug])

    def fields_in_order(self):
        return list(self.fields.all())

    def primary_field(self):
        return self.display_field or self.fields.first()


class Field(models.Model):
    """A column. ``type`` is a key of ``core.fieldtypes.TYPES``; ``options`` hold
    what that type needs, e.g. {"choices": [...]} for a select, or
    {"target": <table id>, "multiple": true, "inverse": <field id>} for a link."""
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField(max_length=100)
    key = models.CharField(max_length=60)
    type = models.CharField(max_length=30, default='text')
    options = models.JSONField(default=dict, blank=True)
    description = models.CharField(max_length=300, blank=True)
    required = models.BooleanField(default=False)
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['table', 'key'], name='unique_field_key')]

    def __str__(self):
        return self.name

    @property
    def kind(self):
        from .fieldtypes import get_type
        return get_type(self.type)

    @property
    def is_computed(self):
        return not self.kind.stored

    @property
    def editable(self):
        return self.kind.editable and not self.options.get('readonly')

    def opt(self, name, default=None):
        return (self.options or {}).get(name, default)


class Record(models.Model):
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='records')
    data = models.JSONField(default=dict, blank=True)
    position = models.FloatField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        from .data import Data
        return Data().label(self)

    def get_absolute_url(self):
        return reverse('core:record', args=[self.pk])


class Link(models.Model):
    """Two linked records. Stored once, for the link field that owns the
    relation (``options.owner``); its pair in the other table reads it backwards."""
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name='links')
    source = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='links_out')
    target = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='links_in')
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['field', 'source', 'target'], name='unique_link')]


class Sequence(models.Model):
    """The last number an autonumber field gave out."""
    field = models.OneToOneField(Field, on_delete=models.CASCADE, related_name='sequence')
    value = models.PositiveIntegerField(default=0)


class View(models.Model):
    """A way of looking at a table. ``type`` is a key of ``core.viewtypes``;
    ``config`` holds its settings: shown fields, filters, sorts, group by,
    the date fields of a calendar or gantt, the parent field of a tree, ..."""
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='views')
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=30, default='grid')
    config = models.JSONField(default=dict, blank=True)
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('core:view', args=[self.table.app.slug, self.table.slug, self.pk])


def attachment_path(instance, filename):
    return f'files/{instance.record.table_id}/{instance.record_id}/{filename}'


class Attachment(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='attachments')
    field = models.ForeignKey(Field, null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=attachment_path, max_length=300)
    name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    is_image = models.BooleanField(default=False)
    caption = models.CharField(max_length=300, blank=True)
    position = models.IntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('core:attachment', args=[self.pk])


class Comment(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class Change(models.Model):
    """One entry in a record's history: who did what, and each field's old → new value.
    Kept when the record is deleted (``record_id`` is not a foreign key)."""

    class Action(models.TextChoices):
        CREATE = 'create', 'Created'
        UPDATE = 'update', 'Changed'
        DELETE = 'delete', 'Deleted'
        COMMENT = 'comment', 'Commented'
        FILE = 'file', 'Files'
        BUTTON = 'button', 'Pressed'

    table = models.ForeignKey(Table, null=True, on_delete=models.CASCADE, related_name='changes')
    record_id = models.BigIntegerField(db_index=True)
    record_label = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=10, choices=Action)
    changes = models.JSONField(default=dict, blank=True)  # {field name: [old, new]} as text
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    source = models.CharField(max_length=200, blank=True)  # e.g. 'automation "Place order"'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Automation(models.Model):
    """When <trigger> happens to a record of ``table``, if <conditions> hold, run <actions>.

    trigger_config: depends on the trigger, e.g. {"fields": ["status"]} for "record updated"
    conditions:     {"match": "all"|"any", "rules": [{"field": key, "op": "is", "value": "Placed"}], "formula": ""}
    actions:        [{"type": "update_record", ...}, ...]  run in order; see core.automation
    """
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='automations')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    trigger = models.CharField(max_length=40)
    trigger_config = models.JSONField(default=dict, blank=True)
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list, blank=True)
    position = models.IntegerField(default=0)
    key = models.CharField(max_length=60, blank=True)  # the template's name for it
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('core:automation_edit', args=[self.table.app.slug, self.pk])


class AutomationState(models.Model):
    """For "when a condition becomes true": whether it held for a record last time."""
    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name='states')
    record_id = models.BigIntegerField()
    met = models.BooleanField(default=False)
    last_run = models.DateField(null=True, blank=True)  # for scheduled triggers: run once per day

    class Meta:
        constraints = [models.UniqueConstraint(fields=['automation', 'record_id'], name='unique_automation_state')]


class AutomationRun(models.Model):
    class Status(models.TextChoices):
        OK = 'ok', 'Done'
        SKIPPED = 'skipped', 'Conditions not met'
        FAILED = 'failed', 'Failed'

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name='runs')
    record_id = models.BigIntegerField(null=True)
    record_label = models.CharField(max_length=200, blank=True)
    trigger = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=Status)
    log = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=500)
    url = models.CharField(max_length=300, blank=True)
    automation = models.ForeignKey(Automation, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.message


class Star(models.Model):
    """A record someone starred, to find it again on their home page."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stars')
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='stars')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'record'], name='unique_star')]


class RecentView(models.Model):
    """When someone last opened a record (for "Recent" on their home page)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recent_views')
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='+')
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-viewed_at']
        constraints = [models.UniqueConstraint(fields=['user', 'record'], name='unique_recent_view')]


class SpaceApp(models.Model):
    """An app of another space, shown in this one (Confluence's "add a shortcut")."""
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='shortcuts')
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='shortcuts')
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['space', 'app'], name='unique_space_app')]


class SpaceLink(models.Model):
    """A record the space is about or uses, under a label: its department, its budget, its project, ..."""
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='links')
    label = models.CharField(max_length=60)
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name='space_links')
    position = models.IntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
