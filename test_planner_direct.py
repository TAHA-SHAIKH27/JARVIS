import sys
sys.path.insert(0, '.')
from backend.agent.planner import _rule_based_plan

task = 'research National Science Day and create Word document'
actions = _rule_based_plan(task)
print('Task:', task)
for i, a in enumerate(actions):
    print('  {} {}: query={} desc={}'.format(i+1, a["type"], a.get("query", ""), a.get("description", "")))