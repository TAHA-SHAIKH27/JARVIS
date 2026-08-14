import React from 'react';
import { Smartphone } from 'lucide-react';

export default function PhonePanel() {
  return (
    <div className="phone-mirror-panel">
      <div className="phone-mirror-inner">
        <div className="phone-mirror-label">
          <Smartphone size={12} style={{ opacity: 0.5 }} />
          <span>PHONE MIRROR</span>
        </div>
        <div className="phone-mirror-frame">
          {/* ws-scrcpy streams to port 8080 — show its stream page directly */}
          <iframe
            src="http://localhost:8080"
            title="Phone Mirror Stream"
            allow="fullscreen"
            style={{ width: '100%', height: '100%', border: 'none', borderRadius: '6px', background: '#050a10' }}
          />
        </div>
      </div>
    </div>
  );
}
