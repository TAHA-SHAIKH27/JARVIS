import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, BrowserContext, Page


class Browser:
    """Playwright browser control with persistent context. headless=False so the user sees it."""

    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None

    async def start(self):
        """Initialize Playwright browser with persistent user profile to avoid CAPTCHAs."""
        self.playwright = await async_playwright().start()
        
        # Use persistent context with user data dir — reuses your Chrome profile (cookies, logins)
        # This makes Google see a "real" browser instead of a fresh automated one
        user_data_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "JARVIS", "browser_profile")
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Try to use system Chrome (has your logins) instead of Playwright's bundled Chromium
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                viewport={"width": 1280, "height": 800},
                channel="chrome",  # Use installed Chrome instead of bundled Chromium
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
        except Exception:
            # Fallback: bundled Chromium with persistent profile
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
        
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def stop(self):
        """Clean up browser resources."""
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass

    async def open(self, url: str = "about:blank", new_tab: bool = False) -> Dict[str, Any]:
        """Open a URL in the browser."""
        try:
            if new_tab and self.context:
                self.page = await self.context.new_page()
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            title = await self.page.title()
            return {"status": "success", "message": f"Opened {url}", "url": url, "title": title}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open {url}: {str(e)}"}

    async def go_to(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL."""
        return await self.open(url)

    async def get_page_title(self) -> Dict[str, Any]:
        """Get the current page title."""
        try:
            title = await self.page.title()
            url = self.page.url
            return {"status": "success", "title": title, "url": url, "message": f"Page title: {title}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get page title: {str(e)}"}

    async def search(self, query: str) -> Dict[str, Any]:
        """Search Google for a query and return result snippets."""
        try:
            encoded = query.replace(" ", "+")
            await self.page.goto(
                f"https://www.google.com/search?q={encoded}",
                wait_until="domcontentloaded",
                timeout=20000
            )
            await asyncio.sleep(1)  # let JS settle

            # Extract organic result links and snippets
            results = []
            try:
                result_els = await self.page.locator("div.g").all()
                for el in result_els[:8]:
                    try:
                        link_el = el.locator("a").first
                        href = await link_el.get_attribute("href")
                        snippet_el = el.locator("span")
                        snippet_texts = await snippet_el.all_text_contents()
                        snippet = " ".join(snippet_texts)[:300]
                        if href and href.startswith("http") and snippet:
                            results.append({"url": href, "snippet": snippet})
                    except Exception:
                        pass
            except Exception:
                pass

            return {
                "status": "success",
                "message": f"Searched for: {query}",
                "query": query,
                "results": results
            }
        except Exception as e:
            return {"status": "error", "message": f"Search failed: {str(e)}"}

    async def extract_search_results(self) -> List[Dict[str, Any]]:
        """Extract clickable search result links from the current Google SERP."""
        results = []
        try:
            els = await self.page.locator("div.g a[href]").all()
            seen = set()
            for el in els:
                try:
                    href = await el.get_attribute("href")
                    text = (await el.text_content() or "").strip()
                    if href and href.startswith("http") and href not in seen:
                        seen.add(href)
                        results.append({"url": href, "text": text[:120]})
                except Exception:
                    pass
        except Exception:
            pass
        return results[:10]

    async def click(self, selector: str) -> Dict[str, Any]:
        """Click on an element by selector."""
        try:
            await self.page.click(selector, timeout=8000)
            await self.page.wait_for_load_state("domcontentloaded")
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
            await self.page.go_back(wait_until="domcontentloaded")
            return {"status": "success", "message": "Went back"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to go back: {str(e)}"}

    async def forward(self) -> Dict[str, Any]:
        """Go forward in browser history."""
        try:
            await self.page.go_forward(wait_until="domcontentloaded")
            return {"status": "success", "message": "Went forward"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to go forward: {str(e)}"}

    async def new_tab(self) -> Dict[str, Any]:
        """Open a new tab."""
        try:
            self.page = await self.context.new_page()
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
            text = await element.text_content(timeout=5000)
            return {"status": "success", "text": text, "selector": selector}
        except Exception as e:
            return {"status": "error", "message": f"Failed to extract: {str(e)}"}

    async def get_page_text(self) -> Dict[str, Any]:
        """Get all visible text from the current page body."""
        try:
            text = await self.page.inner_text("body")
            return {"status": "success", "text": text[:8000] if text else ""}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get page text: {str(e)}"}

    async def get_links(self, limit: int = 20) -> Dict[str, Any]:
        """Get all hyperlinks on the current page."""
        try:
            links = []
            els = await self.page.locator("a[href]").all()
            seen = set()
            for el in els:
                try:
                    href = await el.get_attribute("href")
                    text = (await el.text_content() or "").strip()
                    if href and href.startswith("http") and href not in seen:
                        seen.add(href)
                        links.append({"url": href, "text": text[:100]})
                except Exception:
                    pass
            return {"status": "success", "links": links[:limit]}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get links: {str(e)}"}

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

    @property
    def current_url(self) -> str:
        """Return the current page URL."""
        try:
            return self.page.url if self.page else ""
        except Exception:
            return ""