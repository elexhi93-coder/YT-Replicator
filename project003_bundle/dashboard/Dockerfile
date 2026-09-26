FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
        flask \
        google-auth \
        google-auth-oauthlib \
        google-api-python-client \
        yt-dlp \
        Pillow

COPY app.py .
COPY models.py .
COPY uploader.py .
COPY oauth_youtube.py .
COPY sources.py .
COPY ai_enricher.py .
COPY download_profile.py .
COPY router.py .
COPY projects.py .
COPY youtube_channels.py .
COPY templates/ templates/

EXPOSE 8080

CMD ["python", "app.py"]
