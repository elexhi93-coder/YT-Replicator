# project003 processor — runs FFmpeg pipeline steps on downloaded videos
FROM python:3.11-slim

# ffmpeg + minimal tooling. CUDA/NVENC drivers come from the host via --gpus.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY processor.py .

# Non-root runtime user
RUN useradd -m processor \
 && mkdir -p /data /downloads \
 && chown -R processor:processor /app /data /downloads
USER processor

CMD ["python", "processor.py"]
