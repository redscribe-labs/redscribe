#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main():
    # No-op under Docker/CI, where these vars are already set some other
    # way (Compose's env_file, CI secrets) -- load_dotenv() never
    # overrides an already-set variable, and there's no .env file inside
    # the container image to find anyway. This is what makes bare-metal
    # `python manage.py ...` runs pick up .env the same way Methods 1-3
    # do automatically via Compose.
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
