# syntax=docker/dockerfile:1

# --- 1) Sestavení webového rozhraní -------------------------------------------
FROM node:22.23.4-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2) Běhové prostředí aplikace --------------------------------------------
FROM python:3.12.15-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ELENVAR_DATA_DIR=/data \
    ELENVAR_STATIC_DIR=/app/static

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 elenvar \
 && useradd --system --uid 10001 --gid elenvar --home-dir /app --shell /usr/sbin/nologin elenvar

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --root-user-action=ignore -r requirements.txt
COPY backend/app ./app
COPY VERSION ./VERSION
COPY --from=frontend /build/dist ./static
RUN mkdir -p /data && chown elenvar:elenvar /data && chmod 0700 /data

USER elenvar
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
# Jeden worker: monitoring a limity běží v procesu aplikace.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", "--no-access-log"]
