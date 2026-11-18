"""
Runs ON the Raspberry Pi itself (Raspberry Pi OS) - a separate physical
device on the plant network, not a container in the main backend's
docker-compose. Controls each line's traffic light: HTTP in, GPIO out.

Each line has one GPIO pin (config.LINE_TO_PIN):
    1 (HIGH) = green light        0 (LOW) = red light
Red is the idle state - the pins start LOW. How long green lasts is sent
by the backend with every request (?seconds=N, set in the admin panel):
N > 0 - back to red by itself after N seconds (restarted if turned green
again meanwhile); N = 0 - no timer, stays green until /red (manual mode).
If the request has no ?seconds=, config.GREEN_SECONDS (30 s) is used.

Setup: see README.md in this folder.

API (every endpoint but /health needs header X-API-Key: <config.API_KEY>):
    POST /light/{line_number}/green[?seconds=N]
                                     - pin to 1; back to 0 after N seconds
                                       (N=0: stays green; omitted:
                                       config.GREEN_SECONDS)
    POST /light/{line_number}/red    - pin to 0 immediately
    POST /light/{line_number}/red-if-auto
                                     - does nothing (kept so the backend's
                                       "truck left" call still works); the
                                       light follows its own timer
    GET  /light/{line_number}        - {"line_number": n, "color": "red"|"green"}
    GET  /lights                     - {"<line_number>": "red"|"green", ...}
    GET  /health                     - no auth; quick reachability check
"""
import threading
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from gpiozero import OutputDevice

import config

app = FastAPI(title="RI-LPR relay service")


class Light:
    """One line's GPIO pin as a red/green state with its own revert timer."""

    def __init__(self, pin: int):
        # on() = pin HIGH = 1 = green; off() = pin LOW = 0 = red
        self.device = OutputDevice(pin, active_high=config.GREEN_IS_HIGH, initial_value=False)
        self.color = "red"
        self._revert_timer = None
        self._lock = threading.Lock()

    def set_green(self, seconds: Optional[float] = None):
        """seconds: None -> config.GREEN_SECONDS; 0 -> stay green until
        set_red(); otherwise that many seconds."""
        duration = config.GREEN_SECONDS if seconds is None else seconds
        with self._lock:
            self._cancel_timer_locked()
            self.device.on()
            self.color = "green"
            if duration > 0:
                self._revert_timer = threading.Timer(duration, self.set_red)
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
def light_green(
    line_number: int,
    seconds: Optional[float] = None,
    mode: Optional[str] = None,  # old backends sent this; ignored
    _auth: None = Depends(check_api_key),
):
    if seconds is not None and (seconds < 0 or seconds > 86400):
        raise HTTPException(status_code=400, detail="seconds must be between 0 and 86400")
    get_light(line_number).set_green(seconds)
    return {"line_number": line_number, "color": "green",
            "seconds": config.GREEN_SECONDS if seconds is None else seconds}


@app.post("/light/{line_number}/red")
def light_red(line_number: int, _auth: None = Depends(check_api_key)):
    get_light(line_number).set_red()
    return {"line_number": line_number, "color": "red"}


@app.post("/light/{line_number}/red-if-auto")
def light_red_if_auto(line_number: int, _auth: None = Depends(check_api_key)):
    # Deliberately a no-op: a light follows its own timer (or the operator).
    return {"line_number": line_number, "color": get_light(line_number).color}


@app.get("/light/{line_number}")
def light_status(line_number: int, _auth: None = Depends(check_api_key)):
    return {"line_number": line_number, "color": get_light(line_number).color}


@app.get("/lights")
def all_lights(_auth: None = Depends(check_api_key)):
    return {str(line): light.color for line, light in lights.items()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
