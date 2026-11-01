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

  // --- Field/selector map, one entry per Rahkaran page this script cares about ---
  // IDs confirmed by inspecting the live page (see project chat history);
  // the "fvwMain_" prefix only appears on the Shipping (loading) permit
  // page, not on Unloading - confirmed for the vehicle combobox, assumed
  // (not yet verified) for the rest of the captureFieldIds on Shipping.
  const PERMIT_PAGES = {
    shipping: {
      urlPattern: /TransportationManagement\/ShippingOrderPages\/Edit\.aspx/i,
      vehicleInputId: 'fvwMain_sltTransportationVehicle_Input',
      vehicleDropdownId: 'fvwMain_sltTransportationVehicle_DropDown',
      captureFieldIds: {
        plate: 'fvwMain_txtLiscenseNumber',
        transporter: 'fvwMain_sltTransporter_Input',
        permitType: 'fvwMain_lkpPermitType_ComboBox_Input',
        plant: 'fvwMain_sltPlant_Input',
        loadingPoint: 'fvwMain_sltLoadingPoint_Input',
        vehicle: 'fvwMain_sltTransportationVehicle_Input',
      },
    },
    unloading: {
      urlPattern: /TransportationManagement\/UnloadingOrderPages\/Edit\.aspx/i,
      vehicleInputId: 'sltTransportationVehicle_Input',
      vehicleDropdownId: 'sltTransportationVehicle_DropDown',
      captureFieldIds: {
        plate: 'txtLiscenseNumber',
        transporter: 'sltTransporter_Input',
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

  // --- TEMPORARY: hardcoded fake "detected plates" for testing today,
  // before the real backend exists. Replace with a real fetch() to the
  // backend once it's up (see extension/README.md). ---
  const MOCK_DETECTED_PLATES = [
    { id: 'mock-1', chars: ['1', '2', 'ج', '3', '4', '5', '6', '7'] },
    { id: 'mock-2', chars: ['9', '8', 'و', '1', '1', '1', '2', '2'] },
  ];

  // Iranian plate is 8 chars: [2 digits][letter][3 digits][2 digits].
  // Rahkaran's own "وسیله حمل" search expects the letter stripped and
  // the remaining digits written as "{first2}{middle3}/{last2}" (e.g.
  // "13373/64") - see the project chat for how this was confirmed.
  function formatPlateShort(chars) {
    const first5 = chars[0] + chars[1] + chars[3] + chars[4] + chars[5];
    const last2 = chars[6] + chars[7];
    return `${first5}/${last2}`;
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

  function buildOverlay(anchorInput, onPick) {
    const existing = document.getElementById('ri-lpr-overlay');
    if (existing) existing.remove();

    const box = document.createElement('div');
    box.id = 'ri-lpr-overlay';
    box.className = 'ri-lpr-overlay';

    const rect = anchorInput.getBoundingClientRect();
    box.style.top = `${rect.bottom + window.scrollY}px`;
    box.style.left = `${rect.left + window.scrollX}px`;
    box.style.width = `${Math.max(rect.width, 200)}px`;

    const title = document.createElement('div');
    title.className = 'ri-lpr-overlay-title';
    title.textContent = 'پلاک‌های شناسایی‌شده (آزمایشی)';
    box.appendChild(title);

    if (MOCK_DETECTED_PLATES.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'ri-lpr-overlay-empty';
      empty.textContent = 'در حال حاضر پلاکی شناسایی نشده';
      box.appendChild(empty);
    }

    MOCK_DETECTED_PLATES.forEach((plate) => {
      const item = document.createElement('div');
      item.className = 'ri-lpr-overlay-item';
      item.textContent = formatPlateShort(plate.chars);
      item.addEventListener('click', () => {
        box.remove();
        onPick(plate);
      });
      box.appendChild(item);
    });

    document.body.appendChild(box);

    function closeOnOutsideClick(e) {
      if (!box.contains(e.target) && e.target !== anchorInput) {
        box.remove();
        document.removeEventListener('click', closeOnOutsideClick, true);
      }
    }
    setTimeout(() => document.addEventListener('click', closeOnOutsideClick, true), 0);
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

  function initPermitPage(config) {
    const input = document.getElementById(config.vehicleInputId);
    if (!input) return; // this frame isn't showing the field right now - nothing to do

    input.addEventListener('focus', () => {
      buildOverlay(input, (plate) => {
        const shortPlate = formatPlateShort(plate.chars);
        typeIntoField(input, shortPlate, () => {
          waitForDropdownResult(config.vehicleDropdownId, (itemCount) => {
            if (itemCount === 0) {
              console.log('[RI-LPR] no matching vehicle for', shortPlate, '- opening the new-vehicle form');
              chrome.storage.local.set({ [STORAGE_KEY_PENDING_PLATE]: shortPlate }, () => {
                clickNewButton(config.vehicleDropdownId);
              });
            } else {
              console.log(`[RI-LPR] ${itemCount} matching vehicle(s) found for`, shortPlate, '- pick one from Rahkaran\'s own list');
            }
          });
        });
      });
    });

    function captureAndLog() {
      const data = {};
      for (const [key, id] of Object.entries(config.captureFieldIds)) {
        const el = document.getElementById(id);
        data[key] = el ? el.value : null;
      }
      console.log('[RI-LPR] captured on Save (not sent anywhere yet - backend not built):', data);
      // TODO: once the backend exists, POST `data` to it here.
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
