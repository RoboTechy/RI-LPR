# RI-LPR Rahkaran Plate Assistant (Chrome extension)

Fills camera-detected truck plates into Rahkaran's loading/unloading
permit forms instead of the operator typing them. See the project chat
history for the full design discussion and the exact field IDs this
relies on.

## Current status (first testable version)

- Detects which Rahkaran page/tab it's on (Shipping permit, Unloading
  permit, or the "new vehicle" sub-form) by URL.
- On a permit page: focusing the "وسیله حمل" field shows a small
  overlay with **hardcoded fake plates** (see `MOCK_DETECTED_PLATES` in
  `content.js`) - there's no real backend yet, this is only for testing
  the Rahkaran-side behavior today.
- Picking a plate types it (in the short, letter-stripped format) into
  the combobox and waits for Rahkaran's own AJAX search.
- If no match is found, automatically clicks "جدید" and fills the
  "شماره پلاک" field on the new-vehicle form with the same plate.
- On Save (Ctrl+S or clicking the toolbar's ذخیره button) on a permit
  page, reads plate/transporter/permit-type/plant/loading-point/vehicle
  field values and **logs them to the browser console** - not sent
  anywhere yet, since the backend doesn't exist yet.

## Loading it in Chrome (unpacked, for testing)

1. Go to `chrome://extensions`.
2. Turn on "Developer mode" (toggle, top-right).
3. Click "Load unpacked".
4. Select this `extension/` folder.
5. Open Rahkaran, go to a loading or unloading permit page.

## Testing today (no real camera/backend needed)

1. Click into the "وسیله حمل" field - a small box should appear under
   it with two fake plates (formatted like `12345/67`).
2. Click one. Watch the browser console (F12 → Console) for `[RI-LPR]`
   log lines - they explain what happened (match found vs. not, new
   form filled, etc.).
3. If no match was found in Rahkaran's real vehicle list (likely, since
   these are fake plates), it should auto-open a new tab and fill
   "شماره پلاک" there with the same plate.
4. Press Ctrl+S (or click Save) on the permit page and check the
   console for the `captured on Save` log line - confirms field reading
   works, even though nothing is sent anywhere yet.

## Known unknowns to watch for during testing

- Whether `setFieldValue()`'s `input`/`keyup` events are enough to
  trigger Rahkaran's own AJAX vehicle search - if the dropdown never
  shows results even for a real, known plate, this is the first thing
  to debug.
- The Shipping (loading) permit page's `captureFieldIds` (transporter,
  permit type, plant, loading point) use an assumed `fvwMain_` prefix,
  copied from the pattern confirmed for the vehicle field - not yet
  individually verified.

## Next steps (not built yet)

- Real backend connection (replace `MOCK_DETECTED_PLATES` with a fetch/
  WebSocket call; send captured Save data to the backend instead of
  just logging it).
- Decide (per the open question in the project chat) whether the
  "وسیله حمل"/"شماره پلاک" field stays locked after auto-fill or
  becomes editable.
