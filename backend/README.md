# RI-LPR backend

FastAPI + PostgreSQL, fully dockerized. Three containers:

- **db** - PostgreSQL.
- **api** - the admin panel (server-rendered, Persian/RTL) and the API the
  Chrome extension talks to. Port `8000`.
- **worker** - connects to every active camera's RTSP stream, runs the
  plate-recognition pipeline (`license_plate_extractor.read_plate()`,
  using the exported ONNX models), and logs successful reads to the
  database.

## Deploy (on `192.168.201.4`, or wherever it ends up running)

```bash
cd ri-lpr/backend
cp .env.example .env
# edit .env: set EXTENSION_API_KEY, SESSION_SECRET_KEY, DEFAULT_ADMIN_PASSWORD
# to real values - do not deploy with the example defaults.
docker compose up -d --build
```

- Admin panel: `http://192.168.201.4:8000/admin` - log in with
  `DEFAULT_ADMIN_USERNAME`/`DEFAULT_ADMIN_PASSWORD` from `.env` (only
  created automatically the very first time, if no admin user exists
  yet - change the password or add a new admin right after).
- First thing to do after logging in: **Cameras → + افزودن دوربین** for
  each of the 6 lines (IP, RTSP credentials/path, line number). The
  worker only picks up cameras marked "فعال" (active) - restart the
  `worker` container after adding/changing cameras:
  `docker compose restart worker`.

## What the extension needs from here

- `EXTENSION_API_KEY` from `.env` must match the `API_KEY` constant in
  `extension/content.js`.
- The extension's `manifest.json` needs `http://192.168.201.4:8000/*`
  in `host_permissions` (already added).

## API (extension-facing, needs header `X-API-Key: <EXTENSION_API_KEY>`)

- `GET /api/plates/active` - every not-yet-used plate detected in the
  last `ACTIVE_PLATE_WINDOW_MINUTES`, across all lines, newest first.
- `POST /api/permit-logs` - logs one permit's captured fields (plate,
  transporter, permit type, plant, loading point, vehicle) plus which
  detection it came from, if any.

## Notes / known simplifications (MVP, built under time pressure)

- No per-operator login for the extension - any operator may pick up
  any line's plate (confirmed with the user: with 6 lines and only 2
  operators, a driver may end up at a different operator's desk than
  their own line, so the extension shows every currently active plate,
  labeled with its line number, rather than filtering by camera).
- A detected plate is de-duplicated per camera for
  `WORKER_DEDUPE_COOLDOWN_SECONDS` (default 5 min) - not a real
  "truck has left" detection. Good enough for now; revisit if trucks
  queue at the same line for longer than that.
- No DB migrations tool - tables are created with `create_all()` on
  startup. Fine for a fresh deploy; if the schema changes later after
  going live, this needs Alembic (or a manual `ALTER TABLE`).
