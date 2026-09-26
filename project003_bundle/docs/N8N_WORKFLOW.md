# n8n Workflow Specification
## project003 — Nodes, Logic, and OpenRouter Integration

**Status:** LOCKED  
**Current workflow file:** `./n8n/workflow.json`  
**n8n UI:** `http://<server-ip>:5678`  
**Workflow name:** "project003 — Channel Replicator"

---

## 1. Workflow Overview

The n8n workflow is triggered by a webhook from the `processor` container. It enriches metadata with AI, then uploads the processed video to a target platform. One workflow execution = one video × one destination.

```
[Webhook Trigger]
       │
       ▼
[Prepare Video Data]    ← validate fields, normalize file_path
       │
       ▼
[AI: Enrich Metadata]   ← OpenRouter API call (Mistral 7B free)
       │
       ▼
[AI: Parse & Fallback]  ← parse JSON response, fallback to original on failure
       │
       ├──── platform == "youtube"     → [Upload: YouTube]
       ├──── platform == "dailymotion" → [Upload: Dailymotion]
       ├──── platform == "facebook"    → [Upload: Facebook]
       └──── platform == "tiktok"      → [Upload: TikTok (HTTP)]
                                               │
                                               ▼
                                        [Callback: Dashboard]
```

---

## 2. Node Definitions

### Node 1: `Webhook: IDM-YT Download`
**Type:** Webhook Trigger  
**Path:** `idm-yt-download` (or per-pipeline path configured in destinations table)  
**Method:** POST  
**Response mode:** `onReceived` (acknowledges immediately, processes async)  

**Purpose:** Entry point. Receives the payload from the processor after a video is processed and ready for upload.

**Validation:** None at this node — validation is done in Node 2.

---

### Node 2: `Prepare Video Data`
**Type:** Code (JavaScript)  
**Runs after:** Node 1

**Purpose:** Validate required fields, normalize the file_path, and structure the data for downstream nodes.

**Logic:**
```javascript
const body = $input.first().json;

// Validate required fields
if (!body.file_path) throw new Error('No file_path in payload');
if (!body.job_id)    throw new Error('No job_id in payload');

// Normalize Windows-style backslashes to forward slashes
const filePath = body.file_path.replace(/\\/g, '/');

return [{
  json: {
    job_id:          body.job_id,
    destination_id:  body.destination_id,
    pipeline_id:     body.pipeline_id,
    platform:        body.platform       || 'youtube',
    title:           body.original_title || 'Untitled Video',
    description:     body.original_description || '',
    file_path:       filePath,
    thumbnail_path:  (body.thumbnail_path || '').replace(/\\/g, '/'),
    source_url:      body.source_url     || '',
    channel_name:    body.channel_name   || '',
    channel_id:      body.channel_id     || '',
    duration:        body.duration       || 0,
    timestamp:       body.timestamp      || new Date().toISOString(),
  }
}];
```

---

### Node 3: `AI: Enrich Metadata`
**Type:** HTTP Request  
**Method:** POST  
**URL:** `https://openrouter.ai/api/v1/chat/completions`  
**`continueOnFail`: true** ← critical — upload still happens if AI is unavailable  

**Authentication:** HTTP Header Auth  
**Credential name in n8n:** "OpenRouter API Key"  
**Header:** `Authorization: Bearer {api_key}`  
**Extra headers:**
- `HTTP-Referer: https://github.com/project003`
- `X-Title: project003 Channel Replicator`

**Request body:**
```json
{
  "model": "mistralai/mistral-7b-instruct:free",
  "messages": [
    {
      "role": "system",
      "content": "You are an expert YouTube SEO specialist. Given a video title and channel name, return ONLY a valid JSON object with no markdown, no explanation, just the raw JSON. The object must have these exact keys: youtube_title (max 100 chars, SEO-optimized), youtube_description (150-300 chars, includes keywords and a call-to-action), youtube_tags (array of 10-15 SEO keywords as strings)."
    },
    {
      "role": "user",
      "content": "Video title: {title}\nChannel: {channel_name}\nSource URL: {source_url}"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 600
}
```

**Variables substituted from Node 2 output:**
- `{title}` → `$('Prepare Video Data').item.json.title`
- `{channel_name}` → `$('Prepare Video Data').item.json.channel_name`
- `{source_url}` → `$('Prepare Video Data').item.json.source_url`

**Timeout:** 30 seconds  

**Why Mistral 7B free?** It's available on OpenRouter's free tier, handles JSON output reliably with the right system prompt, and is fast enough for batch processing.

**Alternative models (if Mistral free is unavailable):**
- `google/gemma-3-27b-it:free`
- `meta-llama/llama-3.3-70b-instruct:free`
- These are also free on OpenRouter. Switch the `model` field if needed.

---

### Node 4: `AI: Parse & Fallback`
**Type:** Code (JavaScript)  
**Runs after:** Node 3

**Purpose:** Parse the AI response JSON. If AI failed, format is wrong, or model returned markdown code fences — fall back to original metadata gracefully.

**Logic:**
```javascript
const original = $('Prepare Video Data').first().json;
let aiData = null;

try {
  const aiResponse = $('AI: Enrich Metadata').first().json;
  const content = aiResponse?.choices?.[0]?.message?.content;
  if (content) {
    // Strip markdown code fences if model added them (```json ... ```)
    const cleaned = content
      .replace(/```json\s*/gi, '')
      .replace(/```\s*/g, '')
      .trim();
    aiData = JSON.parse(cleaned);
  }
} catch (e) {
  console.log('[project003] AI parse failed, using original metadata: ' + e.message);
}

return [{
  json: {
    // AI enriched (or fallback)
    youtube_title:       (aiData?.youtube_title || original.title).substring(0, 100),
    youtube_description: aiData?.youtube_description || original.description,
    youtube_tags:        aiData?.youtube_tags || [],
    ai_used:             !!aiData,
    // Original passthrough
    job_id:         original.job_id,
    destination_id: original.destination_id,
    platform:       original.platform,
    file_path:      original.file_path,
    thumbnail_path: original.thumbnail_path,
    source_url:     original.source_url,
    channel_name:   original.channel_name,
    duration:       original.duration,
    timestamp:      original.timestamp,
  }
}];
```

---

### Node 5: `Router: Platform`
**Type:** Switch  
**Runs after:** Node 4  

Routes execution to the correct upload node based on `platform` field.

| Condition          | Output branch |
|--------------------|---------------|
| `platform == "youtube"`     | → Node 6a |
| `platform == "dailymotion"` | → Node 6b |
| `platform == "facebook"`    | → Node 6c |
| `platform == "tiktok"`      | → Node 6d |
| (fallback/unknown)          | → Node 7 (callback with error) |

---

### Node 6a: `Upload: YouTube`
**Type:** YouTube node (n8n built-in)  
**Operation:** Video → Upload  
**Credential:** YouTube OAuth2 (configured in n8n credential store)  

**Parameters:**
```
Title:       {{ $json.youtube_title }}
Description: {{ $json.youtube_description }}
Tags:        {{ $json.youtube_tags.join(',') }}
Category:    22  (People & Blogs — change as needed)
Privacy:     public
File:        {{ $json.file_path }}
```

**`continueOnFail`: true** — failure is handled by Node 7 callback

---

### Node 6b: `Upload: Dailymotion`
**Type:** HTTP Request (Dailymotion API)  
**Authentication:** OAuth2 custom credential  

**Flow (two-step upload):**
1. POST `https://api.dailymotion.com/file/upload` → get upload URL
2. PUT file to upload URL
3. POST `https://api.dailymotion.com/me/videos` with url, title, description, tags

**`continueOnFail`: true**

---

### Node 6c: `Upload: Facebook`
**Type:** HTTP Request (Facebook Graph API)  
**Authentication:** HTTP Header Auth with Page Access Token  

**Flow:**
1. POST `https://graph-video.facebook.com/{page_id}/videos`
   - `file_url` or multipart upload for large files
   - `title`, `description`

**`continueOnFail`: true**

---

### Node 6d: `Upload: TikTok`
**Type:** HTTP Request (TikTok Content Posting API)  
**Authentication:** HTTP Header Auth with TikTok API Bearer token  

**Note:** TikTok's official Content Posting API requires app approval. In v1, this node posts via the TikTok Content Posting API (requires `video.upload` scope). If approval is not available, this destination is disabled until approval is obtained.

**`continueOnFail`: true**

---

### Node 7: `Callback: Dashboard`
**Type:** HTTP Request  
**Method:** POST  
**URL:** `http://dashboard:8080/api/callback`  
**Runs after:** All upload nodes (merge paths)  

**Purpose:** Report upload result back to the dashboard regardless of success or failure.

**Body (dynamically built):**
```javascript
// Build callback body based on which upload node executed
const enriched = $('AI: Parse & Fallback').first().json;
const uploadResult = $input.first().json;  // from whichever upload node ran

// Determine status
let status = 'success';
let uploadUrl = '';
let errorMessage = '';

if (uploadResult.error || $execution.resumeUrl) {
  status = 'failed';
  errorMessage = uploadResult.error?.message || 'Unknown upload error';
} else {
  // Extract URL based on platform
  uploadUrl = uploadResult.id
    ? `https://youtu.be/${uploadResult.id}`  // YouTube
    : uploadResult.url || '';
}

return [{
  json: {
    job_id:          enriched.job_id,
    destination_id:  enriched.destination_id,
    platform:        enriched.platform,
    status:          status,
    upload_url:      uploadUrl,
    error_message:   errorMessage,
    ai_used:         enriched.ai_used,
    ai_title:        enriched.youtube_title,
    ai_description:  enriched.youtube_description,
    ai_tags:         enriched.youtube_tags,
  }
}];
```

**Response handling:** Dashboard returns `{"ok": true}`. If dashboard is down, n8n logs the failure but does not retry (the upload already happened).

---

## 3. Credential Setup Guide

### OpenRouter API Key
1. Create account at https://openrouter.ai
2. Go to Keys → Create new key
3. In n8n: Credentials → New → HTTP Header Auth
   - Name: "OpenRouter API Key"
   - Header name: `Authorization`
   - Header value: `Bearer sk-or-...your-key...`

### YouTube OAuth2
1. Create a Google Cloud project
2. Enable YouTube Data API v3
3. Create OAuth2 credentials (Desktop app type)
4. In n8n: Credentials → New → YouTube OAuth2
5. Authorize in n8n with the Google account that owns the target channel

### Dailymotion OAuth2
1. Create app at https://developer.dailymotion.com
2. In n8n: Credentials → New → custom OAuth2
   - Auth URL: `https://www.dailymotion.com/oauth/authorize`
   - Token URL: `https://www.dailymotion.com/oauth/token`
   - Scopes: `manage_videos write`

### Facebook Page Token
1. Create a Meta Developer app with `pages_manage_posts` permission
2. Generate a Page Access Token (long-lived) via Graph API Explorer
3. In n8n: Credentials → New → HTTP Header Auth
   - Header: `Authorization: Bearer {page_access_token}`

---

## 4. Workflow Import

The workflow is version-controlled in `./n8n/workflow.json`. To import:

1. Open n8n UI at `http://localhost:5678`
2. Top menu → Workflows → Import from File
3. Select `./n8n/workflow.json`
4. Configure credentials (see Section 3)
5. Activate the workflow (toggle in top-right)

**After importing:** Update the webhook path in each destination's `n8n_webhook_url` in the dashboard to match the imported workflow's webhook URL.

---

## 5. Monitoring n8n Executions

- Workflow executions are visible at `http://localhost:5678/executions`
- Failed executions show the exact node and error
- n8n retains last 1000 executions by default
- Each execution takes 5–30 seconds (depending on AI response time and file size)

---

*Next: [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md)*
