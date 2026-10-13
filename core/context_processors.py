from .extensions import registry
from .permissions import visible_apps


def osmia(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    from .models import Notification
    from .permissions import visible_spaces
    apps = visible_apps(user)
    spaces = visible_spaces(user)
    return {
        'sidebar_apps': apps,
        'launcher_personal': next((s for s in spaces if s.is_personal and s.owner_id == user.pk), None),
        'launcher_spaces': [s for s in spaces if not s.is_personal],
        'launcher_mine': [a for a in apps if a.space_id and a.space.is_personal and a.space.owner_id == user.pk and not a.is_space],
        'launcher_others': [a for a in apps if not (a.space_id and a.space.is_personal and a.space.owner_id == user.pk)],
        'unread_notifications': Notification.objects.filter(user=user, read=False).count(),
        'topbar_pages': registry.topbar_pages(),
    }
