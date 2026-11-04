import os
from pathlib import Path

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://acquireos:acquireos@localhost:5432/acquireos"
)
# Where the built web front end lives. In Docker it is copied to /app/web.
WEB_DIST = Path(os.environ.get("WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/acquireos-uploads"))
# Single-user for now. Every user-owned row still carries a user_id so a
# hosted, multi-user version needs no data migration.
DEFAULT_USER_ID = 1

# Optional HTTP basic auth. Leave APP_PASSWORD empty on a trusted LAN.
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
