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
- Two account levels (**Users**, مدیر-only): **مدیر** (`is_superuser`)
  manages cameras and other accounts; **اوپراتور** can only view/test/
  stream the cameras it's explicitly granted and use their traffic-light
  buttons (see below) - it cannot add, edit or delete a camera or
  another account, even its own granted ones.

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

A `transporter_national_code` column was also added to `permit_logs`
(the transporter's auto-filled license-number/national-code field,
alongside the existing `transporter` name field - see گزارش‌ها page).
Same situation - run this once too:

```bash
docker compose exec db psql -U ri_lpr -d ri_lpr -c \
  "ALTER TABLE permit_logs ADD COLUMN IF NOT EXISTS transporter_national_code VARCHAR(50);"
```

Permits saved before this runs simply have it as `NULL`.

## Exporting a fine-tuning dataset

For collecting training data while the system is new - deliberately
**not** a docker-compose service (only needed for a few days, not an
always-on thing): run it on demand inside the already-running `worker`
container, which already has DB + media access:

```bash
docker compose exec worker python3 backend/worker/export_training_dataset.py --min-confidence 0.75
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

## Finding what the plate reader gets wrong

`export_training_dataset.py` above only exports reads the pipeline was
confident about. This is its counterpart - it reports the mistakes:

```bash
docker compose exec worker python3 backend/worker/export_ocr_mismatches.py
```

It compares every saved permit's plate (the truth - an operator typed
or confirmed it) with what the camera read, and sorts each permit into
one category: read correctly, read wrong and corrected by the operator,
typed by hand although a near-identical detection existed, or never
detected at all. It also lists the worker's **failed reads** - frames
where a truck was in the lane but no plate was found, or a plate was
found but its characters were rejected. The worker keeps one of those
per camera every `WORKER_FAILED_READ_INTERVAL_SECONDS` (default 30,
`0` to turn it off) in the `failed_reads` table, images under
`media/failed_reads/`.

Output goes to `media/ocr_review/`: `summary.json` (counts, plate
accuracy, per line), `confusion.csv` (which digit is mistaken for
which), `mismatches.jsonl` (each wrong read with its corrected
characters), `confirmed.jsonl` (verified-correct reads), and the images
behind every mismatch and failed read for review. See the script's
`--help` for options.

The numbers only become meaningful after the system has run for a
while with this version: failed reads and per-character boxes are only
recorded from now on.

## Backups

The database holds every detection and every saved permit - nothing else
has a copy of it. Set up the nightly backup **right after first deploy**,
not as an afterthought:

```bash
cd ri-lpr/backend
./scripts/backup_db.sh   # run it once by hand first - this also creates
                          # backups/, which the cron line below assumes
                          # already exists (cron can't create a directory
                          # just to redirect its log into)
crontab -e
# add this line (runs at 02:00 server time every night):
0 2 * * * cd /path/to/ri-lpr/backend && ./scripts/backup_db.sh >> backups/backup.log 2>&1
```

(Replace `/path/to/ri-lpr` with the real path on whatever server this is
deployed on.)

- Writes a gzip-compressed `pg_dump` to `backend/backups/ri_lpr_<timestamp>.sql.gz`
  via `docker compose exec db pg_dump` - always the exact same Postgres
  version as the running `db` container, no separate client install
  needed.
- `backend/backups/` is a plain directory on the host, **not** inside the
  `db_data` Docker volume - a `docker compose down -v` or a volume-level
  failure can't take the backups down with the live data.
- Keeps 14 days by default; override with `BACKUP_RETENTION_DAYS=30` (or
  any value) before the cron command, or just run
  `BACKUP_RETENTION_DAYS=30 ./scripts/backup_db.sh` by hand.
- Writes to a `.part` file and only renames it on success, so a backup
  killed mid-run never leaves a file that looks valid but isn't.

**This alone only protects against database corruption or an accidental
`DROP`/`docker compose down -v` - not against losing the whole server.**
If there's another machine, NAS, or even just a USB drive on site, add a
second cron line that copies `backend/backups/` somewhere else, e.g.:

```bash
30 2 * * * rsync -a /path/to/ri-lpr/backend/backups/ user@other-host:/backups/ri-lpr/
```

**Restoring** (destructive - confirms before touching anything):

```bash
cd ri-lpr/backend
./scripts/restore_db.sh backups/ri_lpr_2026-11-14_020000.sql.gz
docker compose restart api worker
```

## Traffic light (Raspberry Pi relay)

Each line's traffic light is in one of two modes, set on the
دوربین‌ها page (any account with access to the camera may switch it):

- **خودکار (automatic, default)** - saving a permit linked to a detection
  turns that line's light green for the number of seconds set at the top
  of the page (**مدیر** only, default 30); the Pi then turns it red by
  itself. The green/red buttons are hidden.
- **دستی (manual)** - saving a permit does not touch the light. The
  operator uses "سبز کردن" / "قرمز کردن"; green stays until red is
  pressed (no timer). Switching a line back to automatic turns its light
  red first.

See `../pi-relay-service/README.md` for the Pi-side setup (wiring, GPIO
pin mapping, systemd service) and `PI_RELAY_SERVICE_URL`/
`PI_RELAY_API_KEY` above for pointing this backend at it. If the Pi is
unreachable, none of this ever blocks saving a permit or breaks the
admin panel (see `app/relay_client.py`) - the light just shows as
"نامشخص"، and `GET /admin/cameras/lights-status` (fetched by the page
itself, asynchronously, after it's already rendered) is the only thing
that ever waits on the Pi - not the page load itself.

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
