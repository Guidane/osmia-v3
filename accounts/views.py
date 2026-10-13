from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import NewUserForm, ProfileForm, SetPasswordForm, TeamForm, UserAdminForm
from .models import User

admin_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile is saved.')
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html', {'form': form})


@admin_required
def user_list(request):
    q = request.GET.get('q', '').strip()
    users = User.objects.prefetch_related('groups')
    if q:
        users = users.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                             | Q(email__icontains=q) | Q(job_title__icontains=q))
    return render(request, 'accounts/user_list.html', {'users': users, 'q': q})


@admin_required
def user_detail(request, pk):
    person = get_object_or_404(User, pk=pk)
    return render(request, 'accounts/user_detail.html', {'person': person})


@admin_required
def user_create(request):
    form = NewUserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        person = form.save()
        messages.success(request, f'{person} can now log in.')
        return redirect(person)
    return render(request, 'accounts/form.html', {'form': form, 'title': 'New user'})


@admin_required
def user_edit(request, pk):
    person = get_object_or_404(User, pk=pk)
    form = UserAdminForm(request.POST or None, instance=person)
    if request.method == 'POST' and form.is_valid():
        if person == request.user and not form.cleaned_data['is_superuser']:
            form.add_error('is_superuser', 'You cannot take away your own administrator rights.')
        elif person == request.user and not form.cleaned_data['is_active']:
            form.add_error('is_active', 'You cannot lock yourself out.')
        else:
            form.save()
            messages.success(request, f'{person} is saved.')
            return redirect(person)
    return render(request, 'accounts/form.html', {'form': form, 'title': f'Edit {person}', 'cancel': person.get_absolute_url()})


@admin_required
def user_password(request, pk):
    person = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(person, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        if person == request.user:
            update_session_auth_hash(request, person)
        messages.success(request, f'The password of {person} is changed.')
        return redirect(person)
    return render(request, 'accounts/form.html', {'form': form, 'title': f'Set the password of {person}',
                                                  'cancel': person.get_absolute_url()})


@admin_required
def team_list(request):
    return render(request, 'accounts/team_list.html', {'teams': Group.objects.prefetch_related('user_set').order_by('name')})


@admin_required
def team_edit(request, pk=None):
    team = get_object_or_404(Group, pk=pk) if pk else None
    form = TeamForm(request.POST or None, instance=team)
    if request.method == 'POST':
        if 'delete' in request.POST and team:
            team.delete()
            messages.success(request, f'The team {team.name} is deleted.')
            return redirect('accounts:team_list')
        if form.is_valid():
            team = form.save()
            messages.success(request, f'The team {team.name} is saved.')
            return redirect('accounts:team_list')
    return render(request, 'accounts/team_form.html', {'form': form, 'team': team})
