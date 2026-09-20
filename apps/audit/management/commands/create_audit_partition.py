from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Create the yearly audit_auditlogentry partition for a given (default: next) year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year", type=int, default=None,
            help="Year to create a partition for (default: next calendar year).",
        )

    def handle(self, *args, **options):
        year = options["year"] or (timezone.now().year + 1)
        partition = f"audit_auditlogentry_{year}"

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {partition}
                PARTITION OF audit_auditlogentry
                FOR VALUES FROM (%s) TO (%s)
                """,
                [f"{year}-01-01", f"{year + 1}-01-01"],
            )

        self.stdout.write(self.style.SUCCESS(f"Partition {partition} ready ({year}-01-01 to {year + 1}-01-01)."))
