#!/usr/bin/env python
"""
Test script for the improved JARVIS agent architecture.
Tests different task types to verify the architecture works correctly.
"""
import asyncio
import json
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.agent.state import TaskState
from backend.agent.planner import Planner
from backend.agent.core import AgentCore


async def test_planner():
    """Test the planner with different task types."""
    print("=" * 60)
    print("TESTING PLANNER")
    print("=" * 60)
    
    planner = Planner()
    
    test_tasks = [
        "Open Notepad and type 'Hello World'",
        "Calculate 125 * 48",
        "Research Python history and create a Word document",
        "Search for the weather in London",
        "Create a folder named 'TestFolder' on Desktop",
    ]
    
    for task in test_tasks:
        print(f"\n--- Task: {task} ---")
        state = TaskState()
        try:
            actions = planner.plan_task(task, state)
            print(f"Goal: {state.interpreted_goal}")
            print(f"Task Type: {state.task_type.value}")
            print(f"Plan Valid: {state.plan.is_valid}")
            print(f"Validation Errors: {state.plan.validation_errors}")
            print(f"Actions ({len(actions)}):")
            for i, action in enumerate(actions):
                print(f"  {i+1}. [{action.type}] {action.description}")
                print(f"      Params: {action.parameters}")
                print(f"      Depends on: {action.depends_on}")
                print(f"      Produces: {action.produces}")
                print(f"      Consumes: {action.consumes}")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()


async def test_agent_core_simple():
    """Test AgentCore with a simple task."""
    print("\n" + "=" * 60)
    print("TESTING AGENT CORE - Simple Task")
    print("=" * 60)
    
    agent = AgentCore()
    state = TaskState()
    
    # Use a simple task that doesn't require external APIs
    task = "Open Notepad"
    
    print(f"Task: {task}")
    events = []
    
    async def collect_events(event_queue):
        while True:
            event = await event_queue.get()
            if event is None:
                break
            events.append(event)
            print(f"  EVENT: {event['type']} - {event['message']}")
    
    event_queue = asyncio.Queue()
    collector = asyncio.create_task(collect_events(event_queue))
    
    try:
        result = await agent.process(task, state, event_queue)
        await collector
        print(f"\nResult: {result.get('status')}")
        print(f"Speak: {result.get('speak')}")
        print(f"Completed steps: {result.get('completed_steps')}")
        print(f"Errors: {result.get('errors')}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        collector.cancel()


async def test_agent_core_sequential():
    """Test AgentCore with a sequential task."""
    print("\n" + "=" * 60)
    print("TESTING AGENT CORE - Sequential Task")
    print("=" * 60)
    
    agent = AgentCore()
    state = TaskState()
    
    task = "Open Notepad and type 'Test message'"
    
    print(f"Task: {task}")
    events = []
    
    async def collect_events(event_queue):
        while True:
            event = await event_queue.get()
            if event is None:
                break
            events.append(event)
            print(f"  EVENT: {event['type']} - {event['message']}")
    
    event_queue = asyncio.Queue()
    collector = asyncio.create_task(collect_events(event_queue))
    
    try:
        result = await agent.process(task, state, event_queue)
        await collector
        print(f"\nResult: {result.get('status')}")
        print(f"Speak: {result.get('speak')}")
        print(f"Completed steps: {result.get('completed_steps')}")
        print(f"Errors: {result.get('errors')}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        collector.cancel()


async def test_goal_understanding():
    """Test goal understanding."""
    print("\n" + "=" * 60)
    print("TESTING GOAL UNDERSTANDING")
    print("=" * 60)
    
    planner = Planner()
    
    test_tasks = [
        "Research the history of Python and create a Word document",
        "Calculate 25 * 40",
        "Open Chrome and search for AI news",
        "Create a folder called 'Projects' on my Desktop",
    ]
    
    for task in test_tasks:
        print(f"\n--- Task: {task} ---")
        state = TaskState()
        try:
            goal_analysis = planner.understand_goal(task, state)
            print(f"Primary Goal: {goal_analysis.get('primary_goal')}")
            print(f"Task Type: {goal_analysis.get('task_type')}")
            print(f"Final Deliverables: {goal_analysis.get('final_deliverables')}")
            print(f"Constraints: {goal_analysis.get('constraints')}")
            print(f"Dependencies: {goal_analysis.get('dependencies')}")
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """Run all tests."""
    print("JARVIS Agent Architecture Tests")
    print("=" * 60)
    
    await test_goal_understanding()
    await test_planner()
    await test_agent_core_simple()
    await test_agent_core_sequential()
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())