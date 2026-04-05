# CLAUDE.md — DENT Project Rules

## Infrastructure Rules (MANDATORY)

- **Host nginx is the ONLY reverse proxy** — `/etc/nginx/sites-enabled/` on the server. NEVER create Docker nginx containers inside any project.
- **Never modify `docker-compose.server.yml` or nginx config** without showing the diff first and waiting for explicit user confirmation.
- **Never run `docker compose down` on production** — it destroys all containers including databases.
- **Always use `--no-deps --build` for deploys** — `docker compose up -d --build --no-deps <service>` for atomic container replacement with minimal downtime.
- **All services bind to `127.0.0.1`** — never expose ports to `0.0.0.0`. Host nginx handles external traffic.
- **Stop after each step and wait for explicit user confirmation** before proceeding to the next step. Never chain multiple infrastructure changes.

## DENT Port Map

- web: `127.0.0.1:3200` → container :3000
- api: `127.0.0.1:3201` → container :8080
- ml:  `127.0.0.1:3202` → container :8000
- minio: `127.0.0.1:3203` → container :9000
- postgres: internal only (no host port)

## Server Architecture

```
Cloudflare → Host Nginx (/etc/nginx) → 127.0.0.1:port → Docker containers
```

Each project on the server:
- Has its own `/etc/nginx/sites-enabled/<domain>.conf`
- Has its own docker-compose with `127.0.0.1:port` bindings
- Does NOT have its own nginx container

## Deploy

- CI: GitHub Actions → SSH → `git pull` → `docker compose up -d --build --no-deps`
- No nginx restart needed (host nginx, ports don't change)
- Health checks: API + ML must pass before deploy is considered successful

## Other Projects on Same Server (94.72.107.11)

- DAM: ports 3100-3104
- ShiftOneZero: ports 3300-3301
- Aura: port 8080
- Dinamo: ports 8001, 3001
