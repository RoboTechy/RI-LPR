import os

# Must match PI_RELAY_API_KEY in the backend's .env.
API_KEY = os.environ.get("RELAY_API_KEY", "change-me-relay-key")

PORT = int(os.environ.get("RELAY_PORT", "8080"))
HOST = os.environ.get("RELAY_HOST", "0.0.0.0")

# Low-level-trigger relay board: driving the GPIO pin LOW energizes the
# relay (COM switches to NO - green), driving it HIGH de-energizes it
# (COM switches to NC - red, the safe/idle default this starts in).
# Set to False if your board/level-converter combo works the other way
# around (test with one line before wiring the rest).
RELAY_ACTIVE_LOW = True

# Fallback duration (seconds) for a "manual" green trigger that didn't
# specify its own ?seconds= - normally the backend always sends one
# (admin-editable from the cameras page), so this mostly only matters
# for a manual curl/test call. Has no effect on an "auto" trigger (a
# saved permit) - that one has no timer at all, see relay_service.py's
# module docstring.
AUTO_REVERT_SECONDS = float(os.environ.get("RELAY_AUTO_REVERT_SECONDS", "20"))

# Which BCM GPIO pin drives which line's relay - EDIT THIS to match your
# actual wiring. These defaults just avoid commonly-reserved pins on a
# Pi 4B (I2C: 2,3 - SPI: 7,8,9,10,11 - UART: 14,15) so they're a safe
# starting point, not a claim about your specific relay board's layout.
LINE_TO_PIN = {
    1: 5,
    2: 6,
    3: 13,
    4: 16,
    5: 19,
    6: 20,
}
