# 01 — Frontend Specification: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/00_PILLAR_OVERVIEW.md`  

---

## 1. Executive Summary & Screen Inventory

Pillar 1 provides the operator interface for managing content origins (channels and playlists)
and exploring discovered video inventory. In accordance with `INV-7`, all interactions on these
screens are **metadata-only**: no button triggers media downloads or file writes to local storage.

### Screen & Component List
1. **Screen 1: Sources Management (`/sources`)**
   - Header & Summary KPI bar (Total Sources, Active Monitors, Total Discovered Items).
   - Source List Table (configured channels/playlists, sync status, health pills, cadence).
   - Action Modal: **Add Source Modal** (URL input, SSRF validation, scan depth selector).
   - Action Modal: **Edit Source Settings Drawer** (cadence, monitor toggle, auto-scan).
   - Action Modal: **Delete / Archive Confirmation Dialog**.
2. **Screen 2: Catalog Explorer (`/catalog`)**
   - Catalog Filter Bar (source filter, text search, date range, duration range, live status, availability).
   - Catalog Items Grid / Data Table (thumbnail, title, source, duration, published date, replicate status).
   - Side Drawer: **Video Inspector Drawer** (hydrated metadata, tags chip-cloud, description preview, raw JSON tab).
   - Batch Action Bar (multi-select actions: "Mark as Replicated", "Ignore", "Export CSV").

---

## 2. Screen 1: Sources Management (`/sources`)

### 2.1 Screen Purpose & Route
- **Route**: `/sources`
- **Entry Points**: Primary navigation bar item "Sources".
- **Primary Goal**: Allow operators to register YouTube channels or playlists, observe
  sync health, trigger manual scans, and configure automated polling cadences.

### 2.2 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Sources Library                           [ + Add New Source Button] │
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Bar: [ 12 Sources Total ]  [ 10 Auto-Syncing ]  [ 4,281 Catalog Items ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search & Quick Filter: [ Filter by channel title or URL... ] [ All Statuses ▼]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Sources Data Table                                                          │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Channel / Playlist │ Status │ Last Scan │ Items │ Cadence │ Actions     │ │
│ ├────────────────────┼────────┼───────────┼───────┼─────────┼─────────────┤ │
│ │ [Thumb] Veritasium │ [SYNC] │ 4m ago    │ 412   │ 15m     │ [Scan][Edit]│ │
│ │ [Thumb] 3Blue1Brown│ [IDLE] │ 2h ago    │ 188   │ 60m     │ [Scan][Edit]│ │
│ │ [Thumb] Old Archive│ [ERR]  │ 1d ago    │ 95    │ Paused  │ [Retry][Edit│ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Table Columns & Data Lineage

| Column Header | Display Value | Origin Field (00 §5) | Sortable | Width | Formatting & UX |
|---|---|---|---|---|---|
| **Channel / Source** | Thumbnail + Title + Channel ID | `sources.title`, `sources.channel_id`, `sources.thumbnail_url` | Yes (Title) | 320px | 40x40 circular avatar, title in bold, canonical ID (`UC...`) below in muted mono font. |
| **Type** | Badge: `Channel` or `Playlist` | `sources.source_type` | Yes | 100px | Slate badge for Playlist, Indigo badge for Channel. |
| **Sync Status** | Health Status Pill | `sources.sync_status` | Yes | 120px | Green: `HEALTHY`, Amber: `SCANNING`, Red: `FAILED`, Gray: `PAUSED`. |
| **Last Sync** | Relative timestamp + icon | `sources.last_scanned_at` | Yes | 140px | e.g. "5 mins ago". Hover shows absolute ISO UTC. |
| **Catalog Count** | Count of items | Derived `count(catalog_video.id)` | Yes | 100px | Number with link to `/catalog?source_id={id}`. |
| **Monitor Cadence**| Polling Interval | `sources.monitor_interval_sec` | No | 110px | "15 mins", "60 mins", or "Manual only". |
| **Actions** | Action Button Group | N/A | No | 160px | [Scan Now] (Primary icon), [Edit] (Pencil), [Delete] (Trash). |


### 2.4 Control Behaviors & Validation

#### A. "+ Add New Source" Modal
- **Trigger**: Click `[+ Add New Source]` in header.
- **Fields**:
  1. `Source URL or Handle` (`string`, required):
     - *Client validation*: Must start with `https://www.youtube.com/` or `https://youtu.be/` or `@handle`. Rejects internal IPs, `localhost`, `file://` (SSRF guard).
     - *Helper text*: "Paste channel URL, handle (e.g. @veritasium), or playlist URL."
  2. `Scan Depth` (`select`, default: `Recent 50`):
     - Options: `Latest 50 items (Fast)`, `Full Channel Backfill (All)`, `Monitor Only (No initial backfill)`.
  3. `Monitor Cadence` (`select`, default: `15 minutes`):
     - Options: `5 minutes`, `15 minutes`, `30 minutes`, `60 minutes`, `Manual only`.
- **Primary Button**: `[Verify & Connect]`
  - *Loading state*: Button disabled, spinner active, text: "Resolving channel metadata...".
  - *Success behavior*: Modal closes, toast notification: "Source Veritasium connected successfully", row inserted at top of table with `SCANNING` badge.
  - *Failure behavior*: Inline error banner under URL input: "Failed to resolve YouTube source. Verify the channel URL or check your network connection."

#### B. "Scan Now" Button (Per Row)
- **Behavior**: Dispatches `sources.scan` task via `jobs.api`.
- **States**:
  - Disabled if row status is `SCANNING`.
  - On click: Status instantly transitions to `SCANNING` (optimistic UI update).
  - Spinner appears in row action column.

---

## 3. Screen 2: Catalog Explorer (`/catalog`)

### 3.1 Screen Purpose & Route
- **Route**: `/catalog`
- **Entry Points**: Navigation item "Catalog", or clicking "Catalog Count" link on any source row.
- **Primary Goal**: Give the operator a searchable, sortable view of all media items discovered across all sources, allowing inspection of metadata, filtering by duration/status, and manual tagging.

### 3.2 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Media Catalog                                  [ Export CSV ]       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Filter Toolbar:                                                             │
│ [ Source: All Sources ▼] [ Search Title / ID... ] [ Availability: All ▼]   │
│ [ Duration: Any ▼] [ Live Status: All ▼] [ Replication: All ▼] [ Clear ]   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Batch Actions (shown when >= 1 item checked):                               │
│ [ 3 items selected ] -> [ Mark as Already Uploaded ] [ Ignore ] [ Deselect ]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Catalog Grid Table                                                          │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ [x] │ Thumb │ Title & Video ID │ Source │ Dur │ Published │ Replicated?│ │
│ ├─────┼───────┼──────────────────┼────────┼─────┼───────────┼───────────┤ │
│ │ [ ] │ [Img] │ How Trees Move   │ Veritas│14:22│ 2026-09-20│ [ No ]    │ │
│ │     │       │ ID: abcd1234XYZ  │        │     │           │           │ │
│ │ [x] │ [Img] │ The Calculus Map │ 3Blue1B│21:05│ 2026-09-18│ [ Yes ]   │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ Pagination: Showing 1-50 of 4,281 items           [ < Page 1 of 86 > ]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Catalog Data Table Columns

| Column | Field Lineage | Type / Format | Width | Notes & Interactions |
|---|---|---|---|---|
| `[x]` | Checkbox | Selection | 40px | Header checkbox selects all 50 items on page. |
| **Thumbnail** | `catalog_video.thumbnail_url` | Image (16:9) | 90px | 80x45 rounded preview. Click triggers Video Inspector. |
| **Title & ID** | `catalog_video.title`, `catalog_video.video_id` | Text + Subtext | Flex (min 280px) | Title is clickable (opens Video Inspector). External link icon opens YouTube video in new tab. |
| **Source Channel** | `sources.title` | Text badge | 160px | Links to source details. |
| **Duration** | `catalog_video.duration_seconds` | Monospace `HH:MM:SS` | 90px | Formatted via `format_duration()`. N/A if null. |
| **Published** | `catalog_video.published_at` | UTC Date | 120px | `YYYY-MM-DD`. Hover shows relative "X days ago". |
| **Replication Status** | Sourced via Ledger (`delivery.api`) | Status Tag | 130px | Green `REPLICATED`, Gray `UNREPLICATED`, Orange `IGNORED`. |

---

## 4. Component: Video Inspector Drawer

### 4.1 Drawer Specifications
- **Behavior**: Slides out from right edge (width: `640px`) when clicking any catalog row, thumbnail, or "Inspect Metadata" menu item.
- **Header**: Video Title, Close button `[X]`, and External YouTube link `[↗]`.

### 4.2 Content Tabs

#### Tab 1: Metadata Overview
- **Large Thumbnail Preview**: 16:9 high-resolution preview (`maxresdefault.jpg`).
- **Core Metrics Strip**:
  - Duration: `14m 22s`
  - Published: `Sep 20, 2026 14:32 UTC`
  - Views: `1,280,441`
  - Likes: `45,210` (or `Hydration Required` if null)
  - Live Status: `not_live`
  - Availability: `public`
- **Description Block**: Scrollable formatted description box (preserves linebreaks and links).
- **Tags Cloud**: Chip list displaying all keywords from `catalog_video.tags`. If empty: "No tags found or hydration pending."
- **Chapters List**: Ordered timestamps with titles if chapters exist in `raw_metadata->'chapters'`.

#### Tab 2: Raw JSON Payload (`raw_metadata`)
- Read-only syntax-highlighted code box rendering `catalog_video.raw_metadata`.
- Action: `[Copy Raw JSON]` button at top right.
- Purpose: Operator troubleshooting and verifying yt-dlp extraction faithfulness.

---

## 5. UI States & Defensive Behaviors

### 5.1 Empty States
- **No Sources Connected**:
  - Icon: Empty Satellite dish illustration.
  - Heading: "No content sources connected yet."
  - Text: "Add your first YouTube channel or playlist to begin cataloging media."
  - Action Button: Large centered `[+ Add YouTube Source]`.
- **Empty Catalog**:
  - Heading: "No catalog items found."
  - Text: "Try clearing your search filters, or trigger a manual scan on your sources."

### 5.2 Error & Partial Failure Presentation (`F-48`)
- If a source scan encounters deleted, private, or geo-restricted items:
  - The source sync status badge displays `PARTIAL_WARNING` (amber).
  - Hovering displays a tooltip: *"Scan completed. 3 items were skipped because they are private or deleted."*
  - Clicking opens a Scan Log modal displaying the skipped video IDs and error reasons without breaking the catalog.

### 5.3 Long-Running Action Feedback
- When a "Full Backfill" scan is initiated:
  - Progress bar appears under the source row: *"Discovered 450 items... scanning page 10"*.
  - UI updates in real-time via WebSocket or periodic 2-second polling on `jobs.api`.

---

## 6. Verification Checklist (Definition of Done for Frontend)

- [ ] All 17 YouTube Field Universe attributes from `00_PILLAR_OVERVIEW.md` are accounted for in either the Grid or Inspector Drawer.
- [ ] No button or link in this specification triggers a media download (`INV-7`).
- [ ] SSRF validation regex blocks private IP addresses, loopback addresses, and non-YouTube protocols.
- [ ] Empty, Loading, Partial Warning (`F-48`), and Error states are fully designed.

| **Actions** | N/A | Icon Button | 60px | `[...]` menu: "Inspect Metadata", "Copy Video ID", "Force Hydrate". |
