import asyncio
import time
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, BrowserContext, Page


class Browser:
    """Playwright browser control with persistent context."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        """Initialize Playwright browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

    async def stop(self):
        """Clean up browser resources."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def open(self, url: str = "about:blank", new_tab: bool = False) -> Dict[str, Any]:
        """Open a URL in the browser."""
        try:
            if new_tab and self.page:
                await self.page.evaluate("window.open('', '_blank')")
                await self.page.bring_to_front()
            await self.page.goto(url, wait_until="networkidle")
            return {"status": "success", "message": f"Opened {url}", "url": url}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open {url}: {str(e)}"}

    async def go_to(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL."""
        return await self.open(url)

    async def search(self, query: str) -> Dict[str, Any]:
        """Search for a query."""
        try:
            await self.page.goto(f"https://www.google.com/search?q={query}", wait_until="networkidle")
            # Try to get search results
            results = await self.page.locator(".g").all_text_contents()
            return {"status": "success", "message": f"Searched for: {query}", "results": results[:10]}
        except Exception as e:
            return {"status": "error", "message": f"Search failed: {str(e)}"}

    async def click(self, selector: str) -> Dict[str, Any]:
        """Click on an element by selector."""
        try:
            await self.page.click(selector)
            return {"status": "success", "message": f"Clicked: {selector}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to click: {str(e)}"}

    async def type(self, selector: str, text: str) -> Dict[str, Any]:
        """Type text into an element."""
        try:
            await self.page.fill(selector, text)
            return {"status": "success", "message": f"Typed into {selector}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to type: {str(e)}"}

    async def back(self) -> Dict[str, Any]:
        """Go back in browser history."""
        try:
            await self.page.go_back()
            return {"status": "success", "message": "Went back"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to go back: {str(e)}"}

    async def forward(self) -> Dict[str, Any]:
        """Go forward in browser history."""
        try:
            await self.page.go_forward()
            return {"status": "success", "message": "Went forward"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to go forward: {str(e)}"}

    async def new_tab(self) -> Dict[str, Any]:
        """Open a new tab."""
        try:
            await self.page.context.new_page()
            return {"status": "success", "message": "New tab opened"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open new tab: {str(e)}"}

    async def close_tab(self) -> Dict[str, Any]:
        """Close current tab."""
        try:
            await self.page.close()
            return {"status": "success", "message": "Tab closed"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to close tab: {str(e)}"}

    async def list_tabs(self) -> Dict[str, Any]:
        """List all tab URLs."""
        try:
            pages = self.context.pages
            tabs = [{"index": i, "url": page.url} for i, page in enumerate(pages)]
            return {"status": "success", "tabs": tabs}
        except Exception as e:
            return {"status": "error", "message": f"Failed to list tabs: {str(e)}"}

    async def extract(self, selector: str) -> Dict[str, Any]:
        """Extract text from an element."""
        try:
            element = self.page.locator(selector)
            text = await element.text_content()
            return {"status": "success", "text": text, "selector": selector}
        except Exception as e:
            return {"status": "error", "message": f"Failed to extract: {str(e)}"}

    async def get_page_text(self) -> Dict[str, Any]:
        """Get all page text."""
        try:
            text = await self.page.text_content()
            return {"status": "success", "text": text[:5000] if text else ""}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get page text: {str(e)}"}

    async def screenshot(self) -> Dict[str, Any]:
        """Take a screenshot."""
        try:
            import os
            from system_ops import WORK_DIR
            img_dir = os.path.join(WORK_DIR, "images")
            os.makedirs(img_dir, exist_ok=True)
            filename = f"browser_{int(time.time())}.png"
            path = os.path.join(img_dir, filename)
            await self.page.screenshot(path=path)
            return {"status": "success", "message": f"Screenshot saved: {path}", "path": path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to screenshot: {str(e)}"}

    async def wait(self, selector: str = None, timeout: int = 5000) -> Dict[str, Any]:
        """Wait for an element or timeout."""
        try:
            if selector:
                await self.page.wait_for_selector(selector, timeout=timeout)
            else:
                await asyncio.sleep(timeout / 1000)
            return {"status": "success", "message": "Wait completed"}
        except Exception as e:
            return {"status": "error", "message": f"Wait failed: {str(e)}"}