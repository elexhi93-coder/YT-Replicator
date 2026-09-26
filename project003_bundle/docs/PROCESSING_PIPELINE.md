# Processing Pipeline Specification
## project003 — FFmpeg Step Types and Parameters

**Status:** LOCKED  
**Executed by:** `processor` container  
**Configured via:** `processing_steps` table (see DATABASE_SCHEMA.md)

---

## 1. Overview

The processor reads the `processing_steps` table for a given pipeline and applies them to the source video file in `step_order` sequence. It produces one output file per destination.

### Execution Model

```
source.mp4
    │
    ▼ (global steps applied to all destinations)
    ├── Global Step 0: trim (0–180s)
    ├── Global Step 1: normalize_audio
    │
    ▼ (per-destination steps applied on top of global result)
    ├── Destination: YouTube (16:9)
    │   ├── Step 0: crop (16:9, center)
    │   ├── Step 1: watermark (logo, bottom-right)
    │   └── Step 2: reencode (h264, 1080p, 8Mbps)
    │   └── OUTPUT → job_{id}/youtube.mp4
    │
    └── Destination: TikTok (9:16)
        ├── Step 0: crop (9:16, center)
        ├── Step 1: watermark (logo, bottom-left)
        └── Step 2: reencode (h264, 720p, 4Mbps)
        └── OUTPUT → job_{id}/tiktok.mp4
```

Global steps are applied ONCE to produce an intermediate file. Then per-destination steps are applied to the intermediate, producing the final output per destination. This avoids re-running global steps (like normalize_audio) multiple times.

---

## 2. Step Type Reference

### 2.1 `trim`

Cut the video to a specific time range. Applied as the first global step in most pipelines.

**`params` schema:**
```json
{
  "start": 0,       // start time in seconds (integer or float)
  "end": 180        // end time in seconds (integer or float). null = keep to end
}
```

**FFmpeg command:**
```bash
ffmpeg -i input.mp4 -ss {start} -to {end} -c copy output.mp4
```

**Notes:**
- Uses `-c copy` (stream copy, no re-encode) for speed
- `-ss` before `-i` = fast seek (keyframe accurate, may have ±0.5s precision)
- If `end` is `null` or greater than video duration, trim from `start` to end of video
- If `start` is 0 and `end` is `null`, this step is a no-op (skip it)

**Use case:** "Only keep the first 3 minutes of each video for TikTok"

---

### 2.2 `crop`

Change the aspect ratio of the video by cropping (not stretching). Used to adapt 16:9 YouTube content for 9:16 TikTok/Reels.

**`params` schema:**
```json
{
  "aspect_ratio": "9:16",   // "16:9" | "9:16" | "1:1" | "4:5"
  "method": "center"        // "center" | "smart"
  // "center" = crop from center of frame
  // "smart"  = crop from center (v1 only — smart crop is a v2 feature)
}
```

**Aspect ratio → FFmpeg crop filter mapping:**

| aspect_ratio | FFmpeg crop formula                              |
|--------------|--------------------------------------------------|
| `16:9`       | `crop=iw:iw*9/16:(iw-iw)/2:(ih-iw*9/16)/2`     |
| `9:16`       | `crop=ih*9/16:ih:(iw-ih*9/16)/2:0`              |
| `1:1`        | `crop=min(iw\,ih):min(iw\,ih):(iw-min(iw\,ih))/2:(ih-min(iw\,ih))/2` |
| `4:5`        | `crop=iw:iw*5/4:(iw-iw)/2:(ih-iw*5/4)/2`        |

**FFmpeg command:**
```bash
ffmpeg -i input.mp4 -vf "crop={formula}" -c:a copy output.mp4
```

**Notes:**
- Audio is copied without re-encoding when possible
- If source is already the target ratio (±5% tolerance), this step is skipped
- Crop is applied before watermark (watermark anchors to output frame size)

---

### 2.3 `watermark`

Overlay an image (logo, channel branding) onto the video.

**`params` schema:**
```json
{
  "image_path": "/app/assets/logo.png",  // path inside processor container
  "position": "br",                       // "tl" | "tr" | "bl" | "br" | "center"
  "opacity": 0.8,                         // 0.0 to 1.0
  "scale": 0.1,                           // fraction of output video width (0.05–0.3)
  "margin": 20                            // pixels from edge
}
```

**Position → FFmpeg overlay formula:**

| position | overlay expression                              |
|----------|-------------------------------------------------|
| `tl`     | `{margin}:{margin}`                             |
| `tr`     | `main_w-overlay_w-{margin}:{margin}`            |
| `bl`     | `{margin}:main_h-overlay_h-{margin}`            |
| `br`     | `main_w-overlay_w-{margin}:main_h-overlay_h-{margin}` |
| `center` | `(main_w-overlay_w)/2:(main_h-overlay_h)/2`     |

**FFmpeg command:**
```bash
ffmpeg -i input.mp4 -i {image_path} \
  -filter_complex \
  "[1:v]scale=iw*{scale}:-1,format=rgba,colorchannelmixer=aa={opacity}[logo]; \
   [0:v][logo]overlay={position_expr}" \
  -c:a copy output.mp4
```

**Notes:**
- Image path must be accessible inside the processor container
- Assets folder is bind-mounted: `./processor/assets:/app/assets:ro`
- PNG with transparency is recommended (alpha channel respected)
- If image_path does not exist, step is SKIPPED with a warning (not a failure)

---

### 2.4 `text_overlay`

Burn text directly into the video (channel name, watermark text, subtitles-style labels).

**`params` schema:**
```json
{
  "text": "@YourChannel",
  "position": "br",           // same as watermark
  "font_size": 36,            // pixels
  "font_color": "white",      // CSS color name or hex
  "outline_color": "black",   // optional, adds readability
  "outline_width": 2,         // pixels
  "margin": 20,
  "opacity": 0.9
}
```

**FFmpeg command:**
```bash
ffmpeg -i input.mp4 -vf \
  "drawtext=text='{text}':fontsize={font_size}:fontcolor={color}@{opacity}:\
  borderw={outline_width}:bordercolor={outline_color}:\
  x={x_expr}:y={y_expr}" \
  -c:a copy output.mp4
```

---

### 2.5 `intro`

Prepend a video clip to the beginning of the video.

**`params` schema:**
```json
{
  "file_path": "/app/assets/intro.mp4"  // path inside processor container
}
```

**FFmpeg command:**
```bash
ffmpeg -i intro.mp4 -i input.mp4 \
  -filter_complex "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1" \
  output.mp4
```

**Notes:**
- Intro and source video must have the same resolution and codec, OR the concat filter will force re-encode
- Processor automatically re-encodes both to a common format if they differ
- If file_path does not exist, step is SKIPPED with a warning

---

### 2.6 `outro`

Append a video clip to the end of the video.

**`params` schema:**
```json
{
  "file_path": "/app/assets/outro.mp4"
}
```

**FFmpeg command:** Same as `intro` but with input order reversed.

---

### 2.7 `normalize_audio`

Normalize audio loudness to a target LUFS level. Essential for consistent volume across uploaded videos.

**`params` schema:**
```json
{
  "target_lufs": -14,      // EBU R128 target. -14 = YouTube standard, -16 = Spotify
  "true_peak": -1.0,       // max true peak in dBTP
  "lra": 11.0              // loudness range target (LRA)
}
```

**FFmpeg command (two-pass loudnorm):**
```bash
# Pass 1: measure
ffmpeg -i input.mp4 -af loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null /dev/null 2>&1

# Parse measured_I, measured_TP, measured_LRA from output

# Pass 2: apply
ffmpeg -i input.mp4 \
  -af "loudnorm=I=-14:TP=-1:LRA=11:measured_I={I}:measured_TP={TP}:measured_LRA={LRA}:linear=true" \
  -c:v copy output.mp4
```

**Notes:**
- Two-pass is required for accurate results
- `-c:v copy` means video stream is NOT re-encoded (audio only)
- Adds ~10–30 seconds per video depending on duration
- Apply as a global step (before destination-specific steps)

---

### 2.8 `reencode`

Re-encode video to a specific codec, resolution, and bitrate. Usually the LAST step per destination.

**`params` schema:**
```json
{
  "codec": "h264",            // "h264" | "h265" | "vp9" — selects CPU or GPU codec
  "resolution": "1080p",      // "2160p" | "1080p" | "720p" | "480p" | null (keep original)
  "crf": 23,                  // Constant Rate Factor (0-51). Lower = better quality. 23 = default
  "bitrate": null,            // Target bitrate in kbps e.g. 8000. null = use CRF mode
  "audio_codec": "aac",       // "aac" | "mp3" | "copy"
  "audio_bitrate": 192,       // kbps
  "preset": "medium"          // x264 preset: "ultrafast"|"fast"|"medium"|"slow"|"veryslow"
}
```

**Resolution → width × height mapping:**
| resolution | width | height |
|------------|-------|--------|
| `2160p`    | 3840  | 2160   |
| `1080p`    | 1920  | 1080   |
| `720p`     | 1280  | 720    |
| `480p`     | 854   | 480    |
| `null`     | (unchanged) | (unchanged) |

**Codec selection logic (processor.py):**
```python
if USE_GPU and nvenc_available():
    video_codec = "h264_nvenc"   # or "hevc_nvenc" for h265
else:
    video_codec = "libx264"      # or "libx265" for h265
```

**FFmpeg command (CRF mode, GPU):**
```bash
ffmpeg -i input.mp4 \
  -c:v h264_nvenc -cq {crf} \
  -vf scale={width}:{height} \
  -c:a aac -b:a {audio_bitrate}k \
  output.mp4
```

**FFmpeg command (CRF mode, CPU):**
```bash
ffmpeg -i input.mp4 \
  -c:v libx264 -crf {crf} -preset {preset} \
  -vf scale={width}:{height} \
  -c:a aac -b:a {audio_bitrate}k \
  output.mp4
```

---

### 2.9 `resize`

Resize without cropping (scales video, adding black bars if needed — "letterbox").

**`params` schema:**
```json
{
  "width": 1920,
  "height": 1080,
  "pad_color": "black"    // color for letterbox bars
}
```

**FFmpeg command:**
```bash
ffmpeg -i input.mp4 \
  -vf "scale={width}:{height}:force_original_aspect_ratio=decrease,\
       pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color}" \
  -c:a copy output.mp4
```

**Notes:**
- Use `crop` for social media (no black bars). Use `resize` when black bars are acceptable.
- Commonly used for Dailymotion which requires specific resolution targets

---

## 3. Processor Execution Logic

### 3.1 Step ordering rules

1. Load all processing_steps for the pipeline where `enabled=1`
2. Sort by `step_order ASC`
3. Apply global steps (destination_id IS NULL) first
4. For each destination:
   a. Start from global output (intermediate file)
   b. Apply destination-specific steps in step_order sequence
   c. Write to `/downloads/job_{id}/{platform}.mp4`

### 3.2 Intermediate files

```
/downloads/job_{id}/
  source.mp4              ← raw yt-dlp download
  intermediate.mp4        ← after global steps (trim, normalize, etc.)
  youtube.mp4             ← after YouTube-specific steps
  tiktok.mp4              ← after TikTok-specific steps
  thumbnail.jpg           ← extracted by yt-dlp during download
```

### 3.3 Error handling

- If any step fails (non-zero FFmpeg exit code):
  - Log full FFmpeg stderr
  - UPDATE jobs SET status='failed', error_message='{stderr last 500 chars}'
  - Delete partial output files
  - Do NOT continue to next destination
- If NVENC fails but CPU is available:
  - Retry same step with CPU codec automatically
  - Log: "NVENC failed, retrying with libx264"

### 3.4 Cleanup

After job reaches `done` or `partial` status and `CLEANUP_TTL_HOURS` have passed:
- Delete `source.mp4` and `intermediate.mp4` (large files, no longer needed)
- KEEP `{platform}.mp4` files for `CLEANUP_TTL_HOURS` more (in case re-upload is needed)
- KEEP `thumbnail.jpg` permanently (small file, useful for history display)

---

## 4. Platform Output Requirements

| Platform    | Aspect Ratio | Max Resolution | Max Duration | Max Size  | Codec    |
|-------------|-------------|----------------|--------------|-----------|----------|
| YouTube     | 16:9        | 4K (2160p)     | 12 hours     | 256 GB    | h264/h265|
| TikTok      | 9:16        | 1080x1920      | 10 min       | 2 GB      | h264     |
| Dailymotion | 16:9        | 1080p          | 60 min       | 4 GB      | h264     |
| Facebook    | 16:9 or 4:5 | 1080p          | 4 hours      | 10 GB     | h264     |

These limits inform the default `reencode` params for each destination type.

---

## 5. Recommended Step Sets by Pipeline Type

### Long-form YouTube → Multi-Platform
```
Global:
  0: normalize_audio {target_lufs: -14}

YouTube destination:
  0: crop {aspect_ratio: "16:9"}
  1: watermark {position: "br", scale: 0.08}
  2: reencode {codec: "h264", resolution: "1080p", crf: 23}

TikTok destination:
  0: trim {start: 0, end: 180}
  1: crop {aspect_ratio: "9:16"}
  2: watermark {position: "bl", scale: 0.12}
  3: reencode {codec: "h264", resolution: "720p", crf: 23}

Dailymotion destination:
  0: crop {aspect_ratio: "16:9"}
  1: watermark {position: "br", scale: 0.08}
  2: reencode {codec: "h264", resolution: "1080p", bitrate: 8000}
```

---

*Next: [N8N_WORKFLOW.md](N8N_WORKFLOW.md)*
