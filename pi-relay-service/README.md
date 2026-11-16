# RI-LPR relay service (Raspberry Pi)

Switches each line's traffic light between red and green, controlled over
HTTP from the backend. Runs directly on a Raspberry Pi (Raspberry Pi OS) on
the plant network - **not** a container, not part of
`backend/docker-compose.yml`: GPIO access from inside Docker needs extra
privileged flags for no real benefit, and one small Python process is
simpler to run on the Pi's own OS.

## How it works

Each line has one GPIO pin:

- pin **HIGH = 1 -> green**
- pin **LOW = 0 -> red** (the idle state; pins start LOW at boot)

Whenever a light is turned green - by a saved permit or by the admin
panel's green button - it stays green for **`GREEN_SECONDS`** (30 s) and
then goes back to red by itself. A new green while it is still green
restarts the time. `POST /light/{line}/red` turns it red at once. The
`seconds` value the backend sends and the backend's "truck left" call are
accepted but ignored: `config.py` alone decides, so the time is changed in
one place only.

## Pins (BCM numbers, edit `LINE_TO_PIN` in `config.py` to change)

| Line | BCM GPIO | Physical header pin |
|------|----------|---------------------|
| 1 | 17 | 11 |
| 2 | 27 | 13 |
| 3 | 22 | 15 |
| 4 | 23 | 16 |
| 5 | 24 | 18 |
| 6 | 25 | 22 |

Connect each pin to that line's light driver input and a GND pin (e.g.
physical 6, 9 or 14) to the driver's ground. GPIO pins give **3.3 V and
only a few mA** - drive a relay/driver board or transistor, never a lamp
directly. If your driver switches the other way round (0 = green), set
`GREEN_IS_HIGH = False` in `config.py`.

## Setup

```bash
# on the Pi, with this repo cloned (or just this folder copied over)
cd pi-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then edit .env: set RELAY_API_KEY to a real value
```

The venv is **not optional** - the systemd service runs
`.venv/bin/python3`.

Edit `config.py`:
- `GREEN_SECONDS` - how long green stays on (default 30). Can also be set
  as `RELAY_GREEN_SECONDS` in `.env`.
- `LINE_TO_PIN` - the pins above.
- `GREEN_IS_HIGH` - leave `True` for 1 = green.

`RELAY_API_KEY` must equal `PI_RELAY_API_KEY` in the backend's `.env`.

## Test it by hand first

```bash
source .venv/bin/activate
export $(grep RELAY_API_KEY .env)
python3 relay_service.py
```

From another machine (or a second terminal):

```bash
curl http://<pi-ip>:8080/health                                       # no key needed
curl -X POST -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/light/1/green
curl -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/lights        # line 1 green
# measure pin 11 (BCM 17): 3.3 V while green; after 30 s it is 0 V and /lights shows red
curl -X POST -H "X-API-Key: <RELAY_API_KEY>" http://<pi-ip>:8080/light/1/red   # red at once
```

Do line 1 alone before connecting the other five.

## Run it as a service (starts at every boot, restarts if it crashes)

```bash
sed -i "s#REPLACE_ME_DIR#$(pwd)#g; s#REPLACE_ME_USER#$(whoami)#g" ri-lpr-relay.service
cat ri-lpr-relay.service    # check: no REPLACE_ME left
sudo cp ri-lpr-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ri-lpr-relay
sudo systemctl status ri-lpr-relay      # "active (running)"
```

After changing `GREEN_SECONDS`: `sudo systemctl restart ri-lpr-relay`.
Logs: `journalctl -u ri-lpr-relay -f`. If it fails with a GPIO permission
error, the user must be in the `gpio` group: `sudo usermod -aG gpio $USER`
and reboot.

## Wiring this into the backend

In `backend/.env` on the server:

```
PI_RELAY_SERVICE_URL=http://<the-pi's-static-ip>:8080
PI_RELAY_API_KEY=<same value as RELAY_API_KEY above>
```

Then `docker compose restart api` (no rebuild needed - these are just
environment variables). After that:

- Saving a permit in the extension turns that line's light green; so
  does the admin panel's "سبز کردن" button. Either way it stays green for
  `GREEN_SECONDS` (this folder's `config.py`) and goes back to red by
  itself. The "green duration" setting on the admin panel's دوربین‌ها
  page no longer has any effect, and neither does the worker's "truck
  left" signal - the Pi's own timer decides.
- "قرمز کردن" turns the light red immediately. The page shows each
  line's current color; operators may use both buttons.

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
