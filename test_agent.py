import asyncio
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from backend.agent.planner import Planner, _rule_based_plan
from backend.agent.state import TaskState

async def test_planner():
    print("Testing Planner...")
    planner = Planner()
    state = TaskState()
    
    # Test rule-based planner directly
    print("\n=== Rule-based plans ===")
    tests = [
        'open notepad and type hello',
        'calculate 125 * 48',
        'search for OpenAI website',
        'create folder JARVIS_TEST on Desktop',
        'research National Science Day and create Word document'
    ]
    
    for task in tests:
        print(f"\nTask: {task}")
        actions = _rule_based_plan(task)
        for i, a in enumerate(actions):
            print(f"  {i+1}. {a['type']}: {a.get('description', '')}")

    # Test full planner with LLM (short timeout)
    print("\n=== LLM Planner (with fallback) ===")
    try:
        actions = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, planner.plan_task, 'open notepad and type hello', state),
            timeout=10.0
        )
        print('LLM Plan:')
        for i, a in enumerate(actions):
            print(f"  {i+1}. {a['type']}: {a.get('description', '')}")
    except asyncio.TimeoutError:
        print('LLM Planner TIMEOUT (expected - uses rule-based fallback)')

asyncio.run(test_planner())