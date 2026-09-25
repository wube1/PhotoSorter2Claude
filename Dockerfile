# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------- web ui build
FROM node:22-alpine AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY VERSION /src/VERSION
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------- runtime
FROM python:3.13-slim AS runtime

ARG VERSION=dev
LABEL org.opencontainers.image.title="PhotoSorter2Claude" \
      org.opencontainers.image.description="Semi-automatic photo sorter: EXIF date + GPS place names, live web UI" \
      org.opencontainers.image.source="https://github.com/wube1/PhotoSorter2Claude" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2 \
    TZ=Europe/Warsaw \
    PHOTOSORTER_CONFIG=/config/config.yaml \
    PHOTOSORTER_DATA=/data \
    PHOTOSORTER_LOGS=/logs \
    PHOTOSORTER_INBOX=/photos/inbox \
    PHOTOSORTER_SORTED=/photos/sorted

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-compile -r requirements.txt

COPY backend/app ./app
COPY VERSION ./app/VERSION
COPY --from=ui /src/frontend/dist ./app/static

RUN mkdir -p /config /data /logs /photos/inbox /photos/sorted \
 && chown 1000:1000 /data /logs \
 && python -m compileall -q /app/app

USER 1000:1000
EXPOSE 8080
VOLUME ["/data", "/logs"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)" || exit 1

CMD ["python", "-m", "app.main"]
