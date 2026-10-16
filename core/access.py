"""Who may see which records: access tags.

People hold tags (``Tag.members``); records carry them. A record is seen by
someone only if they hold *every* tag it carries, or the record was shared with
them on its own (``AccessGrant``). A record without tags is seen by everyone
who may look at its app. Nothing ranks above a tag: administrators see a
tagged record only if they hold its tags too. What someone can't see is not
shown at all: not in views, links, counts, totals, search or pages.

The tags a record carries (``Record.access``) are its own (``Record.tags``)
and those of every record it inherits from, following

    - its parent, in a tree (``Table.tree_field``), and
    - its links to spaces (records of a table with ``is_space``), unless it is
      a space itself; a link field can say otherwise with ``options.access_from``.

So a task linked to a tagged project carries the project's tags, and so does
every sub-project under it. ``Record.access`` is kept up to date by
``refresh`` whenever tags or links change.
"""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AccessGrant, Field, Link, Record, Table, Tag, TagEvent

# -- What a person holds ----------------------------------------------------------------


def user_tags(user):
    """The ids of the tags ``user`` holds (remembered on the user object for the request)."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return frozenset()
    cached = getattr(user, '_osmia_tags', None)
    if cached is None:
        cached = frozenset(user.access_tags.values_list('pk', flat=True))
        user._osmia_tags = cached
    return cached


def user_grants(user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return frozenset()
    cached = getattr(user, '_osmia_grants', None)
    if cached is None:
        cached = frozenset(AccessGrant.objects.filter(user=user).values_list('record_id', flat=True))
        user._osmia_grants = cached
    return cached


def forget(user):
    """After a person's tags or grants change."""
    for name in ('_osmia_tags', '_osmia_grants'):
        if hasattr(user, name):
            delattr(user, name)


def allows(user, tag_ids, record_id=None):
    """Whether ``user`` may see something carrying ``tag_ids``."""
    if not tag_ids:
        return True
    if user is None:
        return False
    if set(tag_ids) <= user_tags(user):
        return True
    return record_id is not None and record_id in user_grants(user)


def can_see(user, record):
    return allows(user, record.access or [], record.pk)


def missing_tags(user, record):
    """The tags of ``record`` that ``user`` doesn't hold (for telling an assigner who can't see it)."""
    return [t for t in Tag.objects.filter(pk__in=record.access or []) if t.pk not in user_tags(user)]


# -- Inheriting tags -----------------------------------------------------------------------

class _Graph:
    """Which records inherit tags from which (worked out once per refresh)."""

    def __init__(self):
        self.tables = {t.pk: t for t in Table.objects.all()}
        self.edges = []   # (owner field id, backwards): a link field whose links carry tags along
        for f in Field.objects.filter(type='link'):
            if self.inherits(f):
                if f.opt('owner', True):
                    self.edges.append((f.pk, False))
                else:
                    self.edges.append((f.opt('inverse'), True))

    def inherits(self, field):
        table = self.tables.get(field.table_id)
        target = self.tables.get(field.opt('target'))
        if table is None or target is None:
            return False
        if table.tree_field_id == field.pk:
            return True
        explicit = field.opt('access_from')
        if explicit is not None:
            return bool(explicit)
        return target.is_space and not table.is_space

    def _pairs(self):
        if not hasattr(self, '_up'):
            up, down = defaultdict(set), defaultdict(set)   # up: record -> the records it inherits from
            for field_id, backwards in self.edges:
                for src, dst in Link.objects.filter(field_id=field_id).values_list('source_id', 'target_id'):
                    child, parent = (dst, src) if backwards else (src, dst)
                    if child != parent:
                        up[child].add(parent)
                        down[parent].add(child)
            self._up, self._down = up, down
        return self._up, self._down

    def sources(self, record_id):
        """Every record ``record_id`` inherits from, near or far."""
        up, _ = self._pairs()
        seen, todo = set(), [record_id]
        while todo:
            for parent in up.get(todo.pop(), ()):
                if parent not in seen and parent != record_id:
                    seen.add(parent)
                    todo.append(parent)
        return seen

    def heirs(self, record_ids):
        """``record_ids`` and every record that inherits from one of them."""
        _, down = self._pairs()
        seen, todo = set(record_ids), list(record_ids)
        while todo:
            for child in down.get(todo.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    todo.append(child)
        return seen


def refresh(record_ids):
    """Work out again the tags of ``record_ids`` and of everything that inherits from them."""
    record_ids = {int(r) for r in record_ids if r}
    if not record_ids:
        return set()
    graph = _Graph()
    affected = graph.heirs(record_ids)
    own = {pk: tags for pk, tags in Record.objects.filter(pk__in=affected | {s for r in affected for s in graph.sources(r)})
           .values_list('pk', 'tags')}
    changed = []
    for rec in Record.objects.filter(pk__in=affected).only('pk', 'tags', 'access'):
        tags = set(rec.tags or [])
        for s in graph.sources(rec.pk):
            tags.update(own.get(s) or [])
        new = sorted(tags)
        if new != sorted(rec.access or []):
            rec.access = new
            changed.append(rec)
    Record.objects.bulk_update(changed, ['access'])
    if changed:
        from .extensions import registry
        for fn in registry.access_listeners:
            fn({r.pk for r in changed})
    return {r.pk for r in changed}


def refresh_tables(table_ids):
    """After a table became (or stopped being) a tree or a space, or a field's access_from changed."""
    refresh(Record.objects.filter(table_id__in=table_ids).values_list('pk', flat=True))


def refresh_all():
    refresh(Record.objects.values_list('pk', flat=True))


# -- Putting tags on records ----------------------------------------------------------------

def set_tags(record, tag_ids, user):
    """Put exactly ``tag_ids`` on ``record`` as its own tags. ``user`` must hold every tag
    they add or remove: nobody hides a record from themselves, or opens up one they couldn't see."""
    tag_ids = sorted({int(t) for t in tag_ids})
    existing = set(Tag.objects.filter(pk__in=tag_ids).values_list('pk', flat=True))
    if len(existing) != len(tag_ids):
        raise ValidationError('One of those tags no longer exists.')
    old = set(record.tags or [])
    touched = old ^ set(tag_ids)
    if user is not None and not touched <= user_tags(user):
        names = ', '.join(Tag.objects.filter(pk__in=touched - user_tags(user)).values_list('name', flat=True))
        raise ValidationError(f'Only people who hold a tag can put it on a record or take it off ({names}).')
    with transaction.atomic():
        record.tags = tag_ids
        record.save(update_fields=['tags'])
        refresh([record.pk])
    record.refresh_from_db(fields=['tags', 'access'])
    return record


# -- Tags and the people who hold them ------------------------------------------------------

def _tell_owners(tag, message, by, url='/admin/tags/'):
    from .models import Notification
    Notification.objects.bulk_create(Notification(user=o, message=message[:500], url=url)
                                     for o in tag.owners.exclude(pk=getattr(by, 'pk', None)))


def is_owner(user, tag):
    return user is not None and tag.owners.filter(pk=user.pk).exists()


def create_tag(name, user, color='', description=''):
    name = (name or '').strip()
    if not name:
        raise ValidationError('Give the tag a name.')
    if Tag.objects.filter(name__iexact=name).exists():
        raise ValidationError(f'There is already a tag called {name}.')
    with transaction.atomic():
        tag = Tag.objects.create(name=name, color=color or '#b45309', description=description, created_by=user)
        tag.owners.add(user)
        tag.members.add(user)   # whoever makes a tag holds it, or they couldn't use it
        TagEvent.objects.create(tag=tag, action=TagEvent.Action.CREATED, user=user, by=user)
    forget(user)
    return tag


def _require_owner(user, tag):
    if not is_owner(user, tag):
        raise ValidationError(f'Only the owners of {tag.name} can do that.')


def grant(tag, person, by):
    _require_owner(by, tag)
    if not tag.members.filter(pk=person.pk).exists():
        tag.members.add(person)
        TagEvent.objects.create(tag=tag, action=TagEvent.Action.GRANTED, user=person, by=by)
        _tell_owners(tag, f'{by} gave the access tag {tag.name} to {person}.', by)
    forget(person)


def revoke(tag, person, by):
    _require_owner(by, tag)
    if tag.members.filter(pk=person.pk).exists():
        tag.members.remove(person)
        TagEvent.objects.create(tag=tag, action=TagEvent.Action.REVOKED, user=person, by=by)
        _tell_owners(tag, f'{by} took the access tag {tag.name} from {person}.', by)
    forget(person)


def add_owner(tag, person, by):
    _require_owner(by, tag)
    if not tag.owners.filter(pk=person.pk).exists():
        tag.owners.add(person)
        tag.members.add(person)
        TagEvent.objects.create(tag=tag, action=TagEvent.Action.OWNER_ADDED, user=person, by=by)
        _tell_owners(tag, f'{by} made {person} an owner of the access tag {tag.name}.', by)
    forget(person)


def remove_owner(tag, person, by):
    _require_owner(by, tag)
    if tag.owners.count() <= 1:
        raise ValidationError(f'{tag.name} needs at least one owner.')
    tag.owners.remove(person)
    TagEvent.objects.create(tag=tag, action=TagEvent.Action.OWNER_REMOVED, user=person, by=by)
    _tell_owners(tag, f'{by} removed {person} as an owner of the access tag {tag.name}.', by)


# -- Sharing one record ------------------------------------------------------------------------

def share(record, person, by):
    """Let ``person`` see this one record although they don't hold its tags
    (e.g. a task assigned to them). The tags' owners are told."""
    if allows(person, record.access or [], record.pk):
        return None
    grant_, created = AccessGrant.objects.get_or_create(record=record, user=person, defaults={'granted_by': by})
    if created:
        from .data import Data
        label = Data().label(record)
        for tag in Tag.objects.filter(pk__in=record.access or []):
            TagEvent.objects.create(tag=tag, action=TagEvent.Action.SHARED, user=person, by=by, record_id=record.pk,
                                    note=label[:300])
            _tell_owners(tag, f'{by} shared "{label}" ({tag.name}) with {person}, who doesn\'t hold {tag.name}.', by,
                         url=record.get_absolute_url())
    forget(person)
    return grant_


def end_grants(data, record):
    """Shares end when the record is closed, or when the person is no longer in one of its people fields."""
    from .space import is_closed
    grants = list(AccessGrant.objects.filter(record=record))
    if not grants:
        return
    if is_closed(data, record):
        AccessGrant.objects.filter(record=record).delete()
        return
    on_it = set()
    for f in data.fields(record.table_id):
        if f.type == 'user':
            value = data.value(record, f)
            on_it.update(getattr(value, 'ids', []) or [])
    AccessGrant.objects.filter(record=record).exclude(user_id__in=on_it).delete()


class NeedsSharing(ValidationError):
    """A people field names someone who couldn't see the record; ``people`` says who."""

    def __init__(self, message, people):
        super().__init__(message)
        self.people = people
