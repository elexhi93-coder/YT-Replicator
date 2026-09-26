# SESSION TASK — Step 5.1: n8n Workflow Update

## Your job in this session
Update `n8n/workflow.json` to match the target architecture: ensure `destination_id` passes through all nodes, the callback URL points to `http://dashboard:8080/api/callback`, and the OpenRouter AI node uses the correct model and prompt.

## Read these files first (in this order):
1. `docs/N8N_WORKFLOW.md` — the full target workflow spec: all nodes, connections, parameters
2. `docs/API_CONTRACTS.md` — section: `POST /api/callback` payload
3. Current `n8n/workflow.json` — what exists (you are updating this, not replacing it)

## Hard constraints:
- Do NOT break any working node — only modify what is specified below
- Preserve all existing node IDs where possible (n8n uses IDs internally)
- The `workflow.json` must be valid JSON (use a JSON linter or `python -m json.tool` to verify)
- OpenRouter model: `mistralai/mistral-7b-instruct:free` (free tier — do not change to a paid model)
- The callback URL must be: `http://dashboard:8080/api/callback` (Docker internal DNS)
- `destination_id` must be present in the HTTP Request node payload that calls the callback

## What to verify / fix in the workflow:

### Node: "Webhook" (trigger)
- Must accept: `job_id`, `source_id`, `destination_id`, `video_id`, `title`, `url`, `channel_name`
- Verify `destination_id` is captured from the webhook payload

### Node: "Prepare Data" (Set/Code node)
- Must pass `destination_id` forward to subsequent nodes
- If it's a Set node, ensure `destination_id` is in the mapped fields

### Node: "OpenRouter AI Rewrite" (HTTP Request node)
- URL: `https://openrouter.ai/api/v1/chat/completions`
- Model: `mistralai/mistral-7b-instruct:free`
- Prompt template (from N8N_WORKFLOW.md — use the exact prompt)
- Authorization: `Bearer {{ $credentials.openRouterApi.apiKey }}`

### Node: "Parse AI Response" (Code node)
- Must handle the case where AI returns malformed JSON (fallback to original title/description)
- Must output: `title`, `description`, `tags`

### Node: "Notify Dashboard" (HTTP Request node)
- Method: POST
- URL: `http://dashboard:8080/api/callback`
- Body (JSON):
```json
{
  "job_id": "{{ $json.job_id }}",
  "status": "uploaded",
  "destination_id": "{{ $json.destination_id }}",
  "platform_video_id": "{{ $json.youtube_video_id }}"
}
```

## Validation steps:
1. Run `python -m json.tool n8n/workflow.json > /dev/null && echo "Valid JSON"` — must pass
2. Import the workflow into n8n UI (n8n → Import from File)
3. Verify all nodes appear with no red error indicators
4. Check that "Notify Dashboard" node shows URL `http://dashboard:8080/api/callback`

## When done:
- Show a diff or summary of what changed in `workflow.json`
- Show the "Notify Dashboard" node JSON block
- Confirm `python -m json.tool` passes
- Do NOT build anything else in this session
