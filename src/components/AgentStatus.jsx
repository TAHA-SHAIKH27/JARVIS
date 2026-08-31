import React from 'react';
import { Check, X, Clock, AlertCircle } from 'lucide-react';

function AgentStatus({ status }) {
  const statusMap = {
    ready: { color: 'var(--green)', icon: Check },
    planning: { color: 'var(--cyan)', icon: Clock },
    executing: { color: 'var(--orange)', icon: Clock },
    observing: { color: 'var(--cyan)', icon: Clock },
    completed: { color: 'var(--green)', icon: Check },
    error: { color: 'var(--red)', icon: AlertCircle },
  };

  const s = statusMap[status] || statusMap.ready;
  return (
    <div className="agent-status-tooltip">
      <span className="agent-status-dot" style={{ color: s.color }} />
      <span>{status}</span>
    </div>
  )
}

AgentStatus.defaultProps = { status: 'ready' }

export default AgentStatus