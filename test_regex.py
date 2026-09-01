import re
task = 'research National Science Day and create Word document'
task_lower = task.lower()

# Exact pattern from planner.py
pattern = r'research\s+(.+?)\s+(?:and\s+create|from\s+multiple|from\s+websites?|into\s+word|\s+create)'
m = re.search(pattern, task_lower)
print('Pattern:', pattern)
print('Match:', m.group(1) if m else 'None')

print()
print('task_lower:', repr(task_lower))
print('Contains "and create":', 'and create' in task_lower)
print('Contains "and create word":', 'and create word' in task_lower)