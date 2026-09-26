# SESSION TASK — Step 4.3: GPU / NVENC Support

## Your job in this session
Add optional GPU (NVIDIA NVENC) support to the processor. GPU is used when available, CPU fallback when not.

## Read these files first:
1. `docs/PROCESSING_PIPELINE.md` — section: "GPU Encoding"
2. `docs/CONTAINER_SPECS.md` — section: "GPU in Docker"
3. `processor/processor.py` — the `run_ffmpeg()` function you will modify

## Hard constraints:
- GPU must be **optional** — processor must work without GPU (CPU h264 fallback)
- Detection: check for NVENC at startup by running `ffmpeg -encoders | grep nvenc`
- If NVENC available: use `-c:v h264_nvenc` instead of `-c:v libx264`
- The GPU setting must be a module-level constant, detected once at startup
- Do NOT install CUDA in the Docker image — GPU access comes from Docker `--gpus all` flag

## Changes to make:

### In `processor/processor.py`, add at module level:
```python
def detect_gpu():
    result = subprocess.run(
        ['ffmpeg', '-encoders'],
        capture_output=True, text=True
    )
    return 'nvenc' in result.stdout

USE_GPU = detect_gpu()
VIDEO_CODEC = 'h264_nvenc' if USE_GPU else 'libx264'
print(f"GPU encoding: {'ENABLED (h264_nvenc)' if USE_GPU else 'DISABLED (libx264 fallback)'}")
```

### Update `run_ffmpeg()`:
Replace any hardcoded `-c:v libx264` with `-c:v {VIDEO_CODEC}`.

### Update `docker-compose.yml` processor service:
Add the GPU section (only applies if host has NVIDIA GPU):
```yaml
processor:
  # ... existing config ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

Note in a comment that this section can be removed if no GPU is available.

## Test / pass criteria:

### Without GPU (most common):
```bash
python processor/processor.py
```
Output must include: `GPU encoding: DISABLED (libx264 fallback)`

### With GPU (on the Lenovo C30 with GTX 1080):
```bash
docker compose up processor
```
Container logs must include: `GPU encoding: ENABLED (h264_nvenc)`

## When done:
- Show the GPU detection code block
- Show the updated `run_ffmpeg()` function
- Show the docker-compose.yml GPU section
- Do NOT build anything else in this session
