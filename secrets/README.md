# Root encryption key

`docker-compose.yml` mounts one file from here as a Docker secret:

```
secrets/root_key.txt
```

This is the instance's master key (`apps/crypto/root_key.py`) — every
engagement's per-project data key is wrapped with it. Compose reads it from
this plain file (no Swarm required for file-based secrets) and mounts it
read-only inside the `web` container at `/run/secrets/redscribe_root_key`,
where `RootKeyProvider` reads it in preference to the `REDSCRIBE_ROOT_KEY`
env var. That preference is deliberate: an env var is readable via
`docker inspect` or `/proc/<pid>/environ` by any root/same-UID process on
the host, while this file's access is controlled by the mount itself.

## First run

```
docker compose run --rm web python manage.py generate_root_key
```

Copy the printed value into `secrets/root_key.txt` (no trailing content
beyond the key itself — a trailing newline is fine and stripped) and
restart:

```
docker compose up -d
```

## Losing this file

Losing it makes every engagement's encrypted data permanently
unrecoverable — there is no recovery path. Back it up the same way you'd
back up any other master key (see the server-side encrypted backup
tooling for engagement data itself — this file is a separate, prerequisite
secret that backup does not cover).

`REDSCRIBE_ROOT_KEY` (the env var) remains a supported fallback for
non-Docker/bare-metal deployments and CI, where there's no Compose secret
to mount.

Never commit `root_key.txt` — it's gitignored (`secrets/*.txt`); this
README itself stays tracked.
