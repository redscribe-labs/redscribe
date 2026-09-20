---
name: Bug report
about: Something isn't working the way it should
title: ""
labels: bug
assignees: ""
---

**RedScribe version**
e.g. `0.4.0-alpha.1` — check the sidebar footer of a running instance, or
`cat VERSION` in the repo.

**Install method**
- [ ] Method 1: Docker Compose + Tailscale
- [ ] Method 2: Docker Compose + your own TLS certificate
- [ ] Method 3: Docker Compose, plain HTTP
- [ ] Method 4: Local development without Docker

**Does it reproduce on a clean/demo-data instance?**
Fresh install with demo data loaded (`python manage.py load_demo_data` or
equivalent), no other customization — yes / no / haven't tried.

**What happened**
A clear description of the bug.

**What you expected**
What you expected to happen instead.

**Steps to reproduce**
1.
2.
3.

**Logs / screenshots**
Relevant Django/gunicorn/nginx log output or screenshots, if any. Please
redact anything from real client engagement data.

**Anything else?**
Browser, OS, anything else that seems relevant.
