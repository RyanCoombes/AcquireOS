# AcquireOS: one image with the API and the built web front end.
# Builds for both amd64 and arm64 (Raspberry Pi 4/5 on a 64-bit OS).

FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WEB_DIST=/app/web UPLOAD_DIR=/tmp/acquireos-uploads
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/acquireos ./backend/acquireos
RUN pip install --no-cache-dir ./backend \
 && useradd --create-home --uid 1000 app \
 && mkdir -p /data && chown app /data
COPY --from=web /web/dist /app/web
COPY backend/entrypoint.sh /usr/local/bin/acquireos-entrypoint
COPY backend/healthcheck.sh /usr/local/bin/acquireos-health
RUN chmod 755 /usr/local/bin/acquireos-entrypoint /usr/local/bin/acquireos-health
# Starts as root only to fix the data folder's ownership, then runs as "app".
ENTRYPOINT ["acquireos-entrypoint"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
  CMD ["acquireos-health"]
CMD ["uvicorn", "acquireos.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
