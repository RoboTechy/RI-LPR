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

## Upgrading an already-running deployment past this commit

A `plate_box` column was added to `detected_plates` (see "Exporting a
fine-tuning dataset" below). `create_all()` only creates missing
*tables*, not missing *columns* on a table that already exists - on a
deployment that already has real data, run this once against the live
database before (or right after) `docker compose up -d --build`:

```bash
docker compose exec db psql -U ri_lpr -d ri_lpr -c \
  "ALTER TABLE detected_plates ADD COLUMN IF NOT EXISTS plate_box JSON;"
```

Detections logged before this runs simply have `plate_box = NULL` and
are skipped by the export script - nothing else is affected.

## Exporting a fine-tuning dataset

For collecting training data while the system is new - deliberately
**not** a docker-compose service (only needed for a few days, not an
always-on thing): run it on demand inside the already-running `worker`
container, which already has DB + media access:

```bash
docker compose exec worker python3 worker/export_training_dataset.py --min-confidence 0.75
```

Writes, per high-confidence detection, the vehicle image + a YOLO-format
bounding box label for the plate + the cropped plate image + a
`manifest.jsonl` with the full OCR text and metadata, into
`media/training_export/` inside the container (i.e.
`backend/media/training_export/` on the host, via the `media_data`
volume). See the script's own docstring (`--help`) for all options,
including `--only-consumed` (export only plates an operator actually
picked and saved a permit against - stronger correctness signal than
OCR confidence alone). Only covers detections logged after the
`plate_box` column was added (see above) - older ones are skipped.

## Notes / known simplifications (MVP, built under time pressure)

- No per-operator login for the extension - any operator may pick up
  any line's plate (confirmed with the user: with 6 lines and only 2
  operators, a driver may end up at a different operator's desk than
  their own line, so the extension shows every currently active plate,
  labeled with its line number, rather than filtering by camera).
- A truck is recognized as "the same one still sitting there" (no new
  row - its existing one's timestamp is refreshed instead) by comparing
  where the vehicle sits in frame between reads (`WORKER_IOU_SAME_TRUCK_THRESHOLD`),
  not by plate text (OCR can misread a single character between polls)
  or by a fixed cooldown (a truck can sit there far longer than any
  reasonable cooldown). `WORKER_PRESENCE_GAP_SECONDS` resets that
  tracking once nothing's been read for a while, so a genuinely
  different truck arriving later - even in the same spot - still gets
  logged. Not real multi-object tracking, just a position check between
  consecutive successful reads; good enough for one truck at a time
  per line.
- No DB migrations tool - tables are created with `create_all()` on
  startup. Fine for a fresh deploy; if the schema changes later after
  going live, this needs Alembic (or a manual `ALTER TABLE`).
