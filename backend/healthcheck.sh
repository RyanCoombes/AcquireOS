#!/bin/sh
# Docker health check. The scheduler container runs no web server: it is
# healthy while its process is running. The web app must answer /api/health.
if tr '\0' ' ' < /proc/1/cmdline 2>/dev/null | grep -q "scheduler"; then
  exit 0
fi
exec python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"
