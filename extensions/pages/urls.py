from django.urls import path

from . import views

urlpatterns = [
    path('s/<str:space_key>/', views.space_pages, name='space'),
    path('s/<str:space_key>/new/', views.page_new, name='new'),
    path('s/<str:space_key>/upload/', views.upload, name='upload'),
    path('records/', views.records_for_link, name='records'),
    path('records/<int:pk>/', views.record_for_link, name='record'),
    path('calc/', views.calc_preview, name='calc'),
    path('files/<int:pk>/', views.page_file, name='file'),
    path('<int:pk>/', views.page_view, name='page'),
    path('<int:pk>/edit/', views.page_edit, name='edit'),
    path('<int:pk>/delete/', views.page_delete, name='delete'),
    path('<int:pk>/move/', views.page_move, name='move'),
    path('<int:pk>/comment/', views.page_comment, name='comment'),
    path('<int:pk>/pin/', views.page_pin, name='pin'),
    path('<int:pk>/restore/<int:version>/', views.page_restore, name='restore'),
]
