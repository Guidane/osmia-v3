"""Who may do what, in spaces and their apps.

In an app:

    viewer   sees the app's records
    editor   also adds, changes and deletes records, presses buttons, comments
    creator  also changes the app's tables, fields, views and automations

In a space (``SpaceMember``): viewer, editor or admin. A space role gives the
same role in the space's apps (admin = creator), and space admins also run the
space: its members, its description, its links, its pages.

- A **private** space and its apps are seen by its members only; an **internal**
  space can be looked at by everyone who logs in.
- **Administrators** (superusers) can do everything everywhere, except look into
  people's private personal spaces.
- Everyone has a **personal space** (their home page). They build apps there; the
  space is private unless they make it internal, and even then each app is
  shown only if they share it ("Everyone can look at it"). Its to-do app is
  always theirs alone.
- An app can also give a person or a team another role (``AppAccess``), and a
  role for everyone (``App.default_role``); writing is never given to everyone
  unless an administrator says so.
- Making spaces needs the "Can make spaces" permission (or being an administrator).
"""
from django.core.exceptions import PermissionDenied, ValidationError

from .models import App, AppAccess, Space, SpaceMember

RANK = {'none': 0, 'viewer': 1, 'editor': 2, 'creator': 3}
SPACE_RANK = {'none': 0, 'viewer': 1, 'editor': 2, 'admin': 3}
SPACE_TO_APP = {'none': 'none', 'viewer': 'viewer', 'editor': 'editor', 'admin': 'creator'}


def _cache(user, name):
    cache = getattr(user, f'_osmia_{name}', None)
    if cache is None:
        cache = {}
        setattr(user, f'_osmia_{name}', cache)
    return cache


def membership(user, space):
    """The role ``user`` has as a member of ``space`` (directly or through a team), or None."""
    cache = _cache(user, 'memberships')
    if space.pk not in cache:
        rows = list(SpaceMember.objects.filter(space=space))
        mine = [r.role for r in rows if r.user_id == user.pk]
        if not mine:
            groups = set(user.groups.values_list('pk', flat=True))
            mine = [r.role for r in rows if r.group_id in groups]
        cache[space.pk] = max(mine, key=SPACE_RANK.get) if mine else None
    return cache[space.pk]


def space_role(user, space):
    """'none', 'viewer', 'editor' or 'admin'."""
    if space is None or user is None or not user.is_authenticated or not user.is_active:
        return 'none'
    if space.is_personal:
        if space.owner_id == user.pk:
            return 'admin'
        return 'viewer' if space.visibility == Space.Visibility.INTERNAL else 'none'
    if user.is_superuser:
        return 'admin'
    member = membership(user, space)
    if member:
        return member
    return 'viewer' if space.visibility == Space.Visibility.INTERNAL else 'none'


def can_space(user, space, needed):
    return SPACE_RANK[space_role(user, space)] >= SPACE_RANK[needed]


def require_space(user, space, needed):
    if not can_space(user, space, needed):
        if needed == 'viewer':
            raise PermissionDenied(f'You have no access to the space {space.name}.')
        raise PermissionDenied(f'Only admins of the space {space.name} can do that.')


def _app_access(user, app):
    rows = AppAccess.objects.filter(app=app)
    mine = [r.role for r in rows if r.user_id == user.pk]
    if not mine:
        groups = set(user.groups.values_list('pk', flat=True))
        mine = [r.role for r in rows if r.group_id in groups]
    return max(mine, key=RANK.get) if mine else None


def role(user, app):
    if user is None or not user.is_authenticated or not user.is_active:
        return 'none'
    cache = _cache(user, 'roles')
    if app.pk in cache:
        return cache[app.pk]
    space = app.space
    if space is not None and space.is_personal:
        if space.owner_id == user.pk or app.owner_id == user.pk:
            result = 'creator'
        elif app.is_space:
            result = 'none'  # someone's to-dos and bookmarks
        else:
            result = 'viewer' if app.default_role != App.Role.NONE else 'none'  # shared by its owner, or not
    elif user.is_superuser or (app.owner_id and app.owner_id == user.pk):
        result = 'creator'
    else:
        explicit = _app_access(user, app)
        if space is None:
            result = explicit or app.default_role
        else:
            member = membership(user, space)
            if member:
                base = max([SPACE_TO_APP[member], app.default_role], key=RANK.get)
            elif space.visibility == Space.Visibility.INTERNAL:
                base = app.default_role  # an internal space's apps: what the app gives everyone ("none" hides it)
            else:
                base = 'none'  # a private space hides its apps from non-members
            result = max([base, explicit or 'none'], key=RANK.get)
    cache[app.pk] = result
    return result


def can(user, app, needed):
    return RANK[role(user, app)] >= RANK[needed]


def require(user, app, needed):
    if not can(user, app, needed):
        if needed == 'viewer':
            raise PermissionDenied(f'You have no access to {app.name}.')
        raise PermissionDenied(f'You can look at {app.name} but not change it. An administrator or the space\'s admins can give you access.')


def visible_apps(user):
    return [a for a in App.objects.select_related('owner', 'space') if can(user, a, 'viewer')]


def visible_spaces(user):
    return [s for s in Space.objects.all() if can_space(user, s, 'viewer')]


def can_make_apps(user):
    return user.is_authenticated and user.is_active


def can_make_spaces(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.has_perm('core.add_space'))


def check_automation_write(auto_app, table):
    """An automation of a person's own app may only write to its own app, or to
    apps its owner may edit. (Other apps' automations are checked when saved.)"""
    if auto_app is None or table.app_id == auto_app.pk:
        return
    owner = auto_app.owner or (auto_app.space.owner if auto_app.space_id and auto_app.space.is_personal else None)
    if owner is None:
        return
    if not can(owner, table.app, 'editor'):
        raise ValidationError(f'An automation of {auto_app.name} can\'t change {table.app.name}: '
                              f'{owner} may only look at it.')
