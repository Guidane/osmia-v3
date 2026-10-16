"""Who may do what in an app. (Which records they see is core.access: access tags.)

    viewer   sees the app's records
    editor   also adds, changes and deletes records, presses buttons, comments
    creator  also changes the app's tables, fields, views, automations and home page

- **Administrators** (superusers) are creators of every app. They still see
  only the records whose access tags they hold.
- Everyone may make their **own apps**: they build them, and others see them
  only if the owner lets everyone look (``App.default_role`` viewer).
- An app gives everyone a role (``App.default_role``, viewer unless set) and a
  person or a team another one (``AppAccess``); writing is never given to
  everyone unless an administrator says so.
"""
from django.core.exceptions import PermissionDenied, ValidationError

from .models import App, AppAccess

RANK = {'none': 0, 'viewer': 1, 'editor': 2, 'creator': 3}


def _cache(user, name):
    cache = getattr(user, f'_osmia_{name}', None)
    if cache is None:
        cache = {}
        setattr(user, f'_osmia_{name}', cache)
    return cache


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
    if user.is_superuser or (app.owner_id and app.owner_id == user.pk):
        result = 'creator'
    elif app.owner_id:
        # someone else's own app: looking at most, if they share it, unless given more
        explicit = _app_access(user, app)
        shared = 'viewer' if app.default_role != App.Role.NONE else 'none'
        result = max([shared, explicit or 'none'], key=RANK.get)
    else:
        explicit = _app_access(user, app)
        result = max([app.default_role, explicit or 'none'], key=RANK.get)
    cache[app.pk] = result
    return result


def can(user, app, needed):
    return RANK[role(user, app)] >= RANK[needed]


def require(user, app, needed):
    if not can(user, app, needed):
        if needed == 'viewer':
            raise PermissionDenied(f'You have no access to {app.name}.')
        raise PermissionDenied(f'You can look at {app.name} but not change it. An administrator can give you access.')


def visible_apps(user):
    return [a for a in App.objects.select_related('owner') if can(user, a, 'viewer')]


def can_make_apps(user):
    return user.is_authenticated and user.is_active


def check_automation_write(auto_app, table):
    """An automation of a person's own app may only write to its own app, or to
    apps its owner may edit. (Other apps' automations are checked when saved.)"""
    if auto_app is None or table.app_id == auto_app.pk or auto_app.owner is None:
        return
    if not can(auto_app.owner, table.app, 'editor'):
        raise ValidationError(f'An automation of {auto_app.name} can\'t change {table.app.name}: '
                              f'{auto_app.owner} may only look at it.')
