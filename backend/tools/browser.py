"""
Playwright browser control with persistent context and intelligent page state detection.
headless=False so the user sees it. Detects CAPTCHA, consent, sorry pages, etc.
"""
import asyncio
import os
import time
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from playwright.async_api import async_playwright, BrowserContext, Page


class BrowserPageState(Enum):
    """Detected state of the browser page after navigation/search."""
    NORMAL_SERP = "normal_serp"
    CAPTCHA = "captcha"
    CONSENT = "consent"
    SORRY_PAGE = "sorry_page"
    NETWORK_ERROR = "network_error"
    EMPTY_RESULTS = "empty_results"
    NAVIGATION_PENDING = "navigation_pending"
    UNKNOWN = "unknown"


@dataclass
class PageStateResult:
    """Structured result of page state detection."""
    state: BrowserPageState
    verified: bool
    message: str
    details: Dict[str, Any]


class Browser:
    """Playwright browser control with persistent user profile to avoid CAPTCHAs."""

    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None

    async def start(self):
        """Initialize Playwright browser with persistent user profile to avoid CAPTCHAs."""
        self.playwright = await async_playwright().start()

        # Use persistent context with user data dir — reuses Chrome profile (cookies, logins)
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

    # ─────────────────────────────────────────────────────────────────────────
    # Page State Detection
    # ─────────────────────────────────────────────────────────────────────────

    async def detect_page_state(self) -> PageStateResult:
        """
        Inspect the current page and classify its state.
        Returns structured state for the agent to act upon.
        """
        if not self.page:
            return PageStateResult(
                state=BrowserPageState.UNKNOWN,
                verified=False,
                message="No browser page available",
                details={}
            )

        try:
            # Wait a bit for page to settle
            await asyncio.sleep(0.5)

            url = self.page.url
            title = await self.page.title()
            content = await self.page.content()

            # Check for Google "sorry" / unusual traffic page (only on Google domains)
            is_google_domain = "google.com" in url
            if is_google_domain and ("/sorry/" in url or "unusual traffic" in content.lower()):
                if "recaptcha" in content.lower() or "g-recaptcha" in content or "captcha" in url:
                    return PageStateResult(
                        state=BrowserPageState.CAPTCHA,
                        verified=False,
                        message="Google CAPTCHA / human verification required",
                        details={"url": url, "title": title, "type": "recaptcha"}
                    )
                return PageStateResult(
                    state=BrowserPageState.SORRY_PAGE,
                    verified=False,
                    message="Google 'unusual traffic' / sorry page detected",
                    details={"url": url, "title": title}
                )

            # Check for consent/interstitial page
            if "consent.google.com" in url or "consent.youtube.com" in url:
                return PageStateResult(
                    state=BrowserPageState.CONSENT,
                    verified=False,
                    message="Google consent page requires acceptance",
                    details={"url": url, "title": title}
                )
            # Generic consent overlay detection
            if "before you continue" in content.lower() or "agree" in content.lower() and "privacy" in content.lower():
                consent_buttons = await self.page.locator("button:has-text('Accept'), button:has-text('Agree'), button:has-text('I agree')").all()
                if consent_buttons:
                    return PageStateResult(
                        state=BrowserPageState.CONSENT,
                        verified=False,
                        message="Consent overlay detected",
                        details={"url": url, "title": title, "buttons_found": len(consent_buttons)}
                    )

            # Check for network/navigation errors
            if "net::" in url or "chrome-error://" in url or "about:neterror" in url:
                return PageStateResult(
                    state=BrowserPageState.NETWORK_ERROR,
                    verified=False,
                    message="Network/navigation error",
                    details={"url": url, "title": title}
                )

            # Check if on Google SERP (search results page)
            is_google_serp = "google.com/search" in url or "google.com/search" in content
            if is_google_serp:
                # Check for actual results
                result_count = await self._count_search_results()
                if result_count == 0:
                    # Could be empty results or CAPTCHA without clear indicators
                    if "our systems have detected unusual traffic" in content.lower():
                        return PageStateResult(
                            state=BrowserPageState.CAPTCHA,
                            verified=False,
                            message="CAPTCHA detected on SERP (no results shown)",
                            details={"url": url, "title": title}
                        )
                    return PageStateResult(
                        state=BrowserPageState.EMPTY_RESULTS,
                        verified=False,
                        message="Google SERP loaded but no organic results found",
                        details={"url": url, "title": title, "result_count": 0}
                    )
                return PageStateResult(
                    state=BrowserPageState.NORMAL_SERP,
                    verified=True,
                    message=f"Google SERP with {result_count} results",
                    details={"url": url, "title": title, "result_count": result_count}
                )

            # Check if page is still loading
            ready_state = await self.page.evaluate("document.readyState")
            if ready_state != "complete":
                return PageStateResult(
                    state=BrowserPageState.NAVIGATION_PENDING,
                    verified=False,
                    message=f"Page still loading (readyState: {ready_state})",
                    details={"url": url, "title": title, "ready_state": ready_state}
                )

            return PageStateResult(
                state=BrowserPageState.UNKNOWN,
                verified=True,
                message=f"Page loaded: {title}",
                details={"url": url, "title": title}
            )

        except Exception as e:
            return PageStateResult(
                state=BrowserPageState.UNKNOWN,
                verified=False,
                message=f"Page state detection error: {str(e)}",
                details={"error": str(e)}
            )

    async def _count_search_results(self) -> int:
        """Count organic search results on current Google SERP."""
        try:
            # Multiple selectors for robustness
            selectors = [
                "div.g a[href]",           # Standard result links
                "div[data-hveid] a[href]", # Another common pattern
                "div.MjjYud a[href]",      # Modern Google layout
                "div.g div.VwiC3b a[href]", # Snippet links
            ]
            total = 0
            seen = set()
            for sel in selectors:
                try:
                    els = await self.page.locator(sel).all()
                    for el in els:
                        href = await el.get_attribute("href")
                        if href and href.startswith("http") and "google.com" not in href and href not in seen:
                            seen.add(href)
                            total += 1
                except Exception:
                    continue
            return total
        except Exception:
            return 0

    # ─────────────────────────────────────────────────────────────────────────
    # Consent Handling
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_consent_if_present(self) -> Dict[str, Any]:
        """Click consent/accept buttons if a consent page is detected."""
        try:
            # Common consent button selectors
            consent_selectors = [
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
                "button:has-text('I agree')",
                "button:has-text('Agree')",
                "button:has-text('Continue')",
                "button[id*='accept']",
                "button[jsname*='accept']",
                "div[role='button']:has-text('Accept')",
            ]
            for sel in consent_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click(timeout=3000)
                        await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                        await asyncio.sleep(1)
                        return {"status": "success", "message": f"Consent accepted via '{sel}'"}
                except Exception:
                    continue
            return {"status": "error", "message": "No consent button found or click failed"}
        except Exception as e:
            return {"status": "error", "message": f"Consent handling error: {str(e)}"}

    # ─────────────────────────────────────────────────────────────────────────
    # Search with built-in result extraction
    # ─────────────────────────────────────────────────────────────────────────

    async def search(self, query: str) -> Dict[str, Any]:
        """
        Search Google and extract results in one action.
        Falls back to Bing automatically if Google shows CAPTCHA/sorry page.
        Returns structured results to avoid redundant extraction step.
        """
        try:
            encoded = query.replace(" ", "+")
            await self.page.goto(
                f"https://www.google.com/search?q={encoded}",
                wait_until="domcontentloaded",
                timeout=20000
            )
            await asyncio.sleep(1.5)  # let JS settle

            # Detect page state first
            page_state = await self.detect_page_state()

            if page_state.state == BrowserPageState.CONSENT:
                # Try to auto-handle consent
                await self.handle_consent_if_present()
                await asyncio.sleep(1)
                page_state = await self.detect_page_state()

            if page_state.state == BrowserPageState.CAPTCHA or page_state.state == BrowserPageState.SORRY_PAGE:
                # Auto-fallback to Bing instead of blocking the user
                return await self.search_bing(query)

            if page_state.state == BrowserPageState.NETWORK_ERROR:
                return {
                    "status": "error",
                    "verified": False,
                    "page_state": page_state.state.value,
                    "message": "Network error during search",
                    "retryable": True,
                    "details": page_state.details
                }

            if page_state.state == BrowserPageState.EMPTY_RESULTS:
                return {
                    "status": "error",
                    "verified": False,
                    "page_state": page_state.state.value,
                    "message": "Search returned no results",
                    "retryable": False,
                    "details": page_state.details
                }

            # Extract results using multiple strategies
            results = await self._extract_search_results_robust()

            if not results:
                return {
                    "status": "error",
                    "verified": False,
                    "page_state": "empty_after_extraction",
                    "message": "Search page loaded but no extractable results found",
                    "retryable": False,
                    "url": self.page.url
                }

            return {
                "status": "success",
                "verified": True,
                "page_state": page_state.state.value,
                "message": f"Search completed: {len(results)} results found",
                "query": query,
                "results": results,
                "url": self.page.url,
                "title": await self.page.title()
            }

        except Exception as e:
            return {"status": "error", "verified": False, "message": f"Search failed: {str(e)}", "retryable": True}

    async def search_bing(self, query: str) -> Dict[str, Any]:
        """
        Fallback search using Bing — used automatically when Google blocks with CAPTCHA.
        Falls back further to DuckDuckGo if Bing also fails to return results.
        """
        result = await self._search_engine(
            "https://www.bing.com/search?q=",
            query,
            blocked_domains=["bing.com", "microsoft.com", "msn.com"],
            engine_name="Bing"
        )
        if result.get("status") == "success":
            return result
        # Final fallback: DuckDuckGo
        return await self._search_engine(
            "https://duckduckgo.com/?q=",
            query,
            blocked_domains=["duckduckgo.com", "duck.com"],
            engine_name="DuckDuckGo"
        )

    async def _search_engine(self, base_url: str, query: str, blocked_domains: list, engine_name: str) -> Dict[str, Any]:
        """
        Generic search engine helper with 4-strategy result extraction.
        Strategy 1: Common result-container CSS selectors
        Strategy 2: Any external <a href> on the page with meaningful text
        Strategy 3: Regex URL extraction from page body text
        Strategy 4: JavaScript evaluation to collect all anchor hrefs
        """
        try:
            encoded = query.replace(" ", "+")
            await self.page.goto(
                f"{base_url}{encoded}",
                wait_until="domcontentloaded",
                timeout=25000
            )
            await asyncio.sleep(2.0)  # Let JS render

            results = []
            seen_urls = set()

            # ── Strategy 1: CSS containers ──────────────────────────────────
            container_selectors = [
                # Bing
                "li.b_algo", "div.b_algo",
                # DuckDuckGo
                "article[data-testid='result']", "div.result",
                # Generic
                "div[class*='result']", "div[class*='Result']",
            ]
            for sel in container_selectors:
                try:
                    containers = await self.page.locator(sel).all()
                    for container in containers[:12]:
                        try:
                            link_el = container.locator("a[href]").first
                            href = await link_el.get_attribute("href", timeout=1000)
                            if not href or not href.startswith("http"):
                                continue
                            if any(d in href for d in blocked_domains):
                                continue
                            if href in seen_urls:
                                continue
                            seen_urls.add(href)
                            # Title
                            title = ""
                            for t_sel in ("h2", "h3", "h4", "strong"):
                                t_el = container.locator(t_sel).first
                                if await t_el.count() > 0:
                                    title = (await t_el.text_content() or "").strip()
                                    if title:
                                        break
                            if not title:
                                title = (await link_el.text_content() or href)[:120]
                            # Snippet
                            snippet = ""
                            for s_sel in ("p", "span", "div"):
                                s_el = container.locator(s_sel).first
                                if await s_el.count() > 0:
                                    s_text = (await s_el.text_content() or "").strip()
                                    if len(s_text) > 20:
                                        snippet = s_text[:300]
                                        break
                            results.append({"title": title, "url": href, "snippet": snippet})
                        except Exception:
                            continue
                except Exception:
                    continue
                if len(results) >= 8:
                    break

            # ── Strategy 2: All <a href> on page ───────────────────────────
            if len(results) < 3:
                try:
                    els = await self.page.locator("a[href]").all()
                    for el in els:
                        try:
                            href = await el.get_attribute("href", timeout=500)
                            text = (await el.text_content() or "").strip()
                            if not href or not href.startswith("http"):
                                continue
                            if any(d in href for d in blocked_domains):
                                continue
                            if href in seen_urls or len(text) < 8:
                                continue
                            seen_urls.add(href)
                            results.append({"title": text[:120], "url": href, "snippet": ""})
                            if len(results) >= 10:
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            # ── Strategy 3: Regex URL extraction from page text ─────────────
            if len(results) < 3:
                try:
                    body_text = await self.page.inner_text("body")
                    urls_found = re.findall(r'https?://[^\s\)\]\}\'\"\<\>]+', body_text)
                    for u in urls_found:
                        u = u.rstrip(".,;:")
                        if any(d in u for d in blocked_domains):
                            continue
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        results.append({"title": u, "url": u, "snippet": "Extracted from page text"})
                        if len(results) >= 10:
                            break
                except Exception:
                    pass

            # ── Strategy 4: JavaScript href collection ──────────────────────
            if len(results) < 3:
                try:
                    hrefs = await self.page.evaluate("""
                        () => Array.from(document.querySelectorAll('a[href]'))
                            .map(a => ({href: a.href, text: a.innerText?.trim() || ''}))
                            .filter(x => x.href.startswith('http') && x.text.length > 5)
                    """)
                    for item in hrefs[:30]:
                        href = item.get("href", "")
                        text = item.get("text", "")
                        if any(d in href for d in blocked_domains):
                            continue
                        if href in seen_urls:
                            continue
                        seen_urls.add(href)
                        results.append({"title": text[:120], "url": href, "snippet": ""})
                        if len(results) >= 10:
                            break
                except Exception:
                    pass

            if not results:
                return {
                    "status": "error",
                    "verified": False,
                    "message": f"{engine_name} search returned no results",
                    "retryable": False,
                    "url": self.page.url
                }

            return {
                "status": "success",
                "verified": True,
                "page_state": f"{engine_name.lower()}_serp",
                "message": f"{engine_name} search: {len(results)} results found",
                "query": query,
                "results": results[:10],
                "url": self.page.url,
                "title": await self.page.title()
            }

        except Exception as e:
            return {"status": "error", "verified": False, "message": f"{engine_name} search failed: {str(e)}", "retryable": True}

    async def _extract_search_results_robust(self) -> List[Dict[str, Any]]:
        """
        Extract search results using multiple strategies for robustness.
        Filters out Google internal/navigation links.
        """
        results = []
        seen_urls = set()

        # Strategy 1: Standard organic result containers
        try:
            containers = await self.page.locator("div.g, div[data-hveid], div.MjjYud").all()
            for container in containers[:15]:
                try:
                    # Try to find link in container
                    link_el = container.locator("a[href]").first
                    href = await link_el.get_attribute("href")
                    if not href or not href.startswith("http") or "google.com" in href:
                        continue
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    # Extract title and snippet
                    title = ""
                    snippet = ""

                    # Try heading
                    heading = container.locator("h3").first
                    if await heading.count() > 0:
                        title = (await heading.text_content() or "").strip()

                    # Try snippet
                    snippet_els = container.locator("div.VwiC3b, div.s, span").all()
                    for se in snippet_els:
                        text = (await se.text_content() or "").strip()
                        if len(text) > 20 and text not in snippet:
                            snippet = text[:300]
                            break

                    if title or snippet:
                        results.append({"title": title, "url": href, "snippet": snippet})
                except Exception:
                    continue
        except Exception:
            pass

        # Strategy 2: Direct link extraction (fallback)
        if len(results) < 3:
            try:
                els = await self.page.locator("div.g a[href], div[data-hveid] a[href]").all()
                for el in els:
                    try:
                        href = await el.get_attribute("href")
                        text = (await el.text_content() or "").strip()
                        if not href or not href.startswith("http") or "google.com" in href:
                            continue
                        if href in seen_urls:
                            continue
                        if len(text) < 5:
                            continue
                        seen_urls.add(href)
                        results.append({"title": text[:120], "url": href, "snippet": ""})
                        if len(results) >= 10:
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # Strategy 3: Page text extraction (last resort)
        if not results:
            try:
                text = await self.page.inner_text("body")
                # Regex for URLs in text
                urls = re.findall(r'https?://[^\s\)\]\}\'\">]+', text)
                for u in urls[:10]:
                    if "google.com" not in u and u not in seen_urls:
                        seen_urls.add(u)
                        results.append({"title": u, "url": u, "snippet": "Extracted from page text"})
            except Exception:
                pass

        return results[:10]

    async def extract_search_results(self) -> List[Dict[str, Any]]:
        """Extract clickable search result links from the current Google SERP (legacy method)."""
        results = await self._extract_search_results_robust()
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation & Extraction
    # ─────────────────────────────────────────────────────────────────────────

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
            title_result = await self.get_page_title()
            return {
                "status": "success",
                "text": text[:8000] if text else "",
                "title": title_result.get("title", ""),
                "url": title_result.get("url", "")
            }
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