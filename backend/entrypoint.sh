#!/bin/sh
# Make sure the data folder is writable by the app user (uid 1000), then run
# the command as that user. Docker creates bind-mounted host folders such as
# /opt/acquireos/data owned by root, which the app user could not write to.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/companies-house 2>/dev/null || true
  chown 1000:1000 /data /data/companies-house 2>/dev/null || true
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=1000 --regid=1000 --init-groups -- "$@"
  fi
  echo "setpriv not found; running as root" >&2
fi
exec "$@"
