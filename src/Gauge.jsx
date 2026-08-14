import React from 'react';

export default function Gauge({ label, value }) {
  const GAUGE_R = 30;
  const GAUGE_C = 2 * Math.PI * GAUGE_R;
  const v = Math.max(0, Math.min(100, value || 0));
  const offset = GAUGE_C - (v / 100) * GAUGE_C;
  const cls = v > 88 ? 'crit' : v > 70 ? 'warn' : '';
  return (
    <div className="gauge">
      <div className="gauge-ring">
        <svg width="76" height="76" viewBox="0 0 76 76">
          <circle className="track" cx="38" cy="38" r={GAUGE_R} fill="none" strokeWidth="5" />
          <circle
            className={`fill ${cls}`}
            cx="38"
            cy="38"
            r={GAUGE_R}
            fill="none"
            strokeWidth="5"
            strokeDasharray={GAUGE_C}
            strokeDashoffset={offset}
            strokeLinecap="round"
          />
        </svg>
        <div className="gauge-value">{Math.round(v)}%</div>
      </div>
      <div className="gauge-name">{label}</div>
    </div>
  );
}
