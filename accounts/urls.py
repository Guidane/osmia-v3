from django.contrib.auth import views as auth
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', auth.LoginView.as_view(template_name='accounts/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('password/', auth.PasswordChangeView.as_view(
        template_name='accounts/password_change.html', success_url=reverse_lazy('accounts:password_changed')), name='password_change'),
    path('password/changed/', auth.PasswordChangeDoneView.as_view(template_name='accounts/password_changed.html'),
         name='password_changed'),
    path('reset/', auth.PasswordResetView.as_view(
        template_name='accounts/reset.html', email_template_name='accounts/reset_email.txt',
        subject_template_name='accounts/reset_subject.txt', success_url=reverse_lazy('accounts:reset_sent')), name='reset'),
    path('reset/sent/', auth.PasswordResetDoneView.as_view(template_name='accounts/reset_sent.html'), name='reset_sent'),
    path('reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(
        template_name='accounts/reset_confirm.html', success_url=reverse_lazy('accounts:reset_done')), name='reset_confirm'),
    path('reset/done/', auth.PasswordResetCompleteView.as_view(template_name='accounts/reset_done.html'), name='reset_done'),
    path('users/', views.user_list, name='user_list'),
    path('users/new/', views.user_create, name='user_create'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/password/', views.user_password, name='user_password'),
    path('teams/', views.team_list, name='team_list'),
    path('teams/new/', views.team_edit, name='team_create'),
    path('teams/<int:pk>/', views.team_edit, name='team_edit'),
]
