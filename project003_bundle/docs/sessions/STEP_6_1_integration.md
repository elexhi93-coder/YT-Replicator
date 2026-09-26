# SESSION TASK — Step 6.1: Full Integration Test

## Your job in this session
Run the full system end-to-end and verify every component is working together. This is a test-and-fix session — if something is broken, fix it here.

## Read these files first:
1. `docs/BUILD_ORDER.md` — section: "Phase 6: Integration"
2. `docs/DATA_FLOW.md` — section: "Happy Path: Monitor Flow" (this is the scenario you will test)
3. `docs/API_CONTRACTS.md` — all endpoints (to verify they respond correctly)

## Prerequisites before starting:
All previous steps (1.1 through 5.2) must be complete. Verify:
- [ ] `dashboard/models.py` exists
- [ ] `dashboard/migrate_config.py` exists and has been run
- [ ] `docker-compose.yml` has all 5 services
- [ ] `.env` file exists with real values filled in
- [ ] `headless_watcher.py` uses SQLite
- [ ] `watcher/Dockerfile` exists
- [ ] `dashboard/app.py` has all API routes
- [ ] All HTML templates exist
- [ ] `processor/Dockerfile` and `processor/processor.py` exist
- [ ] `n8n/workflow.json` has been updated
- [ ] n8n credentials configured in n8n UI

## Integration test procedure:

### Step 1: Start all containers
```bash
cd project003
docker compose up -d
docker compose ps  # all 5 must show "running"
```

### Step 2: Verify dashboard
```bash
curl http://localhost:8080/api/pipelines
# Must return JSON with at least one pipeline (from migration)
```
Open `http://localhost:8080` in browser — must load pipelines page.

### Step 3: Verify watcher connects to DB
```bash
docker compose logs watcher | head -20
# Must show: "Loaded X active source(s) from database"
# Must NOT show: "channel_monitor_config.json" errors
```

### Step 4: Trigger a manual backfill
```bash
docker compose exec watcher python headless_watcher.py --mode backfill --max-videos 1
```
Must show: "Queued 1 video(s) for download" and fire webhook to n8n.

### Step 5: Check job appears in queue
```bash
curl http://localhost:8080/api/queue
# Must show 1 job with status 'queued' or 'downloading'
```
Open `http://localhost:8080/queue` — job must appear within 2 seconds via SSE.

### Step 6: Verify n8n receives webhook
Open `http://localhost:5678` → check execution history.
Must show a completed or in-progress execution.

### Step 7: Verify processor picks up job
```bash
docker compose logs processor | tail -20
# Must show: "Processing job <id>..."
```

### Step 8: Verify callback reaches dashboard
```bash
curl http://localhost:8080/api/history
# Must show 1 completed or failed job
```

### Step 9: Check logs page
Open `http://localhost:8080/logs` — switch between container tabs, verify logs appear.

## Known issues to watch for:
- SQLite "database is locked" — means WAL mode wasn't set properly in one container
- n8n can't reach dashboard — check Docker network (`project003_net`)
- Processor finds no jobs — check `download_jobs.status` value in DB
- SSE connection drops — check `X-Accel-Buffering: no` header in SSE route

## When done:
- Show output of each step above
- List any issues found and how they were fixed
- Confirm all 8 steps pass
- The system is DONE ✓
