import React from 'react';
import Gauge from './Gauge'; // We'll create a separate Gauge component file

export default function Telemetry({ stats }) {
  return (
    <div className="hud-telemetry panel">
      <p className="panel-label"><span>System Telemetry</span></p>
      <div className="gauge-row">
        <Gauge label="CPU" value={stats.cpu} />
        <Gauge label="Memory" value={stats.memory} />
        <Gauge label="Disk" value={stats.disk} />
      </div>
    </div>
  );
}
