# SESSION TASK — Step 1.3 + 1.4: docker-compose.yml + .env files

## Your job in this session
Update `docker-compose.yml` to match the full target architecture, and create `.env` and `.env.example` files.

## Read these files first (in this order):
1. `docs/CONTAINER_SPECS.md` — the full target docker-compose spec, all 5 services, env vars, volume mounts
2. `docs/ARCHITECTURE.md` — sections: "Container Map", "Volumes & Shared State"
3. Current `docker-compose.yml` — what exists now (must be updated, not replaced blindly)

## Hard constraints:
- Do NOT remove or break the existing `n8n` service configuration
- All services that access the database must mount `./db:/data`
- External downloads path must use the `DOWNLOADS_PATH` env var: `${DOWNLOADS_PATH:-./downloads}:/downloads`
- All inter-container communication uses service name DNS (e.g., `http://dashboard:8080`)
- Network name: `project003_net` (bridge driver)
- No hardcoded secrets in docker-compose.yml — all secrets come from `.env`
- `restart: unless-stopped` on all services

## Files to modify / create:

### 1. Modify `docker-compose.yml`
The final file must define these 5 services:

| Service | Image/Build | Port | Key env vars |
|---------|------------|------|-------------|
| `n8n` | `n8nio/n8n:latest` | `5678:5678` | N8N_BASIC_AUTH_*, WEBHOOK_URL |
| `dashboard` | `build: ./dashboard` | `8080:8080` | DB_PATH, DOWNLOADS_PATH |
| `watcher` | `build: ./watcher` | (none) | DB_PATH, DOWNLOADS_PATH, N8N_WEBHOOK_URL |
| `processor` | `build: ./processor` | (none) | DB_PATH, DOWNLOADS_PATH, DASHBOARD_URL |
| `db-init` | `build: ./dashboard` | (none) | DB_PATH — runs `python migrate_config.py` then exits |

All services share volume `./db:/data` (DB_PATH=/data/app.db).

`db-init` has `restart: "no"` and `command: python migrate_config.py`.

### 2. Create `.env.example`
```
# Database
DB_PATH=/data/app.db

# Storage
DOWNLOADS_PATH=./downloads

# n8n
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=changeme
N8N_ENCRYPTION_KEY=changeme32charslongkeyhere12345

# Webhook
N8N_WEBHOOK_URL=http://n8n:5678/webhook/video-download
DASHBOARD_URL=http://dashboard:8080
```

### 3. Create `.env` (copy of .env.example — user fills in real values)
Same content as `.env.example`. Add `.env` to `.gitignore` if it exists.

## Test / pass criteria:
Run `docker compose config` from the project root.
It must output a valid merged config with no errors.
All 5 services must appear. Volume `./db` must be present.

## When done:
- Show the full updated `docker-compose.yml`
- Show `.env.example`
- Show `docker compose config` output (or the first 50 lines if long)
- Do NOT build anything else in this session
