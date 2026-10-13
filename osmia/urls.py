from django.conf import settings
from django.urls import include, path

urlpatterns = [
    path('accounts/', include('accounts.urls')),
]

# Each extension's urls.py, at /x/<name>/ (namespace <name>).
for _name in settings.OSMIA_EXTENSIONS:
    try:
        urlpatterns.append(path(f'x/{_name}/', include((f'extensions.{_name}.urls', _name), namespace=_name)))
    except ModuleNotFoundError:
        pass

urlpatterns.append(path('', include('core.urls')))
