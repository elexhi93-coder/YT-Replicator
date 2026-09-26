# SESSION TASK — Step 5.2: n8n Credential Setup Guide

## Your job in this session
This step is documentation and configuration — NOT code. Create a setup guide for configuring n8n credentials in the n8n UI.

## Read these files first:
1. `docs/N8N_WORKFLOW.md` — section: "Credentials Setup"
2. `docs/ARCHITECTURE.md` — section: "Security"

## What to create:
`docs/N8N_CREDENTIAL_SETUP.md` — a step-by-step guide for a human to follow in the n8n UI.

## The guide must cover these credentials:

### 1. OpenRouter API Key
- Where to get it: https://openrouter.ai/keys
- In n8n UI: Settings → Credentials → New → HTTP Header Auth
  - Name: "OpenRouter API"
  - Header Name: `Authorization`
  - Header Value: `Bearer sk-or-v1-YOUR_KEY_HERE`
- Which node uses it: "OpenRouter AI Rewrite"

### 2. YouTube OAuth2
- In n8n UI: Settings → Credentials → New → YouTube OAuth2
- Requirements: Google Cloud Console project, YouTube Data API v3 enabled
- Scopes needed: `https://www.googleapis.com/auth/youtube.upload`
- Which node uses it: "Upload to YouTube"

### 3. Dailymotion OAuth2
- In n8n UI: HTTP Request node uses Bearer token
- API: https://developer.dailymotion.com/api/
- Which node uses it: "Upload to Dailymotion"

### 4. Facebook / Meta
- Page Access Token (not user token)
- Which node uses it: "Upload to Facebook"

### 5. TikTok
- TikTok for Developers: https://developers.tiktok.com/
- Which node uses it: "Upload to TikTok"

## The guide must also include:
- How to test each credential in n8n (using the "Test" button)
- Warning: never put credentials in workflow.json or .env — n8n's encrypted credential store only
- How to export/backup credentials (n8n Settings → Backup)

## Test / pass criteria:
This is a documentation step. Pass criteria:
- The markdown file renders correctly
- All links are valid
- A non-developer could follow the guide without additional help

## When done:
- Show the full `docs/N8N_CREDENTIAL_SETUP.md`
- Do NOT build anything else in this session
