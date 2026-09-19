import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.integrity import append_with_chain

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Reset a local account's password and, optionally, clear its TOTP device, for when the "
        "normal in-app tools aren't usable (e.g. the only Superadmin is themselves locked out). "
        "Unlike a raw `manage.py shell`/`changepassword` session, this writes an entry to "
        "RedScribe's own tamper-evident audit log, so the one access path that bypasses every "
        "other control doesn't also bypass the record of it happening."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="The account to recover.")
        parser.add_argument(
            "--reason", required=True,
            help="Why this is being run. Recorded in the audit log verbatim (e.g. an incident/ticket reference).",
        )
        parser.add_argument(
            "--clear-mfa", action="store_true",
            help="Also delete the account's confirmed TOTP device, forcing re-enrollment at next login.",
        )
        parser.add_argument(
            "--operator", default=None,
            help="Who is running this, recorded in the audit log. Defaults to the current OS user.",
        )

    def handle(self, *args, **options):
        username = options["username"]
        reason = options["reason"].strip()
        if not reason:
            raise CommandError(
                "--reason cannot be blank — it's what the audit log records for why normal "
                "account recovery wasn't used."
            )

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No account with username {username!r}.")

        if user.auth_type != User.AuthType.LOCAL:
            raise CommandError(
                f"{username!r} is an OAuth account, not local — there's no RedScribe-managed "
                "password to reset. Use 'Convert to local account' from that account's detail "
                "page instead."
            )

        password = getpass.getpass("New password (14+ characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise CommandError("Passwords did not match.")
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError("\n".join(exc.messages))

        operator = options["operator"] or getpass.getuser()

        user.set_password(password)
        user.save(update_fields=["password"])

        cleared_mfa = False
        if options["clear_mfa"]:
            deleted, _ = TOTPDevice.objects.filter(user=user).delete()
            cleared_mfa = deleted > 0

        actions = ["password reset"] + (["MFA cleared"] if cleared_mfa else [])
        append_with_chain(
            actor=None,
            actor_username=operator,
            actor_role="",
            action="emergency_account_recovery",
            method="CLI",
            path="cli:emergency_account_recovery",
            status_code=200,
            object_ref=f"{username}: {', '.join(actions)} — {reason}"[:255],
        )

        self.stdout.write(self.style.SUCCESS(
            f"Done: {', '.join(actions)} for {username!r}. Recorded in the audit log "
            f"(operator {operator!r})."
        ))
