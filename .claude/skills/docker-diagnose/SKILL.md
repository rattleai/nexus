---
name: docker-diagnose
description: Diagnose an unhealthy Docker Compose stack. Use when docker compose up fails, services are unhealthy, ports conflict, or the user reports "the stack won't start". Collects compose ps, service logs, port allocations, network state, and .env completeness into a triage summary that surfaces the real cause.
allowed-tools: Bash(docker *) Bash(lsof *) Bash(curl *)
---

# Docker Diagnose

When the stack won't start or is silently broken, stop guessing. Collect evidence in a fixed order, then interpret.

## Collection order

Run these in sequence. Each line below is a diagnostic step that surfaces a specific class of failure.

### 1. Compose state

```bash
docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'
```

- `State: created` but never `running` → service failed its first start; check logs.
- `unhealthy` → healthcheck failing; check logs + healthcheck test.
- Missing services → Compose file override issue or `--scale X=0` still in effect.

### 2. Logs for the unhealthy service

```bash
docker compose logs <service> --tail=100
```

Read the last ~50 lines. The pattern almost always falls into one of:

- Connection refused to dependency → check the dependency is running and on the same network.
- "Permission denied" → volume mount owner mismatch; inspect the mount.
- Python traceback → read the last frame; it's almost never the framework.
- SQL error → migration pending or schema drift.
- Exit immediately with code 0 → the service's CMD is one-shot (intentional for prestart) or the Dockerfile has no long-running process.

### 3. Port conflicts

```bash
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(80|443|5173|5432|8000|8080|8090|1080|1025)'
```

- Another container owns the port → `docker ps | grep <port>`; decide: stop that container or remap this one.
- Host process owns the port → process name tells you what's using it.

### 4. Network check

```bash
docker network ls | grep arcanum
docker network inspect arcanum_default --format '{{range .Containers}}{{.Name}} {{end}}'
```

- Expected containers missing from a network → service definition doesn't include that network, or container was created before the network was attached (happens with failed partial `up`).

### 5. .env sanity

```bash
grep -E '^(POSTGRES_|SECRET_KEY|FIRST_SUPERUSER|SMTP_)' .env | cut -d= -f1
```

- Missing required vars → container refuses to start with `Variable not set`.
- Placeholder values still in place (`changeme`, `example.com`) → app starts but behavior is wrong.

### 6. Backend health from inside

```bash
docker compose exec backend curl -sf http://localhost:8000/api/v1/utils/health-check/
```

- Returns `true` → backend is healthy internally; port mapping is the issue.
- 404 → router not registered.
- 500 → app layer error; check logs.
- `curl: (7) Failed to connect` → app isn't listening (crashed or not started).

## Common failure patterns

| Symptom | Likely cause | Fix |
|---|---|---|
| `port is already allocated` | Host port in use by another container or process | Stop the other process or remap in `compose.override.yml` |
| `prestart` exits 1 with DNS error on `db` | Networks got detached after a prior failed up | `docker compose down` then `up -d` |
| Backend healthy but frontend says CORS | `BACKEND_CORS_ORIGINS` in `.env` missing frontend URL | Update `.env`, `docker compose up -d` |
| DB healthy, backend starts but 500s on first request | Missing `alembic upgrade head` | Check prestart logs; rerun if needed |
| `image "docker.io/library/X:latest": already exists` during parallel build | BuildKit race when two services share an image tag | Build sequentially: `docker compose build backend frontend` |
| `failed to resolve host 'db'` from backend | Backend on `traefik-public` only, db on default; or container created before network | `docker compose down && docker compose up -d` |

## Output format

When reporting:

```
Stack state: <ok|degraded|broken>

Failing services:
- <service>: <status>, <one-line cause>

Likely root cause: <one sentence>

Suggested fix: <exact commands>
```

## Gotchas

- `docker compose logs -f` never exits — use `--tail=N` or pipe to `head`.
- `docker compose up` after a failed partial start may leave dangling containers in `created` state — always `down` first if state is weird.
- `docker compose ps` without `--all` hides exited containers — use `--all` to see them.
- Healthcheck says `healthy` but the app 500s → healthcheck tests the wrong endpoint; read the healthcheck spec in `compose.yml`.
- `docker compose exec` runs as root by default; permission issues in logs may be local-volume ownership mismatches.
- `docker system prune -a` kills more than you expect — never suggest this without confirming.
