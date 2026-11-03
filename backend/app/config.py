import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://ri_lpr:ri_lpr@db:5432/ri_lpr"
)

# Shared secret the Chrome extension sends on every call (X-API-Key header).
# Any operator computer with this key can read active plates and log
# permits - there is no per-operator login, by design (see project chat:
# any operator may handle any line's truck).
EXTENSION_API_KEY = os.environ.get("EXTENSION_API_KEY", "change-me-extension-key")

# Signs the admin panel's session cookie - set a real random value in
# production via the .env file.
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "change-me-session-secret")

# Created automatically on first startup if no admin user exists yet.
DEFAULT_ADMIN_USERNAME = os.environ.get("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "change-me-now")

# A plate stays "active" (shown to operators) for this many minutes after
# detection, unless an operator already used it on a saved permit.
ACTIVE_PLATE_WINDOW_MINUTES = int(os.environ.get("ACTIVE_PLATE_WINDOW_MINUTES", "20"))

# Once a plate has been used on a saved permit, don't show that same
# plate text again (same camera) for this many minutes - a truck that's
# still sitting at the same line being loaded/unloaded would otherwise
# get re-detected and show back up in the list right after being saved.
PLATE_SUPPRESS_AFTER_SAVE_MINUTES = int(os.environ.get("PLATE_SUPPRESS_AFTER_SAVE_MINUTES", "60"))

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
(MEDIA_ROOT / "plates").mkdir(exist_ok=True)
(MEDIA_ROOT / "vehicles").mkdir(exist_ok=True)

# How often (seconds) a worker thread grabs a frame from its camera.
WORKER_POLL_INTERVAL_SECONDS = float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "3"))

# A truck is considered "the same one still sitting there" (no new
# DetectedPlate row - its existing row's timestamp is just refreshed
# instead) when a later read's vehicle box overlaps this much (IoU,
# 0..1) with the last read's - matched by position, not by plate text,
# since OCR can misread a single character between polls.
WORKER_IOU_SAME_TRUCK_THRESHOLD = float(os.environ.get("WORKER_IOU_SAME_TRUCK_THRESHOLD", "0.6"))

# If no plate is successfully read on a camera for longer than this
# (seconds), whatever truck was last seen there is assumed to have left -
# the next successful read starts a fresh "same truck?" comparison
# instead of matching against that stale position.
WORKER_PRESENCE_GAP_SECONDS = float(os.environ.get("WORKER_PRESENCE_GAP_SECONDS", "30"))

# Where the worker container's internal test API (test_server.py) is
# reachable from the api container, over the Compose network - backs
# the admin panel's per-camera "تست ارتباط" button.
WORKER_INTERNAL_URL = os.environ.get("WORKER_INTERNAL_URL", "http://worker:9000")
