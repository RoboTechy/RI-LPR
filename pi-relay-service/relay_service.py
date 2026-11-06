"""
Runs ON the Raspberry Pi itself - a separate physical device on the
plant network, not a container in the main backend's docker-compose.
Controls each line's traffic light via a relay board: HTTP in, GPIO out.

Wiring: each line has one SPDT relay - its NC (normally closed) contact
wired to the light's RED bulb, its NO (normally open) contact wired to
GREEN, COM to the light's shared/power line. De-energized (idle) -> NC
closed -> red. Energized -> NO closed -> green. The relay board is
low-level-trigger (its IN pin must be pulled LOW to energize) with a 5V
coil, driven through a 3.3V->5V level converter from the Pi's GPIO -
see config.py's RELAY_ACTIVE_LOW if your board inverts this.

Setup: see README.md in this folder.

A light is always green for one of two reasons, which behave
differently on purpose (per the project's own requirement):

  "auto"   - the backend turned it green because an operator saved a
             permit for a truck on that line. Stays green for exactly
             as long as that truck is still there - the worker
             (backend/worker/camera_worker.py) explicitly calls
             red-if-auto the moment its own camera loop decides the
             truck has left. No timer here at all for this case.
  "manual" - someone clicked "سبز کردن" in the admin panel. Reverts to
             red after a fixed, admin-configurable duration
             (backend/app/models.py's AppSetting) passed in as
             ?seconds=, regardless of what any camera sees.

API (every endpoint but /health needs header X-API-Key: <config.API_KEY>):
    POST /light/{line_number}/green?mode=auto
                                      - energize the relay, no timer -
                                        stays green until /red or
                                        /red-if-auto turns it off
    POST /light/{line_number}/green?mode=manual&seconds=<N>
                                      - energize the relay, auto-reverts
                                        to red after <N> seconds (falls
                                        back to config.AUTO_REVERT_SECONDS
                                        if seconds is omitted)
    POST /light/{line_number}/red    - de-energize immediately,
                                        unconditionally (manual override)
    POST /light/{line_number}/red-if-auto
                                      - de-energize only if currently
                                        green because of mode=auto - a
                                        no-op otherwise, so it never
                                        cuts a manual test short
    GET  /light/{line_number}        - {"line_number": n, "color": "red"|"green"}
    GET  /lights                     - {"<line_number>": "red"|"green", ...}
                                        for every line in LINE_TO_PIN
    GET  /health                     - no auth; for a quick reachability check
"""
import threading
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from gpiozero import OutputDevice

import config

app = FastAPI(title="RI-LPR relay service")


class Light:
    """One line's relay - wraps a single GPIO pin as a red/green state,
    remembering *why* it's green (see module docstring) and its own
    pending auto-revert timer, if any."""

    def __init__(self, pin: int):
        self.device = OutputDevice(pin, active_high=not config.RELAY_ACTIVE_LOW, initial_value=False)
        self.color = "red"
        self.mode: Optional[str] = None  # "auto" | "manual" | None (while red)
        self._revert_timer = None
        self._lock = threading.Lock()

    def set_green(self, mode: str, seconds: Optional[float] = None):
        with self._lock:
            self._cancel_timer_locked()
            self.device.on()
            self.color = "green"
            self.mode = mode
            if mode == "manual":
                duration = seconds if seconds is not None else config.AUTO_REVERT_SECONDS
                self._revert_timer = threading.Timer(duration, self._revert_locked_wrapper)
                self._revert_timer.daemon = True
                self._revert_timer.start()
            # mode == "auto": no timer - stays green until /red or
            # /red-if-auto is called explicitly.

    def _revert_locked_wrapper(self):
        with self._lock:
            self._set_red_locked()

    def set_red(self):
        with self._lock:
            self._set_red_locked()

    def set_red_if_auto(self):
        with self._lock:
            if self.mode == "auto":
                self._set_red_locked()

    def _set_red_locked(self):
        self._cancel_timer_locked()
        self.device.off()
        self.color = "red"
        self.mode = None

    def _cancel_timer_locked(self):
        if self._revert_timer is not None:
            self._revert_timer.cancel()
            self._revert_timer = None


lights: dict[int, Light] = {line: Light(pin) for line, pin in config.LINE_TO_PIN.items()}


def check_api_key(x_api_key: str = Header(None)):
    if x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


def get_light(line_number: int) -> Light:
    light = lights.get(line_number)
    if light is None:
        raise HTTPException(
            status_code=404,
            detail=f"no relay configured for line {line_number} - check LINE_TO_PIN in config.py",
        )
    return light


@app.get("/health")
def health():
    return {"status": "ok", "lines": sorted(lights.keys())}


@app.post("/light/{line_number}/green")
def light_green(
    line_number: int,
    mode: str = "manual",
    seconds: Optional[float] = None,
    _auth: None = Depends(check_api_key),
):
    if mode not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="mode must be 'auto' or 'manual'")
    get_light(line_number).set_green(mode, seconds)
    return {"line_number": line_number, "color": "green", "mode": mode}


@app.post("/light/{line_number}/red")
def light_red(line_number: int, _auth: None = Depends(check_api_key)):
    get_light(line_number).set_red()
    return {"line_number": line_number, "color": "red"}


@app.post("/light/{line_number}/red-if-auto")
def light_red_if_auto(line_number: int, _auth: None = Depends(check_api_key)):
    light = get_light(line_number)
    light.set_red_if_auto()
    return {"line_number": line_number, "color": light.color}


@app.get("/light/{line_number}")
def light_status(line_number: int, _auth: None = Depends(check_api_key)):
    return {"line_number": line_number, "color": get_light(line_number).color}


@app.get("/lights")
def all_lights(_auth: None = Depends(check_api_key)):
    return {str(line): light.color for line, light in lights.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
