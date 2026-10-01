# One image runs every tier on a clean machine (incl. Apple Silicon Macs via
# Docker Desktop's x86 emulation: the Spectacular AI SDK is x86_64/Windows only).
FROM --platform=linux/amd64 python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-video.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-video.txt
COPY . .
RUN python scripts/fetch_models.py
ENTRYPOINT ["python", "-m", "cli.run"]
