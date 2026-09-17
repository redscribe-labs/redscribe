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

The fastest loop is **Method 4** in the README (local development, no
Docker rebuild cycle) — see the "Method 4: Local development without
Docker" section of `README.md` for the exact setup.

If you touch the Tiptap editor bundle, the password strength meter, or
Tailwind classes, rebuild the frontend assets per `BUILD.md` before
committing — see the README's "Development" section for the dev-vs-prod
settings split and other operational notes.

## Running the test suite

```
python manage.py test
```

The project has substantial existing test coverage (600+ tests as of this
writing) — a PR that changes behavior should come with tests covering it,
following the existing style in the relevant app's `tests.py`.

## Before opening a PR

- Run the full test suite locally; CI (`.github/workflows/test.yml`) runs
  it again on every PR, but catching failures locally first is faster for
  everyone.
- Add a `CHANGELOG.md` entry under `[Unreleased]` describing the change,
  following the existing Keep a Changelog format already used there.
- Keep the change scoped — this codebase favors small, well-reasoned
  diffs with docstrings explaining *why* a non-obvious decision was made,
  not sweeping refactors bundled with feature work.

## Reporting bugs / requesting features

Use the issue templates — they ask for the information that's actually
useful for reproducing a problem in a self-hosted Django app (version,
install method, whether it reproduces on a clean instance).

## Reporting a security vulnerability

Do **not** open a public issue for a security vulnerability in RedScribe
itself — see [`.github/SECURITY.md`](.github/SECURITY.md) for the private
reporting process.
