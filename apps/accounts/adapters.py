from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import redirect


class SingleRoleAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False


class SingleProviderSocialAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        from django.contrib import messages

        domain = settings.OAUTH_ALLOWED_DOMAIN
        email = (sociallogin.user.email or "").strip().lower()
        email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain and email_domain != domain:
            messages.error(
                request,
                "Sign-in is restricted to your organization's account. "
                "Please contact your administrator if you believe this is an error.",
            )
            raise ImmediateHttpResponse(redirect("accounts:login"))

        if sociallogin.is_existing:
            return

        User = sociallogin.user.__class__
        target = User.objects.filter(
            email__iexact=email,
            auth_type=User.AuthType.OAUTH,
            oauth_invite_pending=True,
            is_active=True,
        ).first()
        if target is None:
            return

        if target.role.is_superadmin:
            messages.error(
                request,
                "Sign-in is restricted to your organization's account. "
                "Please contact your administrator if you believe this is an error.",
            )
            raise ImmediateHttpResponse(redirect("accounts:login"))

        sociallogin.connect(request, target)
        target.oauth_invite_pending = False
        target.save(update_fields=["oauth_invite_pending"])

    def is_open_for_signup(self, request, sociallogin):
        return False

    def save_user(self, request, sociallogin, form=None):
        # Unreachable in normal operation: is_open_for_signup() always returns False, so
        # allauth never calls this to create a brand-new User from an OAuth login. Kept
        # defensive rather than removed, in case some allauth internal path calls it directly.
        raise ImmediateHttpResponse(redirect("accounts:login"))
