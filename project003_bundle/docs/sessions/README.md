# Session Briefs — project003
## How to Use These Files

Each file in this folder is a **ready-to-paste session starter** for a specific build step.

### Workflow:
1. Open a new VS Code Copilot Chat session
2. Open the session brief file for the step you want to build
3. Copy the entire contents and paste it as your first message
4. The AI will read the referenced docs, then build exactly that step
5. When done, close the session and move to the next step

### Rules for AI sessions:
- Each session builds **one step only**
- Do not ask the AI to build ahead or combine steps
- After each session, verify the test criteria before moving on
- If a step fails, fix it in the same session before closing

### Step Index:

| Step | File | What gets built |
|------|------|----------------|
| 1.1  | [STEP_1_1_models.md](STEP_1_1_models.md) | SQLite schema (`dashboard/models.py`) |
| 1.2  | [STEP_1_2_migrate.md](STEP_1_2_migrate.md) | JSON → SQLite migration script |
| 1.3  | [STEP_1_3_compose.md](STEP_1_3_compose.md) | docker-compose.yml update |
| 1.4  | [STEP_1_4_env.md](STEP_1_4_env.md) | .env files + db/ folder |
| 2.1  | [STEP_2_1_watcher.md](STEP_2_1_watcher.md) | Watcher: JSON → SQLite migration |
| 2.2  | [STEP_2_2_watcher_docker.md](STEP_2_2_watcher_docker.md) | Watcher Dockerfile cleanup |
| 3.1  | [STEP_3_1_flask.md](STEP_3_1_flask.md) | Flask app skeleton + all API routes |
| 3.2  | [STEP_3_2_base.md](STEP_3_2_base.md) | Base HTML template + navigation |
| 3.3  | [STEP_3_3_pipelines.md](STEP_3_3_pipelines.md) | Pipelines page (full HTMX) |
| 3.4  | [STEP_3_4_queue.md](STEP_3_4_queue.md) | Queue page + SSE live updates |
| 3.5  | [STEP_3_5_history.md](STEP_3_5_history.md) | History page + filters |
| 3.6  | [STEP_3_6_logs.md](STEP_3_6_logs.md) | Logs page + auto-refresh |
| 4.1  | [STEP_4_1_processor_docker.md](STEP_4_1_processor_docker.md) | Processor Dockerfile + requirements |
| 4.2  | [STEP_4_2_processor.md](STEP_4_2_processor.md) | processor.py (FFmpeg job runner) |
| 4.3  | [STEP_4_3_gpu.md](STEP_4_3_gpu.md) | GPU/NVENC support |
| 5.1  | [STEP_5_1_n8n.md](STEP_5_1_n8n.md) | n8n workflow.json update |
| 5.2  | [STEP_5_2_credentials.md](STEP_5_2_credentials.md) | n8n credential setup guide |
| 6.1  | [STEP_6_1_integration.md](STEP_6_1_integration.md) | Full integration test |
