import sys
for mod in list(sys.modules.keys()):
    if 'planner' in mod or 'agent' in mod:
        del sys.modules[mod]

sys.path.insert(0, '.')
import backend.agent.planner as planner_module

task = 'research National Science Day and create Word document'
task_lower = task.lower()
print('task_lower:', repr(task_lower))
print('research in task_lower:', 'research' in task_lower)
print('word in task_lower:', 'word' in task_lower)

# Test the exact condition
if 'research' in task_lower and ('word' in task_lower or 'document' in task_lower or 'docx' in task_lower):
    print('Condition MATCHED')
    import re
    topic_match = re.search(r'research\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)', task_lower)
    print('topic_match:', topic_match)
    if topic_match:
        print('group(1):', topic_match.group(1))
else:
    print('Condition NOT matched')