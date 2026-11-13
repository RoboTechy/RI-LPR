/**
 * RI-LPR Rahkaran Plate Assistant - content script.
 *
 * Runs in every frame of every Rahkaran page (all_frames: true in
 * manifest.json) because each open tab in Rahkaran's own tab bar
 * ("مجوز بارگیری", "مجوز تخلیه", "وسیله حمل") is a separate <iframe>
 * with its own URL - confirmed by inspecting DevTools, which showed each
 * one as a distinct "#document (URL)" node. So each frame's copy of this
 * script independently checks its OWN window.location to know which
 * Rahkaran page it is, and only acts if it recognizes one.
 *
 * IMPORTANT: content scripts run in an "isolated world" - they do NOT
 * share the page's own JS scope, so page-defined functions like
 * `_SgSelector.New(...)` cannot be called directly from here (that
 * would throw ReferenceError). Instead we simulate a real click on the
 * actual DOM element - synthetic DOM events/clicks DO reach the page's
 * own event listeners, since the DOM itself is shared even though JS
 * variables/functions are not. Same reasoning for filling inputs: we
 * set .value and dispatch real events rather than calling any Rahkaran
 * JS function directly.
 */
(function () {
  'use strict';

  // Must match backend/.env's EXTENSION_API_KEY on whatever server the
  // backend actually runs on (see backend/README.md).
  const API_BASE_URL = 'http://192.168.201.4:8000';
  const API_KEY = 'change-me-extension-key';

  // --- Field/selector map, one entry per Rahkaran page this script cares about ---
  // IDs confirmed by inspecting the live page (see project chat history);
  // the "fvwMain_" prefix only appears on the Shipping (loading) permit
  // page, not on Unloading - confirmed for the vehicle combobox, for
  // `plate` (txtPlateIdentifier - DevTools-confirmed), for `transporter`
  // (sltTransporter_Input - DevTools-confirmed to hold the driver's
  // NAME, e.g. "محمد رضا قره قونی"), and for `transporterNationalCode`
  // (txtLiscenseNumber - a separate, disabled textbox that Rahkaran
  // auto-fills with that same driver's license-number/national-code
  // once picked from the combo above - DevTools-confirmed value
  // "5130062620" for that same driver). This is the field an earlier
  // guess wrongly assumed was the plate - it never was, but it's the
  // right field for this. Assumed (not yet verified) for the rest.
  const PERMIT_PAGES = {
    shipping: {
      pageType: 'shipping',
      urlPattern: /TransportationManagement\/ShippingOrderPages\/Edit\.aspx/i,
      vehicleInputId: 'fvwMain_sltTransportationVehicle_Input',
      vehicleDropdownId: 'fvwMain_sltTransportationVehicle_DropDown',
      captureFieldIds: {
        plate: 'fvwMain_txtPlateIdentifier',
        transporter: 'fvwMain_sltTransporter_Input',
        transporterNationalCode: 'fvwMain_txtLiscenseNumber',
        permitType: 'fvwMain_lkpPermitType_ComboBox_Input',
        plant: 'fvwMain_sltPlant_Input',
        loadingPoint: 'fvwMain_sltLoadingPoint_Input',
        vehicle: 'fvwMain_sltTransportationVehicle_Input',
      },
    },
    unloading: {
      pageType: 'unloading',
      urlPattern: /TransportationManagement\/UnloadingOrderPages\/Edit\.aspx/i,
      vehicleInputId: 'sltTransportationVehicle_Input',
      vehicleDropdownId: 'sltTransportationVehicle_DropDown',
      captureFieldIds: {
        plate: 'txtPlateIdentifier',
        transporter: 'sltTransporter_Input',
        transporterNationalCode: 'txtLiscenseNumber',
        permitType: 'lkpPermitType_ComboBox_Input',
        plant: 'sltPlant_Input',
        loadingPoint: 'sltLoadingPoint_Input',
        vehicle: 'sltTransportationVehicle_Input',
      },
    },
  };

  const NEW_VEHICLE_PAGE = {
    urlPattern: /CarriageStructure\/TransportationVehiclePages\/Edit\.aspx/i,
    plateFieldId: 'formView_txtPlateIdentifier',
  };

  const STORAGE_KEY_PENDING_PLATE = 'ri_lpr_pending_plate_for_new_vehicle';

  // No per-operator/per-camera filtering on purpose: with 6 lines and
  // only 2 operators, a driver may end up at a different operator's
  // desk than their own line, so every currently active plate (across
  // all cameras) is shown, each labeled with its line number - the
  // operator picks whichever one matches the truck actually in front
  // of them (confirmed with the user).
  async function fetchPlateOverlay() {
    try {
      const res = await fetch(`${API_BASE_URL}/api/plates/overlay`, {
        headers: { 'X-API-Key': API_KEY },
      });
      if (!res.ok) {
        console.warn('[RI-LPR] backend returned', res.status, 'fetching active plates');
        return null;
      }
      return await res.json();
    } catch (err) {
      console.warn('[RI-LPR] could not reach the backend for the plate list:', err);
      return null;
    }
  }

  async function rereadLane(lineNumber) {
    const response = await fetch(`${API_BASE_URL}/api/plates/reread/${lineNumber}`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY },
    });
    if (!response.ok) throw new Error(`Reread request failed: ${response.status}`);
    return response.json();
  }

  async function logPermitToBackend(payload) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/permit-logs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        console.warn('[RI-LPR] backend rejected the permit log:', res.status, await res.text());
        return;
      }
      console.log('[RI-LPR] permit logged to backend:', await res.json());
    } catch (err) {
      console.warn('[RI-LPR] could not reach the backend to log this permit:', err);
    }
  }

  // Plain fill for ordinary text fields (no search/filter behavior
  // attached) - e.g. the new-vehicle form's "شماره پلاک" field.
  function setFieldValue(input, value) {
    input.focus();
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // KeyboardEvent's keyCode/which/charCode are read-only once
  // constructed in modern browsers (they stay 0), but legacy code
  // (this Telerik RadComboBox included - confirmed empirically: a
  // bare `new Event('keyup')` left the search unfiltered, showing the
  // full vehicle list instead of a real AJAX search result) often
  // checks event.keyCode directly. Overriding the getter is the
  // standard workaround to make a synthetic event report a real value.
  function dispatchKeyEvent(input, type, ch) {
    const keyCode = ch.charCodeAt(0);
    const event = new KeyboardEvent(type, { bubbles: true, cancelable: true, key: ch });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    Object.defineProperty(event, 'which', { get: () => keyCode });
    Object.defineProperty(event, 'charCode', { get: () => keyCode });
    input.dispatchEvent(event);
  }

  // Simulates real character-by-character typing (not "set .value once
  // and fire one generic event") - needed to trigger Rahkaran's own
  // AJAX vehicle search, which a single bulk event did not trigger.
  function typeIntoField(input, text, onDone) {
    input.focus();
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));

    let i = 0;
    function typeNextChar() {
      if (i >= text.length) {
        // give the debounced AJAX search time to fire and come back
        setTimeout(onDone, 900);
        return;
      }
      const ch = text[i];
      input.value += ch;
      dispatchKeyEvent(input, 'keydown', ch);
      dispatchKeyEvent(input, 'keypress', ch);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      dispatchKeyEvent(input, 'keyup', ch);
      i += 1;
      setTimeout(typeNextChar, 70);
    }
    typeNextChar();
  }

  // Below this, the OCR read gets flagged to the operator as "weak" so
  // they know to double check it against the truck itself rather than
  // trusting it blindly - confidence is the weakest single character's
  // score (see backend), a reasonable stand-in for "how sure is the
  // whole read".
  const CONFIDENCE_GOOD_THRESHOLD = 0.75;

  function confidenceLabel(confidence) {
    if (confidence === null || confidence === undefined) return null;
    return confidence >= CONFIDENCE_GOOD_THRESHOLD
      ? { text: 'خوب', cls: 'good' }
      : { text: 'ضعیف', cls: 'weak' };
  }

  // Shows the live "detected plates" list under the vehicle field and
  // keeps it refreshed (about once per second) while it stays open, so a plate that
  // appears while the operator is looking shows up without them having
  // to close/reopen it.
  function buildOverlay(anchorInput, onPick, onShown) {
    const existing = document.getElementById('ri-lpr-overlay');
    if (existing) existing.remove();

    const box = document.createElement('div');
    box.id = 'ri-lpr-overlay';
    box.className = 'ri-lpr-overlay';

    const rect = anchorInput.getBoundingClientRect();
    box.style.top = `${rect.bottom + window.scrollY}px`;
    box.style.left = `${rect.left + window.scrollX}px`;
    box.style.width = `${Math.max(rect.width, 220)}px`;

    const title = document.createElement('div');
    title.className = 'ri-lpr-overlay-title';
    title.textContent = 'پلاک‌های شناسایی‌شده';
    box.appendChild(title);

    const listEl = document.createElement('div');
    box.appendChild(listEl);

    const laneDetails = document.createElement('details');
    laneDetails.className = 'ri-lpr-lane-details';
    const laneSummary = document.createElement('summary');
    laneSummary.textContent = 'وضعیت لاین‌ها';
    laneDetails.appendChild(laneSummary);
    const laneRows = document.createElement('div');
    laneDetails.appendChild(laneRows);
    box.appendChild(laneDetails);

    const rereadStatus = document.createElement('div');
    rereadStatus.className = 'ri-lpr-reread-status';
    rereadStatus.setAttribute('role', 'status');
    box.appendChild(rereadStatus);
    document.body.appendChild(box);

    const pendingRereads = new Set();
    let lastRenderedPlates;
    let lastRenderedLanes;
    let liveLanes = [];
    let rereadNotice;

    function showLaneStatuses() {
      const inlineNotice = laneDetails.open && rereadNotice &&
        liveLanes.some((lane) => lane.line_number === rereadNotice.line) ? rereadNotice : null;
      rereadStatus.textContent = rereadNotice && !inlineNotice
        ? `لاین ${rereadNotice.line} — ${rereadNotice.message}`
        : '';
      renderLaneStatuses(liveLanes, inlineNotice);
    }
    laneDetails.addEventListener('toggle', showLaneStatuses);

    function setRereadButtons(line, disabled) {
      for (const button of box.querySelectorAll(`button[data-line="${line}"]`)) {
        button.disabled = disabled;
      }
    }

    const hiddenPlateReasons = {
      permit_saved: 'مجوز این پلاک قبلاً ثبت شده است',
      permit_recent: 'مجوز این پلاک ثبت شده؛ مهلت ثبت مجدد هنوز تمام نشده است',
      newer_detection: 'پلاک تازه‌تری در این لاین ثبت شده است',
      expired: 'زمان نمایش این پلاک تمام شده است',
      updating: 'منتظر به‌روزرسانی فهرست',
    };

    async function reread(line) {
      if (pendingRereads.has(line)) return;
      pendingRereads.add(line);
      setRereadButtons(line, true);
      const notice = { line, message: 'در حال خواندن مجدد…' };
      rereadNotice = notice;
      showLaneStatuses();
      const messages = {
        available: 'پلاک دوباره خوانده شد',
        not_available: hiddenPlateReasons.updating,
        empty: 'لاین خالی است',
        no_read: 'خواندن مطمئن پلاک ممکن نشد',
        busy: 'خواندن مجدد در حال انجام است',
        unavailable: 'پردازشگر در دسترس نیست',
      };
      let result;
      try {
        result = await rereadLane(line);
      } catch {
        result = { status: 'unavailable' };
      } finally {
        pendingRereads.delete(line);
        setRereadButtons(line, false);
      }
      if (!box.isConnected || rereadNotice !== notice) return;

      notice.message = hiddenPlateReasons[result.reason] || messages[result.status] || messages.unavailable;
      notice.status = result.status === 'no_read' ? 'unreadable' : result.status;
      notice.reason = result.reason;
      showLaneStatuses();
      setTimeout(() => {
        if (rereadNotice !== notice) return;
        rereadNotice = undefined;
        if (box.isConnected) showLaneStatuses();
      }, 4000);
    }

    function makeRereadButton(line) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ri-lpr-reread-button';
      button.dataset.line = line;
      button.title = `خواندن مجدد پلاک لاین ${line}`;
      button.setAttribute('aria-label', button.title);
      button.textContent = '↻';
      button.disabled = pendingRereads.has(line);
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        reread(line);
      });
      return button;
    }

    function renderLaneStatuses(lanes, inlineNotice) {
      const signature = JSON.stringify([lanes, inlineNotice]);
      if (signature === lastRenderedLanes) return;
      lastRenderedLanes = signature;
      laneRows.replaceChildren();
      const labels = {
        empty: 'خالی',
        unreadable: 'خودرو حاضر، پلاک ناخوانا',
        available: 'پلاک قابل‌انتخاب',
        not_available: hiddenPlateReasons.updating,
        unavailable: 'تصویر در دسترس نیست',
        disabled: 'غیرفعال',
      };
      for (const lane of lanes) {
        const row = document.createElement('div');
        row.className = 'ri-lpr-lane-row';
        const label = document.createElement('span');
        const message = inlineNotice?.line === lane.line_number ? inlineNotice.message
          : hiddenPlateReasons[lane.reason] || labels[lane.status] || labels.unavailable;
        label.textContent = `لاین ${lane.line_number} — ${message}`;
        row.appendChild(label);
        if (lane.status !== 'disabled') row.appendChild(makeRereadButton(lane.line_number));
        laneRows.appendChild(row);
      }
    }

    function renderList(plates, emptyMessage) {
      const orderedPlates = [...plates].sort((a, b) => a.id - b.id);
      const signature = JSON.stringify([emptyMessage, ...orderedPlates.map(
        (plate) => [plate.id, plate.short_format, plate.line_number, plate.confidence],
      )]);
      if (signature === lastRenderedPlates) return;
      lastRenderedPlates = signature;
      listEl.innerHTML = '';
      if (plates.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'ri-lpr-overlay-empty';
        empty.textContent = emptyMessage;
        listEl.appendChild(empty);
        return;
      }
      orderedPlates.forEach((plate) => {
        const item = document.createElement('div');
        item.className = 'ri-lpr-overlay-item';

        const mainText = document.createElement('span');
        mainText.textContent = `${plate.short_format} — لاین ${plate.line_number}`;
        item.appendChild(mainText);

        const label = confidenceLabel(plate.confidence);
        if (label) {
          const badge = document.createElement('span');
          badge.className = `ri-lpr-overlay-confidence ri-lpr-overlay-confidence-${label.cls}`;
          badge.textContent = label.text;
          item.appendChild(badge);
        }

        item.appendChild(makeRereadButton(plate.line_number));

        item.addEventListener('click', () => {
          closeOverlay();
          onPick(plate);
        });
        listEl.appendChild(item);
      });
    }

    let refreshTimer;
    function stopRefresh() {
      clearTimeout(refreshTimer);
    }

    async function refresh() {
      if (!box.isConnected || !anchorInput.isConnected) {
        closeOverlay();
        return;
      }
      const overlay = await fetchPlateOverlay();
      if (!box.isConnected || !anchorInput.isConnected) {
        closeOverlay();
        return;
      }
      const plates = overlay?.plates || [];
      const lanes = overlay?.lanes || [];
      const allEmpty = lanes.length > 0 && lanes.every((lane) => lane.status === 'empty');
      const emptyMessage = !overlay ? 'ارتباط با سامانه برقرار نیست' : allEmpty
        ? 'در حال حاضر خودرویی مقابل دوربین‌ها نیست'
        : 'در حال حاضر پلاک قابل‌انتخابی وجود ندارد';
      renderList(plates, emptyMessage);
      liveLanes = lanes;
      if (rereadNotice?.status && rereadNotice.status !== 'busy') {
        const lane = lanes.find((item) => item.line_number === rereadNotice.line);
        if (!lane || lane.status !== rereadNotice.status ||
            (rereadNotice.reason && lane.reason !== rereadNotice.reason)) {
          rereadNotice = undefined;
        }
      }
      laneDetails.hidden = lanes.length === 0;
      showLaneStatuses();
      if (document.visibilityState === 'visible' && box.getClientRects().length) {
        onShown(plates);
      }
      refreshTimer = setTimeout(refresh, 1000);
    }
    refresh();

    function closeOverlay() {
      stopRefresh();
      box.remove();
      document.removeEventListener('click', closeOnOutsideClick, true);
    }

    function closeOnOutsideClick(e) {
      if (!box.contains(e.target) && e.target !== anchorInput) closeOverlay();
    }
    setTimeout(() => {
      if (box.isConnected) document.addEventListener('click', closeOnOutsideClick, true);
    }, 0);
  }

  // Polls the dropdown a few times (Telerik's AJAX search isn't instant)
  // and reports how many <li> results it ended up with - 0 means no
  // matching vehicle, per the empty <ul class="rcbList"> confirmed live.
  function waitForDropdownResult(dropdownId, callback, attemptsLeft = 5) {
    const dropdown = document.getElementById(dropdownId);
    const list = dropdown ? dropdown.querySelector('ul.rcbList') : null;
    const itemCount = list ? list.children.length : 0;

    if (itemCount === 0 && attemptsLeft > 0) {
      setTimeout(() => waitForDropdownResult(dropdownId, callback, attemptsLeft - 1), 400);
      return;
    }
    callback(itemCount);
  }

  function clickNewButton(dropdownId) {
    const dropdown = document.getElementById(dropdownId);
    const newButton = dropdown ? dropdown.querySelector('.new') : null;
    if (!newButton) {
      console.warn('[RI-LPR] could not find the "جدید" button inside', dropdownId);
      return;
    }
    newButton.click();
  }

  function plateDigits(value) {
    return (value || '')
      .replace(/[۰-۹]/g, (digit) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(digit)))
      .replace(/[٠-٩]/g, (digit) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(digit)))
      .replace(/[^0-9]/g, '');
  }

  function initPermitPage(config) {
    // typeIntoField() calls input.focus() itself (needed to make the
    // simulated keystrokes land on the field), which would otherwise
    // re-trigger this very focus listener and pop our overlay back up
    // on top of Rahkaran's own results while we're mid-fill. This flag
    // suppresses that re-trigger for the duration of one pick.
    let suppressOverlayOnFocus = false;

    // The backend detection id behind whatever plate was last picked
    // from our overlay (if any) - sent along at Save so the backend can
    // link the permit log to its crop images and mark it used.
    let lastPickedDetectionId = null;
    const shownByNumber = new Map();
    let overlayAnchor;

    function openOverlay(input) {
      if (overlayAnchor === input && document.getElementById('ri-lpr-overlay')) return;
      overlayAnchor = input;
      buildOverlay(input, (plate) => {
        suppressOverlayOnFocus = true;
        lastPickedDetectionId = plate.id;
        const shortPlate = plate.short_format;
        typeIntoField(input, shortPlate, () => {
          waitForDropdownResult(config.vehicleDropdownId, (itemCount) => {
            if (itemCount === 0) {
              suppressOverlayOnFocus = false;
              console.log('[RI-LPR] no matching vehicle for', shortPlate, '- opening the new-vehicle form');
              chrome.storage.local.set({ [STORAGE_KEY_PENDING_PLATE]: shortPlate }, () => {
                clickNewButton(config.vehicleDropdownId);
              });
            } else {
              console.log(`[RI-LPR] ${itemCount} matching vehicle(s) found for`, shortPlate, '- pick one from Rahkaran\'s own list');
              // Clicking the actual result row in Rahkaran's own dropdown
              // can itself refocus this input (part of how Rahkaran sets
              // the field once a row is picked) - if we re-enabled the
              // overlay immediately, that refocus would pop it right back
              // up over the selection the operator just made. Give them a
              // few seconds to click a row before re-arming it.
              setTimeout(() => { suppressOverlayOnFocus = false; }, 4000);
            }
          });
        });
      }, (plates) => {
        for (const plate of plates) {
          const number = plateDigits(plate.short_format);
          if (number.length === 7) shownByNumber.set(number, plate.id);
        }
      });
    }

    // Rahkaran can replace this input during a partial form update. Listen
    // on the document so the replacement input still opens the overlay.
    document.addEventListener('focusin', (event) => {
      if (event.target?.id !== config.vehicleInputId || suppressOverlayOnFocus) return;
      openOverlay(event.target);
    }, true);

    document.addEventListener('click', (event) => {
      if (event.isTrusted && event.target?.id === config.vehicleInputId) {
        openOverlay(event.target);
      }
    }, true);

    // If the field already had a value (e.g. a vehicle the operator
    // picked earlier) and they clear it with backspace/delete while
    // still focused, no new 'focus' event fires - so without this the
    // overlay would only come back after a blur+refocus. Reopen it the
    // moment the field goes back to empty; but once they start typing
    // a character themselves, leave them alone and let Rahkaran's own
    // search run undisturbed.
    document.addEventListener('input', (event) => {
      const input = event.target;
      if (input?.id !== config.vehicleInputId || suppressOverlayOnFocus) return;
      if (input.value === '') {
        openOverlay(input);
      } else {
        const existing = document.getElementById('ri-lpr-overlay');
        if (existing) existing.remove();
      }
    }, true);

    function captureAndLog() {
      if (!document.getElementById(config.vehicleInputId)) return;
      const data = {};
      for (const [key, id] of Object.entries(config.captureFieldIds)) {
        const el = document.getElementById(id);
        data[key] = el ? el.value : null;
      }
      logPermitToBackend({
        detected_plate_id: lastPickedDetectionId,
        shown_plate_detection_id: shownByNumber.get(plateDigits(data.plate)) ?? null,
        page_type: config.pageType,
        page_url: window.location.href,
        plate: data.plate,
        transporter: data.transporter,
        transporter_national_code: data.transporterNationalCode,
        permit_type: data.permitType,
        plant: data.plant,
        loading_point: data.loadingPoint,
        vehicle: data.vehicle,
      });
      lastPickedDetectionId = null; // consumed - a fresh pick is needed for the next permit
      shownByNumber.clear();
    }

    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        captureAndLog();
      }
    });

    document.addEventListener('click', (e) => {
      const saveLink = e.target.closest('#usrTop_tlbMain a[title*="ذخیره"]');
      if (saveLink) captureAndLog();
    });
  }

  function initNewVehiclePage(config) {
    chrome.storage.local.get([STORAGE_KEY_PENDING_PLATE], (result) => {
      const plate = result[STORAGE_KEY_PENDING_PLATE];
      if (!plate) return;

      function tryFill(attemptsLeft = 15) {
        const field = document.getElementById(config.plateFieldId);
        if (!field) {
          if (attemptsLeft <= 0) {
            console.warn('[RI-LPR] plate field never appeared on the new-vehicle page');
            return;
          }
          setTimeout(() => tryFill(attemptsLeft - 1), 300);
          return;
        }
        setFieldValue(field, plate);
        console.log('[RI-LPR] filled the new-vehicle plate field with', plate);
        chrome.storage.local.remove(STORAGE_KEY_PENDING_PLATE);
      }
      tryFill();
    });
  }

  function main() {
    const url = window.location.href;

    for (const config of Object.values(PERMIT_PAGES)) {
      if (config.urlPattern.test(url)) {
        initPermitPage(config);
        return;
      }
    }

    if (NEW_VEHICLE_PAGE.urlPattern.test(url)) {
      initNewVehiclePage(NEW_VEHICLE_PAGE);
    }
  }

  main();
})();
