from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import redirect

from .models import Role


class SingleRoleAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False


class SingleProviderSocialAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        domain = settings.OAUTH_ALLOWED_DOMAIN
        if not domain:
            return
        email = (sociallogin.user.email or "").strip().lower()
        email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if email_domain != domain:
            from django.contrib import messages

            messages.error(
                request,
                "Sign-in is restricted to your organization's account. "
                "Please contact your administrator if you believe this is an error.",
            )
            raise ImmediateHttpResponse(redirect("accounts:login"))

    def is_open_for_signup(self, request, sociallogin):
        return bool(settings.OAUTH_PROVIDER) and sociallogin.account.provider == settings.OAUTH_PROVIDER

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        User = user.__class__
        user.auth_type = User.AuthType.OAUTH
        if not user.role_id:
            user.role = Role.objects.get(slug="consultant")
        user.save(update_fields=["auth_type", "role"])
        return user
