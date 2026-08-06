import asyncio
import random
from typing import Any, Dict, List, Optional

from bot.config import (
    AGENCY_BLOCKED_WORDS,
    HEADERS,
    IGNORE_KEYWORDS,
    MAX_CONCURRENCY,
    MAX_RETRY,
    PROXIES,
    REQUEST_TIMEOUT,
    SEARCH_FILTERS,
    SEARCH_URL,
    get_cookies,
    get_random_user_agent,
)
from bot.database import is_seen, mark_seen
from bot.logger.logger import log
from bot.network import (
    CookieManager,
    ProxyManager,
    RecoveryPipeline,
    RequestClient,
    SessionManager,
    UserAgentPool,
)

# ======================================================
# Divar Scraper
# ======================================================


class DivarScraper:

    def __init__(self, stats=None, events=None, workers=None):
        self.stats = stats
        self.events = events
        self.workers = workers

        self.session_manager = SessionManager(timeout=REQUEST_TIMEOUT)
        self.ua_pool = UserAgentPool()
        self.cookie_manager = CookieManager()
        self.proxy_manager = ProxyManager(PROXIES)
        self.recovery = RecoveryPipeline(
            self.session_manager,
            self.ua_pool,
            self.cookie_manager,
            self.proxy_manager,
        )
        self.client = RequestClient(self.session_manager, recovery=self.recovery)
        self.client.retry.attempts = MAX_RETRY

        self.semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def __aenter__(self):
        self.session_manager.headers.update(HEADERS)
        self.session_manager.headers["User-Agent"] = get_random_user_agent()

        # real UAs instead of the network package's 3 hardcoded fallbacks —
        # this is what RecoveryPipeline.change_user_agent() rotates through on a 429
        self.ua_pool.agents = [get_random_user_agent() for _ in range(10)]

        # cookie pool for the same rotation-on-block path
        for _ in range(5):
            self.cookie_manager.add(get_cookies())

        await self.session_manager.start()
        log("HTTP Session Started", "INFO")
        if self.events:
            self.events.add("🚀 HTTP Session Started")
        return self

    async def __aexit__(self, *args):
        await self.session_manager.close()
        if self.events:
            self.events.add("🛑 HTTP Session Closed")

    def _blocked_delta(self, before: int) -> int:
        return self.client.stats_data["rate_limit"] - before

    # ======================================================
    # Text Helpers
    # ======================================================

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        return (
            text.replace(" ", "")
            .replace("\u200c", "")
            .replace("\u200f", "")
            .replace("-", "")
            .lower()
        )

    def is_ignore(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        for word in IGNORE_KEYWORDS:
            if self.normalize_text(word) in normalized:
                return True
        return False

    def is_agency(self, text: str) -> bool:
        normalized = self.normalize_text(text)
        for word in AGENCY_BLOCKED_WORDS:
            if self.normalize_text(word) in normalized:
                return True
        return False

    @staticmethod
    def is_special(title: str, text: str) -> bool:
        return "مسکن ویژه" in (title or "") or "مسکن ویژه" in (text or "")

    # ======================================================
    # Search API
    # ======================================================

    async def search(self, pagination: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "city_ids": ["1"],
            "pagination_data": pagination,
            "disable_recommendation": False,
            "map_state": {"camera_info": {"bbox": {}}},
            "search_data": SEARCH_FILTERS,
        }

        if self.events:
            self.events.add("🔎 Searching Divar")

        blocked_before = self.client.stats_data["rate_limit"]

        result = await self.client.post(SEARCH_URL, json=payload, headers=HEADERS)

        if self.stats:
            self.stats.add_request()
            for _ in range(self._blocked_delta(blocked_before)):
                self.stats.add_blocked()

        if not result.success:
            if self.stats:
                self.stats.add_failed()
            log(f"❌ Search failed: {result.error}", "ERROR")
            if self.events:
                self.events.add(f"❌ Search Error: {result.error}", "ERROR")
            return {}

        if self.stats:
            self.stats.add_success()
        if self.events:
            self.events.add("✅ Search OK")

        return result.data or {}

    # ======================================================
    # Response Helpers
    # ======================================================

    @staticmethod
    def has_next(response: dict) -> bool:
        return (
            response.get("action_log", {})
            .get("server_side_info", {})
            .get("info", {})
            .get("has_next_page", False)
        )

    @staticmethod
    def get_pagination(response: dict) -> Optional[str]:
        return response.get("pagination", {}).get("data")

    @staticmethod
    def widgets(response: dict) -> List[dict]:
        return response.get("list_widgets", [])

    @staticmethod
    def post_info(widget: dict) -> tuple:
        payload = widget.get("data", {}).get("action", {}).get("payload", {})
        return payload.get("token"), payload.get("ad_instance_id")

    # ======================================================
    # Fetch Ad Detail
    # ======================================================

    async def fetch_ad(self, token: str, ad_id: str) -> Dict[str, Any]:
        url = f"https://api.divar.ir/v8/posts-v2/web/{token}?tracker_session_id={ad_id}"
        worker_name = f"fetch-{token}"

        async with self.semaphore:
            if self.workers:
                self.workers.update(worker_name, "Divar API", "FETCHING")

            try:
                blocked_before = self.client.stats_data["rate_limit"]

                result = await self.client.get(url, headers=HEADERS)

                if self.stats:
                    self.stats.add_request()
                    for _ in range(self._blocked_delta(blocked_before)):
                        self.stats.add_blocked()

                if not result.success:
                    log(f"❌ Fetch failed for {token}: {result.error}", "ERROR")
                    if self.events:
                        self.events.add(
                            f"❌ Fetch failed {token}: {result.error}", "ERROR"
                        )
                    return {}

                if self.stats:
                    self.stats.add_success()
                if self.events:
                    self.events.add(f"📄 Loaded {token}")

                return result.data or {}
            finally:
                if self.workers:
                    self.workers.update(worker_name, "Divar API", "WAITING")

    # ======================================================
    # Extractors
    # ======================================================

    @staticmethod
    def extract_title(ad: dict) -> str:
        try:
            return ad["sections"][1]["widgets"][0]["data"]["title"]
        except Exception:
            return ""

    @staticmethod
    def extract_text(ad: dict) -> str:
        # ساختار اصلی
        try:
            return ad["sections"][2]["widgets"][1]["data"]["text"]
        except Exception:
            pass
        # ساختار جایگزین (بعضی آگهی‌ها توضیحات را داخل widget_list می‌گذارند)
        try:
            return ad["sections"][1]["widgets"][1]["data"]["widget_list"][0]["data"][
                "text"
            ]
        except Exception:
            return ""

    @staticmethod
    def extract_seo_title(ad: dict) -> str:
        """عنوان SEO آگهی از کلید ad['seo']['title']"""
        try:
            return ad["seo"]["title"]
        except Exception:
            return ""

    @staticmethod
    def extract_district(ad: dict) -> str:
        try:
            return ad["seo"]["web_info"]["district_persian"]
        except Exception:
            try:
                return ad["seo"]["post_seo_schema"]["web_info"]["district_persian"]
            except Exception:
                return ""

    # ======================================================
    # Process Ad
    # ======================================================

    async def process_ad(self, token: str, ad_id: str) -> Optional[Dict]:
        worker_name = f"process-{token}"
        if self.workers:
            self.workers.update(worker_name, "Parser", "PROCESSING")

        try:
            log(f"📥 Fetching ad {token}...", "INFO")
            if self.events:
                self.events.add(f"⚙ Processing {token}")

            if await is_seen(token):
                log(f"⏭ Skipped (already seen): {token}", "INFO")
                if self.stats:
                    self.stats.add_duplicate()
                if self.events:
                    self.events.add(f"⏭ Duplicate {token}", "WARNING")
                return None

            ad = await self.fetch_ad(token, ad_id)
            if not ad:
                log(
                    f"⚠️ No data returned for ad {token} (fetch failed after retries)",
                    "WARNING",
                )
                return None

            title = self.extract_title(ad)
            text = self.extract_text(ad)
            seo_title = self.extract_seo_title(ad)
            district = self.extract_district(ad)
            url = ad.get("share", {}).get("web_url", "")
            full_text = f"{title} {text}"

            log(
                f"📄 Received: \"{title[:50]}\" | محله: {district or '-'} | {token}",
                "INFO",
            )

            if self.is_ignore(full_text):
                log(
                    f"🚫 Filtered out (ignore keyword): {title[:40]} | {token}",
                    "WARNING",
                )
                if self.stats:
                    self.stats.add_filtered()
                if self.events:
                    self.events.add(f"🚫 Ignored {token}", "WARNING")
                return None

            if self.is_agency(full_text):
                log(f"🏢 Filtered out (agency): {title[:40]} | {token}", "WARNING")
                if self.stats:
                    self.stats.add_filtered()
                if self.events:
                    self.events.add(f"🏢 Agency removed {token}", "WARNING")
                return None

            special = self.is_special(title, text)

            await mark_seen(
                token=token,
                title=title,
                url=url,
                district=district,
                text=text[:500],
                seo_title=seo_title,
                special=1 if special else 0,
            )

            log(
                f"💾 Saved{' (ویژه)' if special else ''}: \"{title[:50]}\" | {token}",
                "SUCCESS",
            )

            if self.stats:
                self.stats.add_saved()
            if self.events:
                self.events.add(f"💾 Saved {title[:30]}")

            return {
                "token": token,
                "title": title,
                "seo_title": seo_title,
                "district": district,
                "url": url,
                "text": text,
                "special": special,
            }

        finally:
            if self.workers:
                self.workers.update(worker_name, "Parser", "WAITING")

    # ======================================================
    # Monitor Once
    # ======================================================

    async def monitor_once(self) -> int:
        log("ENTER monitor_once", "INFO")
        if self.events:
            self.events.add("🔍 Monitor started")
            self.events.add("🌐 Calling Divar Search API")

        if self.workers:
            self.workers.update("monitor", "Search", "RUNNING")

        pagination = None
        total_new = 0
        page = 1

        while True:
            if self.events:
                self.events.add(f"📄 Monitor page {page}")

            response = await self.search(pagination)
            log(f"SEARCH RESPONSE: {bool(response)}", "INFO")

            if not response:
                break

            widgets = self.widgets(response)
            log(f"📦 Page {page}: {len(widgets)} آگهی در نتایج جستجو پیدا شد", "INFO")
            tasks = []

            for widget in widgets:
                token, ad_id = self.post_info(widget)
                if token and ad_id:
                    tasks.append(self.process_ad(token, ad_id))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for item in results:
                if isinstance(item, Exception):
                    log(f"❌ process_ad exception: {item}", "ERROR")
                    import traceback

                    for line in (
                        "".join(
                            traceback.format_exception(
                                type(item), item, item.__traceback__
                            )
                        )
                        .strip()
                        .split("\n")
                    ):
                        log(f"    {line}", "ERROR")

            count = sum(
                1 for item in results if item and not isinstance(item, Exception)
            )
            total_new += count

            if not self.has_next(response):
                break

            pagination = self.get_pagination(response)
            if not pagination:
                break

            page += 1
            await asyncio.sleep(random.uniform(2, 5))

        if self.workers:
            self.workers.update("monitor", "Search", "WAITING")

        if self.events:
            self.events.add(f"✅ Monitor finished +{total_new}")

        return total_new

    # ======================================================
    # Full Scan
    # ======================================================

    async def full_scan(self, max_pages: Optional[int] = None) -> int:
        if self.events:
            self.events.add("🚀 Full scan started")
        if self.workers:
            self.workers.update("full-scan", "Search", "RUNNING")

        pagination = None
        page = 1
        total_new = 0

        while True:
            if max_pages and page > max_pages:
                break

            if self.events:
                self.events.add(f"📃 Scan page {page}")

            response = await self.search(pagination)
            if not response:
                break

            widgets = self.widgets(response)
            if not widgets:
                break

            tasks = []
            for widget in widgets:
                token, ad_id = self.post_info(widget)
                if token and ad_id:
                    tasks.append(self.process_ad(token, ad_id))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_new += sum(
                1 for item in results if item and not isinstance(item, Exception)
            )

            if not self.has_next(response):
                break

            pagination = self.get_pagination(response)
            if not pagination:
                break

            page += 1
            await asyncio.sleep(random.uniform(2, 5))

        if self.workers:
            self.workers.update("full-scan", "Search", "WAITING")
        if self.events:
            self.events.add(f"🏁 Full scan finished +{total_new}")

        return total_new
