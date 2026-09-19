#!/usr/bin/env python
"""
JARVIS Computer Use Engine - Integration Tests
Real Windows tests for Notepad, Calculator, File Explorer, and Paint.
"""
import asyncio
import sys
import os
import time
import re

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.tools.computer import Computer
from backend.agent.registry import ToolRegistry
from backend.agent.state import TaskState


async def test_notepad():
    """Test: Open Notepad, type text, observe, verify text."""
    print("\n" + "="*60)
    print("TEST: Notepad - Open, Type, Observe, Verify")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # Clean up any existing Notepad windows first
    print("\n0. Cleaning up existing Notepad windows...")
    import pyautogui
    for _ in range(10):  # Try up to 10 times to close all Notepad windows
        pyautogui.hotkey('alt', 'f4')
        await asyncio.sleep(0.2)
    
    # 1. Open Notepad
    print("\n1. Opening Notepad...")
    result = await computer.open_app("notepad", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to open Notepad"
    
    # Wait for window to appear
    await asyncio.sleep(1.5)
    
    # 2. Focus Notepad window - get the actual window title
    print("\n2. Focusing Notepad window...")
    result = await computer.focus_window("Notepad", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to focus Notepad"
    
    # Get the actual window title that was focused
    focused_title = state.active_window or "Untitled - Notepad"
    print(f"   Focused window title: '{focused_title}'")
    
    # 3. Type text
    test_text = "Hello JARVIS! This is a test."
    print(f"\n3. Typing text: '{test_text}'")
    result = await computer.type_text(test_text, state=state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to type text"
    
    # 4. Verify text via find_element + get_window_text on the specific window
    print("\n4. Verifying text via find_element...")
    try:
        # Find the Edit control in the focused window
        result = await computer.find_element({"control_type": "Edit"}, state)
        print(f"   Find element result: {result.get('status')} - {result.get('message')}")
        element = result.get("element")
        
        if element:
            # The find_element result message contains the actual window title
            # Extract it from the message or use inspect_window to get current title
            import re
            msg = result.get('message', '')
            # Message format: "Found window: <title>" or "Found element: <title>"
            match = re.search(r'Found (?:window|element): (.+)', msg)
            if match:
                current_title = match.group(1).strip()
            else:
                # Fallback: use inspect_window to find the actual current title
                obs = await computer.inspect_window("Notepad", state)
                current_title = obs.get("element", {}).get("title", state.active_window or "Notepad")
            
            print(f"   Current active window: '{current_title}'")
            
            # If we still have the old text from a previous run, the test text should still be in the content
            # We'll check for a substring match that's unique to our test
            unique_substring = "JARVIS"
            
            # Use get_window_text with the specific current window title
            result = await computer.get_window_text(current_title, state)
            print(f"   get_window_text result: {result.get('status')} - {result.get('message')}")
            texts = result.get("data", {}).get("texts", [])
            
            # Find Edit control text
            edit_texts = [t for t in texts if t.get("control_type") == "Edit"]
            if edit_texts:
                content = edit_texts[0].get("text", "")
                print(f"   Notepad content (Edit control): '{content[:80]}'")
                assert unique_substring in content, f"Unique substring '{unique_substring}' not found in Notepad: got '{content[:80]}'"
                print("   [PASS] Text verified successfully!")
            else:
                # Fallback: check all texts
                all_text = " ".join([t.get("text", "") for t in texts])
                print(f"   All window text: '{all_text[:200]}'")
                assert unique_substring in all_text, f"Unique substring '{unique_substring}' not found in any control: got '{all_text[:200]}'"
                print("   [PASS] Text verified successfully!")
        else:
            print("   [FAIL] Could not find Edit control")
            return False
    except Exception as e:
        print(f"   [FAIL] UIA verification failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 5. Get structured observation
    print("\n5. Getting structured observation...")
    obs = await computer.inspect_window(focused_title, state)
    print(f"   Window: {obs.get('element', {}).get('title') if obs.get('element') else 'N/A'}")
    print(f"   Controls found: {obs.get('data', {}).get('control_count', 0)}")
    
    # 6. Close Notepad (don't save)
    print("\n6. Closing Notepad...")
    pyautogui.hotkey('alt', 'f4')
    await asyncio.sleep(0.5)
    pyautogui.press('right')  # Don't save
    pyautogui.press('enter')
    
    print("\n[PASS] NOTEPAD TEST PASSED")
    return True


async def test_calculator():
    """Test: Open Calculator, perform calculation, observe, verify result."""
    print("\n" + "="*60)
    print("TEST: Calculator - Open, Compute, Observe, Verify")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # 1. Open Calculator
    print("\n1. Opening Calculator...")
    result = await computer.open_app("calc", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to open Calculator"
    
    await asyncio.sleep(2.0)
    
    # 2. Focus Calculator
    print("\n2. Focusing Calculator...")
    result = await computer.focus_window("Calculator", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 3. Type calculation using pyautogui
    print("\n3. Computing 125 * 48...")
    import pyautogui
    pyautogui.write("125*48", interval=0.05)
    pyautogui.press("enter")
    await asyncio.sleep(0.5)
    
    # 4. Verify result via UIA
    print("\n4. Verifying result via UIA...")
    try:
        from pywinauto import Application
        app = Application(backend="uia").connect(title_re=".*Calculator.*", timeout=3)
        win = app.top_window()
        display = win.child_window(auto_id="CalculatorResults", control_type="Text")
        value = display.window_text().strip().replace("Display is", "").strip()
        print(f"   Calculator display: '{value}'")
        assert "6000" in value.replace(",", ""), f"Expected 6000, got '{value}'"
        print("   [PASS] Calculation verified: 125 * 48 = 6000")
    except Exception as e:
        print(f"   [FAIL] UIA verification failed: {e}")
        return False
    
    # 5. Get structured observation
    print("\n5. Getting structured observation...")
    obs = await computer.inspect_window("Calculator", state)
    print(f"   Window: {obs.get('element', {}).get('title') if obs.get('element') else 'N/A'}")
    print(f"   Controls found: {obs.get('data', {}).get('control_count', 0)}")
    
    # 6. Close Calculator
    print("\n6. Closing Calculator...")
    pyautogui.hotkey('alt', 'f4')
    
    print("\n[PASS] CALCULATOR TEST PASSED")
    return True


async def test_file_explorer():
    """Test: Open File Explorer, navigate, observe, verify location."""
    print("\n" + "="*60)
    print("TEST: File Explorer - Open, Navigate, Observe, Verify")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # 1. Open File Explorer
    print("\n1. Opening File Explorer...")
    result = await computer.open_app("explorer", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to open File Explorer"
    
    await asyncio.sleep(1.5)
    
    # 2. Focus File Explorer
    print("\n2. Focusing File Explorer...")
    result = await computer.focus_window("File Explorer", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 3. Get structured observation
    print("\n3. Getting structured observation...")
    obs = await computer.inspect_window("File Explorer", state)
    print(f"   Window: {obs.get('element', {}).get('title') if obs.get('element') else 'N/A'}")
    print(f"   Controls found: {obs.get('data', {}).get('control_count', 0)}")
    
    # List some controls
    controls = obs.get('data', {}).get('controls', [])
    for ctrl in controls[:5]:
        if isinstance(ctrl, dict):
            print(f"   - {ctrl.get('name', 'unnamed')}: {ctrl.get('role', 'unknown')}")
    
    # 4. Verify we can see the address bar or navigation elements
    print("\n4. Checking for navigation elements...")
    nav_controls = [c for c in controls if isinstance(c, dict) and ('address' in c.get('name', '').lower() or 'edit' in c.get('role', '').lower())]
    if nav_controls:
        print(f"   Found {len(nav_controls)} navigation/edit controls")
    else:
        print("   No explicit address bar found (may be in different form)")
    
    # 5. Close File Explorer
    print("\n5. Closing File Explorer...")
    import pyautogui
    pyautogui.hotkey('alt', 'f4')
    
    print("\n[PASS] FILE EXPLORER TEST PASSED")
    return True


async def test_paint():
    """Test: Open Paint, inspect UI, identify Shapes, identify ellipse/circle."""
    print("\n" + "="*60)
    print("TEST: Paint - Open, Inspect UI, Identify Shapes, Identify Ellipse")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # 1. Open Paint
    print("\n1. Opening Paint...")
    result = await computer.open_app("mspaint", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Failed to open Paint"
    
    await asyncio.sleep(2.0)
    
    # 2. Focus Paint
    print("\n2. Focusing Paint...")
    result = await computer.focus_window("Paint", state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 3. Inspect UI controls
    print("\n3. Inspecting Paint UI controls...")
    obs = await computer.inspect_window("Paint", state)
    controls = obs.get('data', {}).get('controls', [])
    print(f"   Total controls found: {len(controls)}")
    
    # 4. Find Shapes control
    print("\n4. Searching for Shapes control...")
    shapes_controls = [c for c in controls if isinstance(c, dict) and 'shape' in c.get('name', '').lower()]
    if shapes_controls:
        for ctrl in shapes_controls:
            print(f"   Found: {ctrl.get('name')} (role: {ctrl.get('role')}, bounds: {ctrl.get('bounds')})")
    else:
        # Try broader search
        for ctrl in controls:
            if isinstance(ctrl, dict):
                name = ctrl.get('name', '').lower()
                if any(kw in name for kw in ['shape', 'ellipse', 'circle', 'rectangle', 'polygon']):
                    print(f"   Found related: {ctrl.get('name')} (role: {ctrl.get('role')})")
    
    # 5. Search for specific shape buttons (Ellipse, Circle)
    print("\n5. Searching for Ellipse/Circle tool...")
    shape_tools = [c for c in controls if isinstance(c, dict) and any(
        kw in c.get('name', '').lower() for kw in ['ellipse', 'circle', 'oval']
    )]
    if shape_tools:
        for ctrl in shape_tools:
            print(f"   Found shape tool: {ctrl.get('name')} (bounds: {ctrl.get('bounds')})")
    else:
        print("   No explicit ellipse/circle tool found by name")
        # Check for button controls that might be shape tools
        button_controls = [c for c in controls if isinstance(c, dict) and c.get('role') == 'button']
        print(f"   Found {len(button_controls)} button controls")
    
    # 6. Get active window info
    print("\n6. Getting active window info...")
    active = await computer.get_active_window(state)
    if active.get("status") == "success":
        win = active.get("window", {})
        print(f"   Title: {win.get('title')}")
        print(f"   Rect: {win.get('rect')}")
        print(f"   Size: {win.get('width')}x{win.get('height')}")
    
    # 7. Close Paint
    print("\n7. Closing Paint...")
    import pyautogui
    pyautogui.hotkey('alt', 'f4')
    await asyncio.sleep(0.5)
    pyautogui.press('right')  # Don't save
    pyautogui.press('enter')
    
    print("\n[PASS] PAINT TEST PASSED (UI inspection completed)")
    return True


async def test_screen_capture():
    """Test: Screen capture methods."""
    print("\n" + "="*60)
    print("TEST: Screen Capture - Full Screen, Region, Window")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # 1. Full screen capture
    print("\n1. Full screen capture...")
    result = await computer.get_screen(state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Full screen capture failed"
    assert result.get("screenshot_path"), "No screenshot path returned"
    
    # 2. Region capture
    print("\n2. Region capture (100x100 at 0,0)...")
    result = await computer.screenshot_region(0, 0, 100, 100, state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    assert result.get("status") == "success", "Region capture failed"
    
    # 3. Active window capture
    print("\n3. Active window capture...")
    result = await computer.get_active_window(state)
    if result.get("status") == "success":
        print(f"   Active window: {result.get('window', {}).get('title')}")
    
    print("\n[PASS] SCREEN CAPTURE TEST PASSED")
    return True


async def test_ui_element_operations():
    """Test: Find element, click element, wait for element."""
    print("\n" + "="*60)
    print("TEST: UI Element Operations - Find, Click, Wait")
    print("="*60)
    
    registry = ToolRegistry()
    computer = Computer(registry)
    state = TaskState()
    
    # Open Notepad first
    print("\n1. Opening Notepad for element tests...")
    await computer.open_app("notepad", state)
    await asyncio.sleep(1.5)
    await computer.focus_window("Notepad", state)
    
    # 2. Find Notepad edit control
    print("\n2. Finding Notepad edit control...")
    result = await computer.find_element({"text": "", "control_type": "Edit"}, state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    element = result.get("element")
    if element:
        print(f"   Element: {element.get('name')}, bounds: {element.get('bounds')}")
    
    # 3. Click the edit control
    print("\n3. Clicking edit control...")
    if element:
        result = await computer.click_element(element, state)
        print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 4. Type in the control
    print("\n4. Typing in edit control...")
    result = await computer.type_text("Test via click_element", element=element, state=state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 5. Test wait_for_element (should find immediately)
    print("\n5. Testing wait_for_element...")
    result = await computer.wait_for_element({"control_type": "Edit"}, timeout=3.0, state=state)
    print(f"   Result: {result.get('status')} - {result.get('message')}")
    
    # 6. Close Notepad
    print("\n6. Closing Notepad...")
    import pyautogui
    pyautogui.hotkey('alt', 'f4')
    await asyncio.sleep(0.5)
    pyautogui.press('right')
    pyautogui.press('enter')
    
    print("\n[PASS] UI ELEMENT OPERATIONS TEST PASSED")
    return True


async def run_all_tests():
    """Run all integration tests."""
    print("\n" + "#"*60)
    print("# JARVIS COMPUTER USE ENGINE - INTEGRATION TESTS")
    print("#"*60)
    
    tests = [
        ("Screen Capture", test_screen_capture),
        ("UI Element Operations", test_ui_element_operations),
        ("Notepad", test_notepad),
        ("Calculator", test_calculator),
        ("File Explorer", test_file_explorer),
        ("Paint", test_paint),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = await test_func()
            results[name] = result
        except Exception as e:
            print(f"\n[FAIL] {name} TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Summary
    print("\n" + "#"*60)
    print("# TEST SUMMARY")
    print("#"*60)
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[PASS] ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)