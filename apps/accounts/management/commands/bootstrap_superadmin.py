import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Role

User = get_user_model()


class Command(BaseCommand):
    help = "Create the first local Superadmin account for a fresh RedScribe instance."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        if User.objects.filter(role__is_superadmin=True).exists():
            raise CommandError(
                "A Superadmin already exists. Grant the role to a new account "
                "from the admin UI as an existing Superadmin instead."
            )

        username = options["username"]
        email = options["email"]

        if User.objects.filter(username=username).exists():
            raise CommandError(f"Username {username!r} is already taken.")

        password = getpass.getpass("Password (14+ characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise CommandError("Passwords did not match.")

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("\n".join(exc.messages))

        user = User(
            username=username,
            email=email,
            role=Role.objects.get(is_superadmin=True),
            auth_type=User.AuthType.LOCAL,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Superadmin {username!r} created. They must complete TOTP "
                "enrollment on first login."
            )
        )
