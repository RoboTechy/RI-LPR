# RI-LPR relay service (Raspberry Pi)

Switches each line's traffic light between red and green via a relay
board, controlled over HTTP from the backend. Runs directly on a
Raspberry Pi 4B (8GB) on the plant network - **not** a container, not
part of `backend/docker-compose.yml`. Keep it that way: GPIO access
from inside Docker needs extra privileged flags/device mounts for no
real benefit here, and this one small Python process is simpler to
reason about running straight on the Pi's own OS.

## Wiring (as discussed)

Per line, one SPDT relay (one NO contact, one NC contact):

- **NC** (normally closed) → red bulb. De-energized = NC closed = red.
  This is the safe idle state - what the light shows on boot or if the
  Pi loses power.
- **NO** (normally open) → green bulb. Energized = NO closed = green.
- **COM** → the light's shared/power line.

Relay coils are 5V, low-level-trigger (pull the relay's IN pin LOW to
energize it). The Pi's GPIO is 3.3V logic, so each relay channel's IN
pin goes through a 3.3V→5V level converter before reaching the relay
board, per your own setup. `config.py`'s `RELAY_ACTIVE_LOW = True`
matches this; if a given channel ends up inverted in practice, flip it
to `False` and re-test that one line before trusting the rest.

## Two ways a light turns green - and two different ways it turns red

- **"auto"** - the backend sent this when an operator saved a permit
  for a truck on that line. No timer at all here - stays green until
  the backend's worker explicitly decides the truck has left (it
  watches the camera; see `backend/worker/camera_worker.py`) and calls
  `POST /light/{line}/red-if-auto`.
- **"manual"** - someone clicked "سبز کردن" in the admin panel.
  Auto-reverts to red after a fixed number of seconds the backend sends
  along (admin-editable from the cameras page) - regardless of what any
  camera sees.

`POST /light/{line}/red` is an unconditional manual override (the
admin panel's "قرمز کردن" button); `red-if-auto` is a no-op unless the
light is currently green for the "auto" reason, so the worker's own
departure detection can never cut a manual test short.

**Before wiring all 6 lines**: wire just line 1, run through the smoke
test below, and confirm red is really the idle state and green is
really what you get from `POST /light/1/green` - cheaper to catch a
wiring or polarity mistake on one line than on six.

## Setup

```bash
# on the Pi, with this repo cloned (or just this folder copied over)
cd pi-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The venv is **not optional** - `ri-lpr-relay.service` runs the script with
`.venv/bin/python3` directly, so the packages above must end up inside
that venv (not installed system-wide) or the systemd service will fail
with `ModuleNotFoundError` even if your manual test run worked.

Edit `config.py`:
- `LINE_TO_PIN` - which BCM GPIO pin drives which line's relay. The
  defaults are just safe, unreserved pins on a Pi 4B - they say nothing
  about your actual wiring. Set these to match reality.
- `RELAY_ACTIVE_LOW` - should already be right (see above) unless you
  find otherwise while testing line 1.
- `AUTO_REVERT_SECONDS` - how long green stays before reverting to red
  on its own (default 20s).

Set a real API key (shared with the backend - `PI_RELAY_API_KEY` in
`backend/.env` must match this exactly):

```bash
cp .env.example .env
# edit .env: set RELAY_API_KEY to a real value
```

## Running it

Manually, for the initial wiring test:

```bash
source .venv/bin/activate
export RELAY_API_KEY=$(grep RELAY_API_KEY .env | cut -d= -f2)
python3 relay_service.py
```

From another machine on the same network:

```bash
curl http://<pi-ip>:8080/health                                       # no auth needed
curl -X POST -H "X-API-Key: <RELAY_API_KEY>" "http://<pi-ip>:8080/light/1/green?mode=manual&seconds=5"
curl -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/lights        # {"1": "green", "2": "red", ...}
# wait 5s, then /lights should show line 1 back to "red" on its own

# "auto" mode (what a saved permit actually triggers) has NO timer -
# confirm it stays green until you explicitly clear it:
curl -X POST -H "X-API-Key: <RELAY_API_KEY>" "http://<pi-ip>:8080/light/1/green?mode=auto"
sleep 10 && curl -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/lights   # line 1 should still be green
curl -X POST -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/light/1/red-if-auto
```

Once that's confirmed, install it as a systemd service so it survives
reboots and restarts itself if it crashes:

```bash
sudo cp ri-lpr-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ri-lpr-relay
sudo systemctl status ri-lpr-relay    # should show "active (running)"
```

(The unit file assumes this folder lives at `/home/pi/ri-lpr/pi-relay-service`
and runs as the `pi` user - edit the paths/`User=` in
`ri-lpr-relay.service` first if that doesn't match your setup.)

## Wiring this into the backend

In `backend/.env` on the server:

```
PI_RELAY_SERVICE_URL=http://<the-pi's-static-ip>:8080
PI_RELAY_API_KEY=<same value as RELAY_API_KEY above>
```

Then `docker compose restart api` (no rebuild needed - these are just
environment variables). After that:

- Saving a permit in the extension automatically turns that line's
  light green and keeps it green for exactly as long as the worker's
  camera still sees that truck - no fixed timer for this path.
- The admin panel's دوربین‌ها page shows each line's current light
  color and has manual "سبز کردن"/"قرمز کردن" buttons - available to
  اوپراتور accounts too, not just مدیر, since this is routine
  day-to-day use, not service configuration. A manual green always
  reverts after a fixed, مدیر-editable duration from that same page,
  regardless of what any camera sees.

If the Pi is unreachable, nothing else breaks - saving a permit and the
admin panel both treat the relay service as best-effort (see
`backend/app/relay_client.py`); the light status just shows as
"نامشخص" (unknown) instead of red/green.

## A network gotcha to watch for

If the Pi and the backend server end up on different subnets/VLANs
with no route between them, this won't work even though both halves
are individually fine - the same class of problem as the camera-VLAN/
Docker-bridge collision hit earlier in this project. Confirm with a
plain `ping <pi-ip>` **from the backend server itself** (not from your
laptop) before assuming the integration is broken.
