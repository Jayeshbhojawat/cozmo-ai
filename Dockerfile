# One image runs every tier on a clean machine (incl. Apple Silicon Macs via
# Docker Desktop's x86 emulation: the Spectacular AI SDK is x86_64/Windows only).
FROM --platform=linux/amd64 python:3.11-slim
# HTTPS package sources (found in the Mac rehearsal: a network that altered
# plain-HTTP downloads -> apt "Hash Sum mismatch"). ffmpeg is required by the
# Spectacular AI SDK to decode data.mov (removing it broke the pose step:
# "SpectacularAI error: `ffmpeg` must be installed"); libglib for OpenCV.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
 && apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends ffmpeg libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-video.txt ./
RUN pip install --no-cache-dir --retries 5 -r requirements.txt -r requirements-video.txt
COPY . .
# The pose step (cli.run poses) needs no model; fetch is best-effort so a
# flaky network cannot break the image build.
RUN python scripts/fetch_models.py || echo "depth model not fetched (only needed for full runs inside Docker)"
ENTRYPOINT ["python", "-m", "cli.run"]
