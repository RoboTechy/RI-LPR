# RI-LPR relay - Arduino Mega 2560 + Ethernet shield (W5100)

An alternative to `../pi-relay-service` (the Raspberry Pi version). It
answers the **same HTTP commands**, so the backend, the admin panel's
automatic/manual modes and the extension work with either one - the only
thing that decides which device is used is `PI_RELAY_SERVICE_URL` in
`backend/.env`. Use one device per set of lights, never both on the same
lights.

## How it works

Each line has one output pin: **HIGH (1, 5 V) = green, LOW (0) = red**.
Red is the idle state - every pin is driven LOW the moment the board
starts. The backend sends how long green should last with each command:

- `POST /light/{n}/green?seconds=30` - green, then back to red by itself
  after 30 s (automatic mode, the time set in the admin panel);
- `POST /light/{n}/green?seconds=0` - green until `/red` (manual mode);
- `POST /light/{n}/red` - red at once;
- `GET /lights`, `GET /light/{n}`, `GET /health` - status.

All but `/health` need the header `X-API-Key`.

## Pins (Mega 2560)

| Line | Arduino pin |
|------|-------------|
| 1 | 22 |
| 2 | 23 |
| 3 | 24 |
| 4 | 25 |
| 5 | 26 |
| 6 | 27 |

These avoid the pins the Ethernet shield uses (4, 10, 50-53) and the USB
serial pins (0, 1). Change `LINE_PINS` in the sketch if you want others,
but keep away from those.

Wiring, per line:
- Arduino pin -> the relay/driver board's input for that line.
- Arduino GND -> the board's GND (always share the ground).
- The board's VCC -> the Arduino's 5 V pin (a 5 V relay board is driven
  directly - no level converter needed, unlike the Pi). A relay board with
  several relays can draw a lot: power it from a separate 5 V supply if
  you can, joining its GND with the Arduino's.
- **10 kOhm resistor from each output pin to GND** (pull-down). For about
  a second after power-up, before the sketch runs, Arduino pins are
  floating; the resistor keeps them at 0 (red) so a light never flashes
  green at boot.

If your relay board is active-low (relay on at 0 V), set
`GREEN_IS_HIGH = false` in the sketch. Check that red really means "relay
off / idle" on your board before wiring all six lines.

## Install

1. Plug the Ethernet shield onto the Mega. Connect it to the network with
   a cable.
2. Install the **Arduino IDE** on your PC. Open `arduino-relay.ino`
   (the folder `arduino-relay` must keep that name).
3. Edit the settings block at the top of the sketch:
   - `LOCAL_IP`, `GATEWAY`, `SUBNET`, `DNS_SERVER` - a free fixed address
     the backend server can reach (the defaults are an example in
     192.168.203.x - change them);
   - `MAC` - any address that is unique on your network;
   - `API_KEY` - the same value as `PI_RELAY_API_KEY` in `backend/.env`
     (up to 60 characters);
   - `DEFAULT_GREEN_SECONDS` - only used when a command has no `seconds`.
4. **Tools -> Board -> Arduino Mega or Mega 2560**, pick the USB port
   under **Tools -> Port**, then **Upload**.
5. Open **Tools -> Serial Monitor** at 115200 baud. It prints
   `RI-LPR relay ready at <ip>:8080`, and a line for each request.

The sketch starts by itself every time the board gets power - nothing to
run after a reboot or power cut. To update it, upload again over USB.

## Test (from any PC or the server on the same network)

```bash
curl http://<arduino-ip>:8080/health                                   # no key needed
curl -H "X-API-Key: <key>" http://<arduino-ip>:8080/lights             # all red
curl -X POST -H "X-API-Key: <key>" "http://<arduino-ip>:8080/light/1/green?seconds=5"
# pin 22 is 5 V for 5 s, then 0 V
```

Then point the backend at it - in `backend/.env` on the server:

```
PI_RELAY_SERVICE_URL=http://<arduino-ip>:8080
PI_RELAY_API_KEY=<the same key as API_KEY in the sketch>
```

and run `docker compose restart api`. The admin panel's دوربین‌ها page
then shows each line's colour. To go back to the Raspberry Pi, put its
address back and restart `api` again.

## Notes

- Plain HTTP on the plant network, like the Pi version; the key is checked
  on every command except `/health`.
- One request is handled at a time; the backend's calls are short, so
  that is fine for six lines.
- `USE_WATCHDOG` (off by default) makes the board reset itself if the
  program hangs. Turn it on only if your Mega's bootloader supports the
  watchdog, otherwise the board can get stuck restarting.
- The seconds in a green command can be fractional (`0.5`); the reply
  shows whole seconds.
