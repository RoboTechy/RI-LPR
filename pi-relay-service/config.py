import os

# Must match PI_RELAY_API_KEY in the backend's .env.
API_KEY = os.environ.get("RELAY_API_KEY", "change-me-relay-key")

PORT = int(os.environ.get("RELAY_PORT", "8080"))
HOST = os.environ.get("RELAY_HOST", "0.0.0.0")

# How long a light stays GREEN, in seconds, every time it is turned green
# (a saved permit, or the admin panel's green button) - then it goes back
# to red on its own. Change the number here (or set RELAY_GREEN_SECONDS in
# .env) and restart the service: sudo systemctl restart ri-lpr-relay
# Turning a light green again while it is already green starts the time
# over. This is the only green duration - the "seconds" the backend may
# send with a request is ignored on purpose, so this file is the one
# place to change it.
GREEN_SECONDS = float(os.environ.get("RELAY_GREEN_SECONDS", "30"))

# What each line's GPIO pin does (plain logic level, no relay inversion):
#   1 (pin HIGH, 3.3 V) = GREEN
#   0 (pin LOW,  0 V)   = RED  - also the state at start-up and shutdown
# If your driver board is wired the other way around, set this to False.
GREEN_IS_HIGH = True

# Which BCM GPIO number drives which line. Chosen to avoid the Pi's special
# pins (I2C 2/3, SPI 7-11, UART 14/15) and to sit close together on the
# header. Physical header pin in brackets - connect each to that line's
# light driver input, and a GND pin (e.g. physical 9, 14, 20, 25, 30, 34,
# 39) to the driver's ground.
LINE_TO_PIN = {
    1: 17,  # physical pin 11
    2: 27,  # physical pin 13
    3: 22,  # physical pin 15
    4: 23,  # physical pin 16
    5: 24,  # physical pin 18
    6: 25,  # physical pin 22
}
