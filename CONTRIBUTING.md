# Contributing to RedScribe

Thanks for considering a contribution. A few things to know before you
start.

## Licensing of contributions

RedScribe is source-available under the [PolyForm Noncommercial License
1.0.0](LICENSE), paired with a separate [commercial license](COMMERCIAL-LICENSE.md)
— see the README's Licensing section for what that means. By submitting a
pull request, you agree your contribution is licensed under the same
terms as the rest of the project. There's no formal CLA/sign-off process
at this stage — that may be introduced before any contribution goes in,
so don't be surprised if a PR gets held for that conversation first.

## Getting a dev environment running

The fastest loop — no Docker rebuild cycle:

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db          # just the database
cp .env.example .env             # fill in secrets; POSTGRES_HOST=localhost
python manage.py migrate
python manage.py generate_root_key   # put the output in .env
python manage.py bootstrap_superadmin --username admin --email admin@example.com
python manage.py runserver
```

If you touch the Tiptap editor bundle, the password strength meter, or
Tailwind classes, rebuild the frontend assets per `BUILD.md` before
committing.

### Dev vs. prod settings

`.env.example` defaults to `DJANGO_SETTINGS_MODULE=config.settings.dev` —
no HTTPS-redirect behavior, works whether or not anything is terminating
TLS in front of it. `config.settings.prod` is for real deployment behind
a TLS-terminating reverse proxy: it sets `SECURE_PROXY_SSL_HEADER` to
trust `X-Forwarded-Proto: https` from that proxy, and hard-enforces
HTTPS/HSTS/secure cookies once that's set. Don't point `prod.py` at port
8000 directly without a proxy in front setting that header — it
force-redirects everything to HTTPS and you'll get a redirect loop.

### Testing OAuth locally

You don't need a live domain or TLS to test the OAuth scaffold end to
end. Google and Microsoft both carve out an exception to their "redirect
URI must be HTTPS" rule for the literal host `localhost` — not
`127.0.0.1`, not a LAN IP, not a Tailscale hostname — specifically for
local development.

1. Bring up `db` + `web` with `DJANGO_SETTINGS_MODULE=config.settings.dev`
   — `web` is published to `127.0.0.1:8000` for exactly this.
2. In the provider's console, add a *second* authorized redirect URI
   alongside your production one, over plain HTTP against `localhost`:
   - Google: `http://localhost:8000/accounts/social/google/login/callback/`
   - Microsoft: `http://localhost:8000/accounts/social/microsoft/login/callback/`

   Same client ID/secret works for both — it's an extra allowed redirect
   on the same OAuth client, not a separate app registration.
3. Set `OAUTH_PROVIDER`, `OAUTH_ALLOWED_DOMAIN`, and the client ID/secret
   in `.env`, then browse to `http://localhost:8000/accounts/login/` —
   exactly that host, so the scheme/host allauth builds the callback from
   matches what you registered.

This only works because there's no reverse proxy sitting between you and
`web` in this mode — `config.settings.dev` doesn't set
`SECURE_PROXY_SSL_HEADER` (see above), so if you instead put dev settings
behind a real TLS-terminating proxy, Django would still think the
connection is plain HTTP and build an `http://` callback that no longer
matches the `https://` URI you'd have to register for a real hostname,
producing a `redirect_uri_mismatch` (Google) or `AADSTS50011` (Microsoft)
error. Testing straight against `localhost:8000` sidesteps that entirely.

## Running the test suite

```
python manage.py test
```

The project has substantial existing test coverage (600+ tests as of this
writing) — a PR that changes behavior should come with tests covering it,
following the existing style in the relevant app's `tests.py`.

## Before opening a PR

- Run the full test suite locally before opening a PR — there's no CI
  running it automatically, so this is the only check.
- Add a `CHANGELOG.md` entry under `[Unreleased]` describing the change,
  following the existing Keep a Changelog format already used there.
- Keep the change scoped — this codebase favors small, well-reasoned
  diffs with docstrings explaining *why* a non-obvious decision was made,
  not sweeping refactors bundled with feature work.

## Cutting a release

Update `VERSION`, move `[Unreleased]` entries in `CHANGELOG.md` into a new
dated section, commit, then tag:

```
git tag -a v0.1.0-alpha.2 -m "v0.1.0-alpha.2"
git push origin v0.1.0-alpha.2
```

## Reporting bugs / requesting features

Use the issue templates — they ask for the information that's actually
useful for reproducing a problem in a self-hosted Django app (version,
install method, whether it reproduces on a clean instance).

## Reporting a security vulnerability

Do **not** open a public issue for a security vulnerability in RedScribe
itself — see [`.github/SECURITY.md`](.github/SECURITY.md) for the private
reporting process.
