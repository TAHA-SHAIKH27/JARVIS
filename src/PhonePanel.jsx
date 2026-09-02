import React, { useEffect, useState, useCallback } from 'react';
import { Smartphone, RefreshCw } from 'lucide-react';

// ws-scrcpy's internal ADB proxy port (fixed, baked into its server — see
// ws-scrcpy/src/common/Constants.ts SERVER_PORT).
const WS_SCRCPY_ADB_PORT = 8886;
const WS_SCRCPY_HOST = 'localhost:8080';

function buildStreamUrl(udid) {
  const wsUrl = new URL(`ws://${WS_SCRCPY_HOST}/`);
  wsUrl.searchParams.set('action', 'proxy-adb');
  wsUrl.searchParams.set('remote', `tcp:${WS_SCRCPY_ADB_PORT}`);
  wsUrl.searchParams.set('udid', udid);

  const hash = new URLSearchParams({
    action: 'stream',
    udid,
    // MsePlayer fills its container natively via CSS; WebCodecsPlayer
    // instead CSS-transforms down to a hardcoded small default unless
    // pre-configured, which renders tiny in a corner.
    player: 'mse',
    ws: wsUrl.toString(),
    fitToScreen: 'true',
  });

  return `http://${WS_SCRCPY_HOST}/#!${hash.toString()}`;
}

export default function PhonePanel() {
  const [streamUrl, setStreamUrl] = useState(null);
  const [status, setStatus] = useState('connecting'); // connecting | ready | no-device | offline

  const connect = useCallback(() => {
    setStatus('connecting');
    setStreamUrl(null);
    fetch('/api/phone/devices')
      .then(r => r.json())
      .then(data => {
        const dev = (data.devices || []).find(d => d.status === 'device');
        if (!dev) { setStatus('no-device'); return; }
        setStreamUrl(buildStreamUrl(dev.serial));
        setStatus('ready');
      })
      .catch(() => setStatus('offline'));
  }, []);

  useEffect(() => { connect(); }, [connect]);

  const statusMessage = {
    connecting: 'Connecting to device…',
    'no-device': 'No authorized Android device found. Check USB/ADB.',
    offline: 'ws-scrcpy server unreachable on :8080.',
  }[status];

  return (
    <div className="phone-mirror-panel">
      <div className="phone-mirror-inner">
        <div className="phone-mirror-label">
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Smartphone size={12} style={{ opacity: 0.5 }} />
            <span>PHONE MIRROR</span>
          </span>
          <button
            className="icon-btn"
            style={{ width: 20, height: 20, border: 'none' }}
            onClick={connect}
            title="Reconnect"
            aria-label="Reconnect phone mirror"
          >
            <RefreshCw size={11} />
          </button>
        </div>
        <div className="phone-mirror-frame">
          {status === 'ready' && streamUrl ? (
            <iframe
              key={streamUrl}
              src={streamUrl}
              title="Phone Mirror Stream"
              allow="fullscreen"
              style={{ width: '100%', height: '100%', border: 'none', borderRadius: '6px', background: '#050a10' }}
            />
          ) : (
            <div style={{
              color: 'var(--text-faint)', fontSize: 10, fontFamily: 'var(--font-mono)',
              padding: 10, textAlign: 'center', height: '100%',
              display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
              {statusMessage}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
