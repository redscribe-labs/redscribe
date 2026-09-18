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
            self._mark_email_verified(sociallogin.user, email)
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
        self._mark_email_verified(target, email)
        target.oauth_invite_pending = False
        target.save(update_fields=["oauth_invite_pending"])

    def _mark_email_verified(self, user, email):
        # The identity provider already vouches for this address, and an admin already
        # vouched for it a second time by pre-approving it as an invite — allauth's own
        # separate email-ownership verification step is redundant on top of that, and
        # would otherwise send every OAuth user through its (unbranded) "verify your
        # email" flow indefinitely, since providers like Microsoft never report a
        # verified flag at all for allauth to trust instead. Idempotent and self-healing:
        # runs on every login, so an account left in a bad state by a past login (e.g.
        # before this method existed) is fixed on its very next one.
        from allauth.account.models import EmailAddress
        from django.db import transaction

        # Order matters: a user can have at most one primary=True row (DB-enforced,
        # "unique_primary_email"), so any other primary must be cleared *before*
        # inserting/promoting this one — doing it after, as a prior version of this
        # method did, throws IntegrityError whenever this user already had a
        # different primary address (e.g. a leftover row from before this method
        # existed, or one created some other way).
        with transaction.atomic():
            EmailAddress.objects.filter(user=user).exclude(email__iexact=email).update(primary=False)
            existing = EmailAddress.objects.filter(user=user, email__iexact=email).first()
            if existing:
                if not existing.verified or not existing.primary:
                    existing.verified = True
                    existing.primary = True
                    existing.save(update_fields=["verified", "primary"])
            else:
                EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)

    def is_open_for_signup(self, request, sociallogin):
        return False

    def save_user(self, request, sociallogin, form=None):
        # Unreachable in normal operation: is_open_for_signup() always returns False, so
        # allauth never calls this to create a brand-new User from an OAuth login. Kept
        # defensive rather than removed, in case some allauth internal path calls it directly.
        raise ImmediateHttpResponse(redirect("accounts:login"))
