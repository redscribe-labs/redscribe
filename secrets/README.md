# Secrets

`docker-compose.yml` mounts three files from here as Docker secrets, read
only, inside whichever container needs them:

| File | Mounted at | Used by |
|---|---|---|
| `root_key.txt` | `/run/secrets/redscribe_root_key` | `web` |
| `django_secret_key.txt` | `/run/secrets/django_secret_key` | `web` |
| `postgres_password.txt` | `/run/secrets/postgres_password` | `web`, `db` |

Compose reads each straight from this plain file (no Swarm required for
file-based secrets). This is the same convention for all three: a mounted
file beats the equivalent env var wherever the app checks for one, because
an env var is readable via `docker inspect` or `/proc/<pid>/environ` by any
root/same-UID process on the host, while a file's access is controlled by
the mount itself. See `config/settings/base.py`'s `env_secret()` helper for
the general mechanism (`<NAME>_FILE` beats `<NAME>`), and
`apps/crypto/root_key.py` for the root key's own equivalent.

## Root encryption key (`root_key.txt`)

The instance's master key (`apps/crypto/root_key.py`) — every engagement's
per-project data key is wrapped with it. `RootKeyProvider` reads the
mounted file in preference to the `REDSCRIBE_ROOT_KEY` env var.

### First run

```
docker compose run --rm web python manage.py generate_root_key
```

Copy the printed value into `secrets/root_key.txt` (no trailing content
beyond the key itself — a trailing newline is fine and stripped) and
restart:

```
docker compose up -d
```

### Losing this file

Losing it makes every engagement's encrypted data permanently
unrecoverable — there is no recovery path. Back it up the same way you'd
back up any other master key (see the server-side encrypted backup
tooling for engagement data itself — this file is a separate, prerequisite
secret that backup does not cover).

## Django signing key (`django_secret_key.txt`)

Django's session/CSRF signing key (`DJANGO_SECRET_KEY`). Generate a random
50+ character value and put it in this file, e.g.:

```
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50)))" > secrets/django_secret_key.txt
```

## Database password (`postgres_password.txt`)

The `db`/`web` shared Postgres password. Put a password of your own
choosing in this file, e.g.:

```
openssl rand -base64 32 > secrets/postgres_password.txt
```

`db` picks it up via Postgres's own official `POSTGRES_PASSWORD_FILE`
convention; `web` picks up the same file via `env_secret()`.

## Everything else (OAuth client secrets, SMTP password, ...)

`env_secret()` applies the identical `<NAME>_FILE`-beats-`<NAME>` pattern
to every secret-shaped setting RedScribe reads — currently also
`GOOGLE_OAUTH_CLIENT_SECRET`, `MICROSOFT_OAUTH_CLIENT_SECRET`, and
`EMAIL_HOST_PASSWORD`. These are optional features (OAuth sign-in, SMTP),
so `docker-compose.yml` doesn't mount a Docker secret for them by default —
plain `.env` values still work. If you want file-based delivery for one of
these too, set e.g. `GOOGLE_OAUTH_CLIENT_SECRET_FILE=/run/secrets/google_oauth_client_secret`
in `.env` and add the matching `secrets:` entry (and mount) to your own
`docker-compose.override.yml`.

## For every secret above

`REDSCRIBE_ROOT_KEY`, `DJANGO_SECRET_KEY`, and `POSTGRES_PASSWORD` (the
plain env vars) remain a supported fallback for non-Docker/bare-metal
deployments and CI, where there's no Compose secret to mount.

Never commit any `secrets/*.txt` file — they're gitignored; this README
itself stays tracked.
