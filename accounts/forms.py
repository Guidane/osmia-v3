from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group

from .models import User


def space_permission():
    from django.contrib.auth.models import Permission
    return Permission.objects.filter(codename='add_space', content_type__app_label='core').first()


class CanMakeSpaces(forms.Form):
    """Adds "Can make spaces" to a user or team form."""
    can_make_spaces = forms.BooleanField(required=False, label='Can make spaces',
                                         help_text='Make spaces for departments, teams and projects, and run them.')

    def init_spaces(self, holder):
        perm = space_permission()
        if holder is not None and holder.pk and perm is not None:
            perms = holder.user_permissions if isinstance(holder, User) else holder.permissions
            self.fields['can_make_spaces'].initial = perms.filter(pk=perm.pk).exists()

    def save_spaces(self, holder):
        perm = space_permission()
        if perm is None:
            return
        perms = holder.user_permissions if isinstance(holder, User) else holder.permissions
        (perms.add if self.cleaned_data.get('can_make_spaces') else perms.remove)(perm)


class ProfileForm(forms.ModelForm):
    """What people can change about themselves."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'job_title', 'phone']


class UserAdminForm(forms.ModelForm):
    """What an administrator can change about anyone."""
    groups = forms.ModelMultipleChoiceField(Group.objects.all(), required=False, label='Teams',
                                            widget=forms.CheckboxSelectMultiple)
    can_make_spaces = CanMakeSpaces.base_fields['can_make_spaces']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        CanMakeSpaces.init_spaces(self, self.instance)

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            CanMakeSpaces.save_spaces(self, user)
        return user

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'job_title', 'phone', 'is_active', 'is_superuser', 'groups']
        labels = {'is_superuser': 'Administrator', 'is_active': 'Can log in'}
        help_texts = {'is_superuser': 'Administrators manage users, apps, templates and extensions, and see every app.'}


class NewUserForm(UserCreationForm):
    groups = forms.ModelMultipleChoiceField(Group.objects.all(), required=False, label='Teams',
                                            widget=forms.CheckboxSelectMultiple)
    can_make_spaces = CanMakeSpaces.base_fields['can_make_spaces']

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'job_title', 'phone', 'is_superuser', 'groups']
        labels = {'is_superuser': 'Administrator'}

    def save(self, commit=True):
        user = super().save(commit)
        if commit:
            user.groups.set(self.cleaned_data['groups'])
            CanMakeSpaces.save_spaces(self, user)
        return user


class SetPasswordForm(forms.Form):
    """An administrator sets someone's password (Django's validators apply)."""
    password1 = forms.CharField(label='New password', widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label='Repeat it', widget=forms.PasswordInput, strip=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('The two passwords are not the same.')
        if p1:
            password_validation.validate_password(p1, self.user)
        return data

    def save(self):
        self.user.set_password(self.cleaned_data['password1'])
        self.user.save(update_fields=['password'])
        return self.user


class TeamForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(User.objects.filter(is_active=True), required=False,
                                             widget=forms.CheckboxSelectMultiple)
    can_make_spaces = CanMakeSpaces.base_fields['can_make_spaces']

    class Meta:
        model = Group
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['members'].initial = self.instance.user_set.all()
        CanMakeSpaces.init_spaces(self, self.instance)

    def save(self, commit=True):
        team = super().save(commit)
        team.user_set.set(self.cleaned_data['members'])
        CanMakeSpaces.save_spaces(self, team)
        return team
