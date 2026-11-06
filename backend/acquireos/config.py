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

# Token for the MCP endpoint (/mcp) and for scripts calling the REST API.
# Send it as "Authorization: Bearer <token>". Strongly recommended; required
# for /mcp whenever APP_PASSWORD is set.
API_TOKEN = os.environ.get("API_TOKEN", "")
# Optional free Companies House API key (developer.company-information.service.gov.uk):
# unlocks charge details (who holds each loan) and filing history (share allotments).
CH_API_KEY = os.environ.get("CH_API_KEY", "").strip()
if CH_API_KEY.upper().startswith("PASTE"):  # the stack file's placeholder
    CH_API_KEY = ""
# Optional Companies House Streaming API key (a separate key type, same
# developer account): live change events for every company.
CH_STREAM_KEY = os.environ.get("CH_STREAM_KEY", "").strip()
if CH_STREAM_KEY.upper().startswith("PASTE"):
    CH_STREAM_KEY = ""
# Map tiles. The default is OpenStreetMap's own server, which is fine for
# personal use; a hosted product should use a commercial tile provider.
MAP_TILE_URL = os.environ.get("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
MAP_ATTRIBUTION = os.environ.get("MAP_ATTRIBUTION", "© OpenStreetMap contributors")
