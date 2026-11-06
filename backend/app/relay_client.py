"""
Talks to the Raspberry Pi relay-control service (../pi-relay-service/)
that switches each line's physical traffic light between red and
green. That service is a separate device on the plant network, not a
container here - see PI_RELAY_SERVICE_URL in config.py.

Every call here is best-effort: the light is a physical convenience
signal for the driver, not a system of record, so a Pi/network hiccup
must never block saving a permit or break the admin panel. Every
function below swallows connection errors and returns a value the
caller can act on (False / {}) instead of raising.
"""
import logging

import httpx

from .config import PI_RELAY_API_KEY, PI_RELAY_SERVICE_URL

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


def set_light(line_number: int, color: str) -> bool:
    """color: "green" or "red". Returns True if the Pi acknowledged it."""
    try:
        resp = httpx.post(
            f"{PI_RELAY_SERVICE_URL}/light/{line_number}/{color}",
            headers={"X-API-Key": PI_RELAY_API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPError:
        log.warning("could not set line %s's light to %s (relay service unreachable)", line_number, color)
        return False


def get_all_lights() -> dict:
    """Returns {line_number: "red" | "green"} for every line the Pi
    knows about, or {} if it couldn't be reached - callers should treat
    a missing line_number as "unknown", not assume red."""
    try:
        resp = httpx.get(
            f"{PI_RELAY_SERVICE_URL}/lights",
            headers={"X-API-Key": PI_RELAY_API_KEY},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return {int(line): color for line, color in resp.json().items()}
    except httpx.HTTPError:
        log.warning("could not reach the relay service for light statuses")
        return {}
