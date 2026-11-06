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

API (every endpoint but /health needs header X-API-Key: <config.API_KEY>):
    POST /light/{line_number}/green  - energize the relay; auto-reverts
                                        to red after AUTO_REVERT_SECONDS
                                        on its own, even with no further
                                        requests
    POST /light/{line_number}/red    - de-energize immediately, and
                                        cancels any pending auto-revert
    GET  /light/{line_number}        - {"line_number": n, "color": "red"|"green"}
    GET  /lights                     - {"<line_number>": "red"|"green", ...}
                                        for every line in LINE_TO_PIN
    GET  /health                     - no auth; for a quick reachability check
"""
import threading

from fastapi import Depends, FastAPI, Header, HTTPException
from gpiozero import OutputDevice

import config

app = FastAPI(title="RI-LPR relay service")


class Light:
    """One line's relay - wraps a single GPIO pin as a red/green state
    with its own auto-revert timer."""

    def __init__(self, pin: int):
        self.device = OutputDevice(pin, active_high=not config.RELAY_ACTIVE_LOW, initial_value=False)
        self.color = "red"
        self._revert_timer = None
        self._lock = threading.Lock()

    def set_green(self):
        with self._lock:
            self._cancel_timer_locked()
            self.device.on()
            self.color = "green"
            self._revert_timer = threading.Timer(config.AUTO_REVERT_SECONDS, self.set_red)
            self._revert_timer.daemon = True
            self._revert_timer.start()

    def set_red(self):
        with self._lock:
            self._cancel_timer_locked()
            self.device.off()
            self.color = "red"

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
def light_green(line_number: int, _auth: None = Depends(check_api_key)):
    get_light(line_number).set_green()
    return {"line_number": line_number, "color": "green"}


@app.post("/light/{line_number}/red")
def light_red(line_number: int, _auth: None = Depends(check_api_key)):
    get_light(line_number).set_red()
    return {"line_number": line_number, "color": "red"}


@app.get("/light/{line_number}")
def light_status(line_number: int, _auth: None = Depends(check_api_key)):
    return {"line_number": line_number, "color": get_light(line_number).color}


@app.get("/lights")
def all_lights(_auth: None = Depends(check_api_key)):
    return {str(line): light.color for line, light in lights.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
