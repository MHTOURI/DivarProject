"""
Divar Scraper - Core scraping functionality.

This module provides the main DivarScraper class for scraping listings from Divar.ir.
It's designed to be modular and extensible, allowing users to:
- Customize search filters
- Add custom processing logic via callbacks
- Use custom storage backends
- Build their own API on top
"""

import asyncio
import logging
import random
from typing import Optional, Callable, List, Dict, Any, AsyncIterator
from datetime import datetime

import aiohttp

from divar.models import Ad, ScraperConfig
from divar.exceptions import RateLimitError, NetworkError, ScraperError

logger = logging.getLogger(__name__)


class DivarScraper:
    """
    Async scraper for Divar.ir listings.
    
    This scraper is designed to be used as a library component.
    Users can subclass it or use callbacks to customize behavior.
    
    Example:
        ```python
        import asyncio
        from divar import DivarScraper, ScraperConfig
        
        async def main():
            config = ScraperConfig(max_pages=5, delay_between_requests=3.0)
            scraper = DivarScraper(config)
            
            async with scraper:
                ads = await scraper.search(max_pages=5)
                for ad in ads:
                    print(f"{ad.title} - {ad.district}")
        
        asyncio.run(main())
        ```
    
    Example with callback:
        ```python
        async def on_ad_found(ad: Ad):
            # Custom processing - save to database, send to API, etc.
            print(f"Found: {ad.title}")
        
        scraper = DivarScraper()
        scraper.on_ad_found = on_ad_found
        ```
    """
    
    def __init__(
        self,
        config: Optional[ScraperConfig] = None,
        on_ad_found: Optional[Callable[[Ad], Any]] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
        on_rate_limit: Optional[Callable[[int], Any]] = None,
    ):
        """
        Initialize the scraper.
        
        Args:
            config: Scraper configuration (uses defaults if None)
            on_ad_found: Callback called when an ad is found (sync or async)
            on_error: Callback called when an error occurs
            on_rate_limit: Callback called when rate limited
        """
        self.config = config or ScraperConfig()
        self.on_ad_found = on_ad_found
        self.on_error = on_error
        self.on_rate_limit = on_rate_limit
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._cookies: Dict[str, str] = {}
        self._seen_tokens: set = set()
        
        # API endpoints
        self._search_url = "https://api.divar.ir/v8/postlist/w/search"
        self._ad_url_template = "https://api.divar.ir/v8/posts-v2/web/{token}?tracker_session_id={ad_id}"
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def start(self):
        """Initialize the scraper (create session, etc.)."""
        if self._session is not None:
            return
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://divar.ir",
            "Referer": "https://divar.ir/",
        }
        
        # Set custom user agent if provided
        if self.config.user_agent:
            headers["User-Agent"] = self.config.user_agent
        else:
            headers["User-Agent"] = self._get_random_user_agent()
        
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        connector = aiohttp.TCPConnector(limit=50)
        
        self._session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector,
        )
        
        # Generate initial cookies
        self._cookies = self._generate_cookies()
        
        logger.info("DivarScraper started")
    
    async def close(self):
        """Close the scraper (cleanup session, etc.)."""
        if self._session:
            await self._session.close()
            self._session = None
            logger.info("DivarScraper closed")
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent string."""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        return random.choice(user_agents)
    
    def _generate_cookies(self) -> Dict[str, str]:
        """Generate random cookies for requests."""
        import uuid
        return {
            "did": str(uuid.uuid4()),
            "cdid": str(uuid.uuid4()),
        }
    
    def _update_cookies(self):
        """Update cookies (rotate if needed)."""
        self._cookies = self._generate_cookies()
    
    async def _make_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make an HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments for aiohttp
            
        Returns:
            JSON response as dictionary
            
        Raises:
            RateLimitError: If rate limited
            NetworkError: If network error occurs
            ScraperError: If other error occurs
        """
        max_retries = self.config.max_retries
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if self._session is None:
                    raise ScraperError("Session not started. Use 'async with scraper:' or call start()")
                
                async with self._session.request(
                    method, url, 
                    cookies=self._cookies,
                    **kwargs
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    elif response.status == 429:
                        # Rate limited
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"Rate limited. Waiting {retry_after}s")
                        
                        if self.on_rate_limit:
                            await self._maybe_call(self.on_rate_limit, retry_after)
                        
                        await asyncio.sleep(retry_after)
                        self._update_cookies()
                        continue
                    
                    elif response.status >= 500:
                        logger.warning(f"Server error {response.status}, retrying...")
                        await asyncio.sleep(base_delay * (2 ** attempt))
                        continue
                    
                    else:
                        text = await response.text()
                        raise ScraperError(f"HTTP {response.status}: {text[:200]}")
                        
            except aiohttp.ClientError as e:
                logger.warning(f"Network error (attempt {attempt + 1}/{max_retries}): {e}")
                
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                else:
                    raise NetworkError(f"Request failed after {max_retries} attempts: {e}")
            
            except asyncio.TimeoutError:
                logger.warning(f"Timeout (attempt {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2 ** attempt))
                else:
                    raise NetworkError("Request timed out")
        
        raise ScraperError(f"Max retries ({max_retries}) exceeded")
    
    async def _maybe_call(self, callback, *args, **kwargs):
        """Call a callback, handling both sync and async functions."""
        if callback is None:
            return
        
        result = callback(*args, **kwargs)
        if asyncio.iscoroutine(result):
            await result
    
    def _should_ignore(self, title: str, description: str) -> bool:
        """Check if ad should be ignored based on keywords."""
        text = f"{title} {description}".lower()
        
        for keyword in self.config.keywords_to_ignore:
            if keyword.lower() in text:
                return True
        
        return False
    
    def _should_filter(self, title: str, description: str) -> bool:
        """Check if ad should be filtered (e.g., agency ads)."""
        text = f"{title} {description}".lower()
        
        for keyword in self.config.keywords_to_filter:
            if keyword.lower() in text:
                return True
        
        return False
    
    def _extract_ad_from_response(self, data: Dict[str, Any], ad_id: str) -> Optional[Ad]:
        """
        Extract Ad object from API response.
        
        Args:
            data: API response data
            ad_id: Ad instance ID
            
        Returns:
            Ad object or None if extraction failed
        """
        try:
            token = data.get("token", "")
            if not token:
                return None
            
            # Check if already seen
            if token in self._seen_tokens:
                return None
            
            self._seen_tokens.add(token)
            
            # Extract basic info
            title = ""
            description = ""
            district = ""
            
            # Try to extract from sections
            sections = data.get("sections", [])
            for section in sections:
                widgets = section.get("widgets", [])
                for widget in widgets:
                    widget_data = widget.get("data", {})
                    
                    # Title
                    if "title" in widget_data and not title:
                        title = widget_data["title"]
                    
                    # Description
                    if "text" in widget_data and not description:
                        description = widget_data["text"]
                    
                    # District from SEO
                    seo = data.get("seo", {})
                    web_info = seo.get("web_info", {})
                    district = web_info.get("district_persian", "")
            
            # URL
            url = data.get("share", {}).get("web_url", "")
            
            # Check if special
            is_special = "ویژه" in title or "special" in title.lower()
            
            ad = Ad(
                token=token,
                title=title,
                description=description,
                url=url,
                district=district,
                special=is_special,
                extra={"raw_data": data},
            )
            
            return ad
            
        except Exception as e:
            logger.error(f"Error extracting ad: {e}")
            return None
    
    async def search(
        self,
        city_id: Optional[str] = None,
        max_pages: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[Ad]:
        """
        Search for ads on Divar.
        
        Args:
            city_id: City ID to search (default: config.city_id)
            max_pages: Maximum pages to scrape (default: config.max_pages)
            category: Category to filter by
            
        Returns:
            List of Ad objects found
        """
        city_id = city_id or self.config.city_id
        max_pages = max_pages or self.config.max_pages
        
        all_ads: List[Ad] = []
        pagination_data = None
        
        for page in range(max_pages):
            logger.info(f"Scanning page {page + 1}/{max_pages}")
            
            ads = await self._search_page(
                city_id=city_id,
                pagination_data=pagination_data,
                category=category,
            )
            
            if not ads:
                logger.info("No more ads found")
                break
            
            all_ads.extend(ads)
            
            # Check for next page
            if len(ads) == 0:
                break
            
            # Get pagination for next page
            pagination_data = self._get_next_pagination(ads)
            if not pagination_data:
                break
            
            # Delay between requests
            delay = self.config.delay_between_requests
            if delay > 0:
                await asyncio.sleep(delay)
        
        logger.info(f"Scraped {len(all_ads)} ads total")
        return all_ads
    
    async def _search_page(
        self,
        city_id: str,
        pagination_data: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
    ) -> List[Ad]:
        """
        Search a single page and extract ads.
        
        Returns:
            List of Ad objects found on this page
        """
        # Build request payload
        payload = {
            "city_ids": [city_id],
            "pagination_data": pagination_data,
            "disable_recommendation": False,
            "map_state": {"camera_info": {"bbox": {}}},
            "search_data": self._build_search_filters(category),
        }
        
        try:
            response = await self._make_request("POST", self._search_url, json=payload)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            if self.on_error:
                await self._maybe_call(self.on_error, e)
            return []
        
        # Extract ads from response
        ads = []
        widgets = response.get("list_widgets", [])
        
        for widget in widgets:
            token = widget.get("data", {}).get("action", {}).get("payload", {}).get("token")
            ad_id = widget.get("data", {}).get("action", {}).get("payload", {}).get("ad_instance_id")
            
            if not token or not ad_id:
                continue
            
            # Fetch ad details
            try:
                ad_data = await self._fetch_ad_details(token, ad_id)
                ad = self._extract_ad_from_response(ad_data, ad_id)
                
                if ad and not self._should_ignore(ad.title, ad.description):
                    if self._should_filter(ad.title, ad.description):
                        logger.debug(f"Filtered: {ad.title[:50]}")
                        continue
                    
                    ads.append(ad)
                    
                    # Call callback
                    if self.on_ad_found:
                        await self._maybe_call(self.on_ad_found, ad)
                        
            except Exception as e:
                logger.error(f"Error fetching ad {token}: {e}")
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
        
        return ads
    
    def _build_search_filters(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Build search filters payload."""
        filters = {
            "form_data": {
                "data": {
                    "business-type": {"repeated_string": {"value": ["personal"]}},
                }
            },
            "server_payload": {
                "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
                "additional_form_data": {
                    "data": {"sort": {"str": {"value": "sort_date"}}}
                },
            },
        }
        
        if category:
            filters["form_data"]["data"]["category"] = {"str": {"value": category}}
        
        return filters
    
    def _get_next_pagination(self, ads: List[Ad]) -> Optional[Dict[str, Any]]:
        """Get pagination data for next page from last ad's data."""
        if not ads:
            return None
        
        # This is a simplified version - in reality you'd need to parse
        # the response properly. For now, we return None to indicate
        # pagination isn't implemented in this basic version.
        return None
    
    async def _fetch_ad_details(self, token: str, ad_id: str) -> Dict[str, Any]:
        """Fetch detailed ad information."""
        url = self._ad_url_template.format(token=token, ad_id=ad_id)
        return await self._make_request("GET", url)
    
    async def stream(
        self,
        city_id: Optional[str] = None,
        max_pages: Optional[int] = None,
        category: Optional[str] = None,
    ) -> AsyncIterator[Ad]:
        """
        Stream ads as they're found (async generator).
        
        Useful for processing ads one at a time without waiting for all pages.
        
        Example:
            async with scraper:
                async for ad in scraper.stream(max_pages=10):
                    await process_ad(ad)
        
        Yields:
            Ad objects as they're found
        """
        city_id = city_id or self.config.city_id
        max_pages = max_pages or self.config.max_pages
        
        pagination_data = None
        
        for page in range(max_pages):
            logger.info(f"Streaming page {page + 1}/{max_pages}")
            
            # Build request payload
            payload = {
                "city_ids": [city_id],
                "pagination_data": pagination_data,
                "disable_recommendation": False,
                "map_state": {"camera_info": {"bbox": {}}},
                "search_data": self._build_search_filters(category),
            }
            
            try:
                response = await self._make_request("POST", self._search_url, json=payload)
            except Exception as e:
                logger.error(f"Search failed: {e}")
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
                break
            
            widgets = response.get("list_widgets", [])
            
            for widget in widgets:
                token = widget.get("data", {}).get("action", {}).get("payload", {}).get("token")
                ad_id = widget.get("data", {}).get("action", {}).get("payload", {}).get("ad_instance_id")
                
                if not token or not ad_id:
                    continue
                
                try:
                    ad_data = await self._fetch_ad_details(token, ad_id)
                    ad = self._extract_ad_from_response(ad_data, ad_id)
                    
                    if ad and not self._should_ignore(ad.title, ad.description):
                        if not self._should_filter(ad.title, ad.description):
                            yield ad
                            
                            # Call callback
                            if self.on_ad_found:
                                await self._maybe_call(self.on_ad_found, ad)
                
                except Exception as e:
                    logger.error(f"Error fetching ad {token}: {e}")
                    if self.on_error:
                        await self._maybe_call(self.on_error, e)
            
            # Check for next page
            if not widgets:
                break
            
            # Get pagination (simplified)
            pagination_data = None  # Implement proper pagination extraction
            
            # Delay
            delay = self.config.delay_between_requests
            if delay > 0:
                await asyncio.sleep(delay)
    
    async def monitor(
        self,
        city_id: Optional[str] = None,
        interval: float = 60.0,
        max_pages_per_cycle: int = 5,
        category: Optional[str] = None,
    ) -> AsyncIterator[List[Ad]]:
        """
        Monitor Divar for new ads continuously.
        
        Yields batches of new ads at each interval.
        
        Example:
            async with scraper:
                async for batch in scraper.monitor(interval=120):
                    for ad in batch:
                        await send_notification(ad)
        
        Args:
            city_id: City to monitor
            interval: Seconds between checks
            max_pages_per_cycle: Max pages per check
            category: Category filter
            
        Yields:
            Lists of new Ad objects
        """
        city_id = city_id or self.config.city_id
        seen_tokens = set()
        
        while True:
            logger.info("Starting monitoring cycle")
            
            new_ads = []
            
            async for ad in self.stream(
                city_id=city_id,
                max_pages=max_pages_per_cycle,
                category=category,
            ):
                if ad.token not in seen_tokens:
                    seen_tokens.add(ad.token)
                    new_ads.append(ad)
            
            if new_ads:
                logger.info(f"Found {len(new_ads)} new ads")
                yield new_ads
            
            logger.info(f"Waiting {interval}s until next check")
            await asyncio.sleep(interval)
