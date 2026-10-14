from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('<int:pk>/', views.run_view, name='run'),
    path('<int:pk>/check/', views.check, name='check'),
    path('<int:pk>/apply/', views.apply, name='apply'),
]
