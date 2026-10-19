def osmia(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    from .data import Data
    from .models import Notification
    from .space import app_groups, space_tables
    from .trees import Tree
    data = Data(user)
    spaces = []
    for table in space_tables():
        for root in Tree(data, table).roots():
            spaces.append((root, data.label(root)))
    return {
        'launcher_groups': app_groups(request),
        'launcher_spaces': spaces[:20],
        'unread_notifications': Notification.objects.filter(user=user, read=False).count(),
        'owns_tags': user.owned_tags.exists(),
    }
