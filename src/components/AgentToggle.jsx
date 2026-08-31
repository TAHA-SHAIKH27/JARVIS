import React from 'react';
import { Brain, X } from 'lucide-react';

function AgentToggle({ agentMode, onToggle }) {
  return (
    <button
      className="agent-toggle-btn"
      onClick={onToggle}
      title={agentMode ? 'Exit Agent Mode' : 'Enter Agent Mode'}
      aria-label={agentMode ? 'Exit Agent Mode' : 'Enter Agent Mode'}
    >
      {agentMode ? <X size={16} /> : <Brain size={16} />}
    </button>
  )
}

AgentToggle.defaultProps = { agentMode: false }

export default AgentToggle