/* ============================================================
   bill-qr.js — QR scanner (USB/manual + camera)
   Depends on: bill-state.js, bill-items.js
   ============================================================ */

function openQrScanModal() {
  qrScanLock = false;
  document.getElementById('qr-scan-error').textContent = '';
  document.getElementById('qr-manual-input').value = '';
  document.getElementById('qr-reader').style.display    = 'none';
  document.getElementById('btn-stop-camera').style.display = 'none';
  document.getElementById('btn-start-camera').style.display = '';
  document.getElementById('qr-scan-modal').classList.remove('hidden');
  document.getElementById('qr-manual-input').focus();
}

function closeQrScanModal() {
  stopCamera();
  document.getElementById('qr-scan-modal').classList.add('hidden');
}

// ---- Manual / USB scanner input ----
async function applyManualQr() {
  const raw = document.getElementById('qr-manual-input').value.trim();
  if (!raw) return;

  let text = raw;
  if (!raw.startsWith('inv:') && !raw.startsWith('cs:')) text = 'inv:' + raw;

  document.getElementById('qr-manual-input').value = '';
  closeQrScanModal();
  await processQrText(text);
}

// ---- Camera (only works on HTTPS / localhost) ----
function startCamera() {
  document.getElementById('qr-scan-error').textContent = '';

  if (typeof Html5Qrcode === 'undefined') {
    document.getElementById('qr-scan-error').textContent =
      'QR library not loaded — check internet connection.';
    return;
  }
  if (!window.isSecureContext) {
    document.getElementById('qr-scan-error').textContent =
      'Camera requires HTTPS. Use a USB scanner or type the item code instead.';
    return;
  }

  document.getElementById('btn-start-camera').style.display = 'none';
  document.getElementById('qr-reader').style.display = '';
  document.getElementById('btn-stop-camera').style.display = '';

  html5QrScanner = new Html5Qrcode('qr-reader');
  Html5Qrcode.getCameras().then(cameras => {
    if (!cameras || !cameras.length) {
      document.getElementById('qr-scan-error').textContent = 'No camera found on this device.';
      stopCamera();
      return;
    }
    const cameraId = cameras[cameras.length - 1].id;
    html5QrScanner.start(
      cameraId,
      { fps: 10, qrbox: { width: 220, height: 220 } },
      onQrScanned,
      () => {}
    ).catch(err => {
      document.getElementById('qr-scan-error').textContent = 'Camera error: ' + err;
      stopCamera();
    });
  }).catch(err => {
    document.getElementById('qr-scan-error').textContent =
      'Camera access denied. Use USB scanner or type the item code.';
    stopCamera();
  });
}

function stopCamera() {
  if (html5QrScanner) {
    html5QrScanner.stop().catch(() => {}).finally(() => {
      html5QrScanner.clear();
      html5QrScanner = null;
    });
  }
  const readerEl  = document.getElementById('qr-reader');
  const startBtn  = document.getElementById('btn-start-camera');
  const stopBtn   = document.getElementById('btn-stop-camera');
  if (readerEl) readerEl.style.display = 'none';
  if (startBtn) startBtn.style.display = '';
  if (stopBtn)  stopBtn.style.display  = 'none';
}

async function onQrScanned(text) {
  if (qrScanLock) return;   // ignore duplicate fires from the same QR code
  qrScanLock = true;

  if (html5QrScanner) {
    await html5QrScanner.stop().catch(() => {});
    html5QrScanner = null;
  }
  closeQrScanModal();
  await processQrText(text);
}

// ---- Shared QR processing (used by both modes) ----
async function processQrText(text) {
  if (text.startsWith('inv:')) {
    const code = text.slice(4);
    const url = /^\d+$/.test(code)
      ? `/api/inventory/${code}`
      : `/api/inventory/by-code/${encodeURIComponent(code)}`;
    try {
      const res = await fetch(url);
      if (!res.ok) { alert('Inventory item not found (' + code + ').'); return; }
      const item = await res.json();
      await fillRowFromInventoryItem(item);
    } catch (e) {
      alert('Failed to fetch inventory item: ' + e.message);
    }
  } else if (text.startsWith('cs:')) {
    try {
      const data = JSON.parse(text.slice(3));
      await fillRowFromCurrentStock(data);
    } catch (e) {
      alert('Invalid current stock QR code.');
    }
  } else {
    alert('Unrecognised QR. Expected an Inventory or Current Stock QR from this system.');
  }
}

document.getElementById('qr-scan-modal').addEventListener('click', function(e) {
  if (e.target === this) closeQrScanModal();
});
