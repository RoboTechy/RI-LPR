# RI-LPR Rahkaran Plate Assistant (Chrome extension)

Fills camera-detected truck plates into Rahkaran's loading/unloading
permit forms instead of the operator typing them. See the project chat
history for the full design discussion and the exact field IDs this
relies on.

## How it works

- Detects which Rahkaran page/tab it's on (Shipping permit, Unloading
  permit, or the "new vehicle" sub-form) by URL.
- On a permit page: focusing the "وسیله حمل" field shows a small
  overlay listing every plate the backend currently has as "active"
  (detected in the last `ACTIVE_PLATE_WINDOW_MINUTES`, not yet used on
  a saved permit) - across **all** lines/cameras, each one labeled with
  its line number. There's no per-computer camera filtering: with 6
  lines and only 2 operators, a driver may end up at a different
  operator's desk than their own line, so every operator sees every
  currently active plate and picks whichever one matches the truck
  actually in front of them. The list auto-refreshes every 4 seconds
  while open.
- Picking a plate types it (in the short, letter-stripped format the
  backend already computed) into the combobox and waits for Rahkaran's
  own AJAX search.
- If no match is found, automatically clicks "جدید" and fills the
  "شماره پلاک" field on the new-vehicle form with the same plate.
- On Save (Ctrl+S or clicking the toolbar's ذخیره button) on a permit
  page, reads plate/transporter/permit-type/plant/loading-point/vehicle
  field values and POSTs them to the backend (`POST /api/permit-logs`),
  along with which detected plate (if any) was picked for this permit.

## Setup

1. Open `content.js` and check the two constants near the top:
   - `API_BASE_URL` - where the backend is running (currently
     `http://192.168.201.32:8000`).
   - `API_KEY` - must match `EXTENSION_API_KEY` in the backend's `.env`
     (see `../backend/README.md`). If someone changes one, change the
     other.
2. Go to `chrome://extensions`, turn on "Developer mode", click "Load
   unpacked", select this `extension/` folder.
3. Open Rahkaran, go to a loading or unloading permit page.

If `content.js` or `manifest.json` changes after it's already loaded,
click the reload icon on the extension's card in `chrome://extensions`,
then refresh the Rahkaran tab (content scripts only re-inject on page
load).

## Testing

1. Make sure the backend is up and at least one camera is logging
   plates (or insert a test row directly, or just wait for a real
   truck) - `GET http://192.168.201.32:8000/api/plates/active` with
   header `X-API-Key: <the same key>` should return a non-empty list.
2. Click into the "وسیله حمل" field on a permit page - the overlay
   should show the active plates, each with its line number.
3. Pick one. Watch the browser console (F12 → Console) for `[RI-LPR]`
   log lines - they explain what happened (match found vs. not, new
   form filled, etc.).
4. If no match was found in Rahkaran's real vehicle list, it should
   auto-open a new tab and fill "شماره پلاک" there with the same plate.
5. Press Ctrl+S (or click Save) on the permit page - check the console
   for `permit logged to backend`, and check the backend's admin panel
   (`/admin/logs`) for the new row.

## Known simplifications / open items

- The Shipping (loading) permit page's `captureFieldIds` (transporter,
  permit type, plant, loading point) use an assumed `fvwMain_` prefix,
  copied from the pattern confirmed for the vehicle field - not yet
  individually verified against a real Save on that page.
- Whether the "وسیله حمل"/"شماره پلاک" field should lock (read-only)
  after auto-fill, or stay editable, is still an open question from the
  project chat - revisit once there's time.
- `API_KEY` is a plain constant in `content.js`, visible to anyone who
  opens the extension's files - acceptable for an internal-network MVP,
  not for anything exposed beyond that.
