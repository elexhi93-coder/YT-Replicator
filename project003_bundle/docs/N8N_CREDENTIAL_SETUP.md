# n8n Credential Setup — project003

This guide walks a human (no developer skill required) through configuring every
credential the `project003` workflow needs. Follow the sections in order. You
only need to do each step once per machine; n8n stores everything in its
encrypted credential vault inside the `n8n_data` Docker volume.

> **Where to do this:** open n8n at <http://localhost:5678> after running
> `docker compose up -d`. Each credential is created in the n8n sidebar under
> **Credentials → + New Credential**.

> **Security rules — read first:**
>
> - Credentials live ONLY inside n8n. **Never** paste them into
>   `n8n/workflow.json`, `.env`, or any file checked into git.
> - The `n8n_data` Docker volume holds the encrypted vault. Back it up regularly
>   (see *Backup & restore* at the bottom of this page).
> - Rotate keys at the cadence required by each provider.

---

## 1. OpenRouter API Key (AI metadata enrichment)

**Used by:** *AI: Enrich Metadata* node (HTTP Request) — calls OpenRouter to
generate SEO titles, descriptions, and tags using the free Mistral model.

### a. Get the key

1. Go to <https://openrouter.ai/keys>.
2. Sign in (Google / GitHub) and click **+ Create Key**.
3. Copy the key — it starts with `sk-or-v1-…`. You will not see it again.

### b. Add it to n8n

1. n8n → **Credentials → + New Credential**.
2. Search for **HTTP Header Auth** and select it.
3. Fill in:
   - **Credential Name:** `OpenRouter API Key`
   - **Header Name:** `Authorization`
   - **Header Value:** `Bearer sk-or-v1-PASTE-YOUR-KEY-HERE`
4. **Save**.

### c. Wire it to the node

1. Open the workflow `project003 — Channel Replicator`.
2. Click the **AI: Enrich Metadata** node.
3. Under *Authentication* it should already be set to *Generic Credential
   Type → HTTP Header Auth*. From the *Credential* dropdown, pick
   `OpenRouter API Key`.
4. **Save** the workflow.

### d. Test

Click **Execute Node** on *AI: Enrich Metadata* with a pinned input that
contains a `title` and `channel_name`. A `200` response with a JSON body
containing `choices[0].message.content` means it's working.

---

## 2. YouTube OAuth2 (video upload)

**Used by:** *YouTube Upload* node.

### a. Google Cloud project

1. Open <https://console.cloud.google.com/>.
2. Create a project (or pick an existing one) named e.g. `project003-uploader`.
3. **APIs & Services → Library → YouTube Data API v3 → Enable**.
4. **APIs & Services → OAuth consent screen**:
   - User Type: **External**
   - Add yourself as a test user
   - Add scope: `https://www.googleapis.com/auth/youtube.upload`
5. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
   - Copy the **Client ID** and **Client Secret**.

### b. Add it to n8n

1. n8n → **Credentials → + New Credential**.
2. Pick **YouTube OAuth2 API**.
3. Fill in:
   - **Credential Name:** `YouTube OAuth2`
   - **Client ID:** *(paste from Google)*
   - **Client Secret:** *(paste from Google)*
4. Click **Connect my account** and complete the Google consent screen.
5. **Save**.

### c. Wire it & test

1. Open the **YouTube Upload** node.
2. Set *Credential* → `YouTube OAuth2`.
3. Click **Test step** — n8n will display the connected channel name.

---

## 3. Dailymotion OAuth2

**Used by:** *Dailymotion: Upload File* and *Dailymotion: Publish Video*
HTTP nodes (currently disabled — enable them only if you actually upload to
Dailymotion).

### a. Get OAuth client

1. <https://developer.dailymotion.com/> → **My API keys**.
2. **+ Create API key** → app type `Server-side` → save **Client ID** and
   **Client Secret**.
3. Add scopes: `manage_videos`, `read_videos`.

### b. Add it to n8n

1. n8n → **Credentials → + New Credential → OAuth2 API** (generic).
2. Fill in:
   - **Credential Name:** `Dailymotion OAuth2`
   - **Grant Type:** *Client Credentials*
   - **Access Token URL:** `https://api.dailymotion.com/oauth/token`
   - **Client ID:** *(paste)*
   - **Client Secret:** *(paste)*
   - **Scope:** `manage_videos read_videos`
3. **Save**, then **Connect**.

### c. Wire it

In each Dailymotion HTTP node, set *Authentication → Generic Credential Type
→ OAuth2 API*, then pick `Dailymotion OAuth2`.

---

## 4. Facebook Page Token

**Used by:** *Facebook Upload* node (currently disabled).

> **Important:** use a **Page** access token, not a user token. Pages can post
> videos; user tokens cannot.

### a. Get the token

1. <https://developers.facebook.com/apps/> → create an app of type *Business*.
2. Add the **Pages** product.
3. **Tools → Graph API Explorer**:
   - Pick your app.
   - **Get Token → Get Page Access Token** for the page you control.
   - Required permissions: `pages_manage_posts`, `pages_read_engagement`,
     `pages_show_list`.
4. Convert the short-lived token to a long-lived one (Graph Explorer's
   *Debug → Extend Access Token*). Copy the long-lived token.

### b. Add it to n8n

1. n8n → **Credentials → + New Credential → Facebook Graph API**.
2. **Credential Name:** `Facebook Page Token`.
3. Paste the **Page Access Token**.
4. **Save**.

### c. Wire it

Open *Facebook Upload* node → *Credential* → `Facebook Page Token`. Set
the **Page ID** parameter to your page's numeric ID (replace
`YOUR_FACEBOOK_PAGE_ID` placeholder).

---

## 5. TikTok Content Posting API

**Used by:** *TikTok Upload (HTTP)* node (currently disabled).

### a. Get OAuth client

1. <https://developers.tiktok.com/> → **Manage apps → + Create**.
2. Add the **Content Posting API** product. Submit for review (TikTok
   requires manual approval — this can take days).
3. After approval: copy **Client Key** and **Client Secret**.
4. Authorize a TikTok account against your app to get a refresh token via
   the TikTok OAuth flow.

### b. Add it to n8n

1. n8n → **Credentials → + New Credential → OAuth2 API**.
2. Fill in:
   - **Credential Name:** `TikTok OAuth2`
   - **Grant Type:** *Authorization Code*
   - **Authorization URL:** `https://www.tiktok.com/v2/auth/authorize/`
   - **Access Token URL:** `https://open.tiktokapis.com/v2/oauth/token/`
   - **Client ID:** *(Client Key from TikTok)*
   - **Client Secret:** *(Client Secret from TikTok)*
   - **Scope:** `video.upload video.publish`
   - **Auth URI Query Parameters:** `client_key={Client ID}`
3. **Save → Connect** and complete the TikTok consent screen.

### c. Wire it

Open *TikTok Upload (HTTP)* → *Authentication → Generic Credential Type →
OAuth2 API* → select `TikTok OAuth2`.

---

## 6. (Optional) Instagram & X / Twitter

These nodes ship disabled and are placeholders. If you enable them, follow
the same pattern:

| Node                         | Credential type             | Provider docs                                         |
|------------------------------|-----------------------------|--------------------------------------------------------|
| *Instagram Reels (HTTP)*     | OAuth2 (Instagram Graph)    | <https://developers.facebook.com/docs/instagram-api>   |
| *X / Twitter Post*           | OAuth2 (X v2 API)           | <https://developer.twitter.com/en/portal/dashboard>    |

---

## Testing every credential

For each credential you saved:

1. Open the node that uses it.
2. Pin a single test input (small JSON object — n8n's *Pin Data* feature).
3. Click **Test step**.
4. Look for a green tick and a 2xx HTTP response. A red X with `401`,
   `403`, or `invalid_grant` means the credential is wrong or expired.

---

## Backup & restore the credential vault

n8n encrypts every credential with the `N8N_ENCRYPTION_KEY` (auto-generated
on first start, stored inside `n8n_data`). To back up safely:

```bash
# Stop n8n briefly so the SQLite file is consistent
docker compose stop n8n

# Copy the entire named volume to a tarball
docker run --rm \
  -v project003_n8n_data:/data \
  -v "$(pwd)":/backup \
  alpine tar -czf /backup/n8n_data_$(date +%F).tar.gz -C /data .

docker compose start n8n
```

To restore on another machine: extract the tarball back into the
`project003_n8n_data` volume **before** the first `docker compose up`. The
encryption key inside the tarball must match the n8n install — keep them
together.

You can also export workflows (without credentials) from the n8n UI:
**⋯ menu → Download workflow JSON**. This is safe to commit; it never
contains secrets.

---

## Troubleshooting

| Symptom                                            | Likely cause / fix                                                                       |
|----------------------------------------------------|------------------------------------------------------------------------------------------|
| `401 Unauthorized` from OpenRouter                 | Key revoked or `Bearer ` prefix missing in the header value.                              |
| YouTube quota exceeded                             | Default quota = 10,000 units/day = ≈6 uploads. Request a quota increase in Google Cloud. |
| `invalid_grant` after connecting                   | Refresh token expired — click **Reconnect** on the credential.                            |
| Workflow fails silently after upload               | Check the *Notify Dashboard* node — its URL must be `http://dashboard:8080/api/callback`.|
| Dashboard shows nothing in `/history`              | Verify n8n container can resolve `dashboard` (same Docker network: `project003_default`). |

---

*Once every credential shows a green tick on **Test step**, the workflow is
ready to receive jobs from the watcher.*
