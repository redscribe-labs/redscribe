from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Role

from .models import Client

User = get_user_model()


class ClientCreateForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name"]


class ClientEditForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "is_active"]


class ClientUserCreateForm(forms.ModelForm):
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_active=True),
        label="Client company",
        help_text="Which company this account can see engagements/findings for.",
    )

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "client"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.auth_type = User.AuthType.LOCAL
        user.role = Role.objects.get(slug="client")
        user.client = self.cleaned_data["client"]
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class ClientUserEditForm(forms.ModelForm):
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_active=True),
        label="Client company",
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "client"]
