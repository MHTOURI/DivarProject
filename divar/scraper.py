"""
Divar Scraper - Core scraping functionality.

This module provides the main DivarScraper class for scraping listings from Divar.ir.
It's designed to be modular and extensible, allowing users to:
- Customize search filters
- Add custom processing logic via callbacks
- Use custom storage backends
- Build their own API on top
- Scrape map data with coordinates
"""

import asyncio
import logging
import random
from typing import Optional, Callable, List, Dict, Any, AsyncIterator
from datetime import datetime
from pathlib import Path
import json

import aiohttp

from divar.models import (
    Ad, MapAd, ScraperConfig, CITY_IDS, CATEGORIES, DEFAULT_SEARCH_FILTERS
)
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
            scraper = DivarScraper(config=config)
            
            async with scraper:
                ads = await scraper.search(max_pages=5)
                for ad in ads:
                    print(f"{ad.title} - {ad.district}")
        
        asyncio.run(main())
        ```
    
    Example with map view:
        ```python
        config = ScraperConfig.for_map_view(
            category="apartment-sell",
            bbox={
                "min_latitude": 35.228049,
                "min_longitude": 51.107464,
                "max_latitude": 36.119353,
                "max_longitude": 51.636307,
            }
        )
        scraper = DivarScraper(config=config)
        
        async with scraper:
            map_ads = await scraper.scrape_map()
            for ad in map_ads:
                print(f"{ad.title} at ({ad.latitude}, {ad.longitude})")
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
        self._map_url = "https://api.divar.ir/v8/mapview/viewport"
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
        """Extract Ad object from API response."""
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
                    
                    if "title" in widget_data and not title:
                        title = widget_data["title"]
                    
                    if "text" in widget_data and not description:
                        description = widget_data["text"]
                    
                    seo = data.get("seo", {})
                    web_info = seo.get("web_info", {})
                    district = web_info.get("district_persian", "")
            
            url = data.get("share", {}).get("web_url", "")
            is_special = "ویژه" in title or "special" in title.lower()
            
            # Extract coordinates if available
            latitude = None
            longitude = None
            location = data.get("location", {})
            if location:
                latitude = location.get("latitude")
                longitude = location.get("longitude")
            
            ad = Ad(
                token=token,
                title=title,
                description=description,
                url=url,
                district=district,
                special=is_special,
                latitude=latitude,
                longitude=longitude,
                extra={"raw_data": data},
            )
            
            return ad
            
        except Exception as e:
            logger.error(f"Error extracting ad: {e}")
            return None
    
    def _build_search_filters(
        self,
        category: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build search filters payload."""
        filters = DEFAULT_SEARCH_FILTERS.copy()
        
        if category:
            if "form_data" not in filters:
                filters["form_data"] = {"data": {}}
            if "data" not in filters["form_data"]:
                filters["form_data"]["data"] = {}
            
            filters["form_data"]["data"]["category"] = {"str": {"value": category}}
        
        return filters
    
    async def _fetch_ad_details(self, token: str, ad_id: str) -> Dict[str, Any]:
        """Fetch detailed ad information."""
        url = self._ad_url_template.format(token=token, ad_id=ad_id)
        return await self._make_request("GET", url)
    
    def _get_next_pagination(self, ads: List[Ad]) -> Optional[Dict[str, Any]]:
        """Get pagination data for next page."""
        return None
    
    async def _search_page(
        self,
        city_id: str,
        pagination_data: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
    ) -> List[Ad]:
        """Search a single page and extract ads."""
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
        
        ads = []
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
                    if self._should_filter(ad.title, ad.description):
                        logger.debug(f"Filtered: {ad.title[:50]}")
                        continue
                    
                    ads.append(ad)
                    
                    if self.on_ad_found:
                        await self._maybe_call(self.on_ad_found, ad)
                        
            except Exception as e:
                logger.error(f"Error fetching ad {token}: {e}")
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
        
        return ads
    
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
            category: Category to filter by (default: config.category)
            
        Returns:
            List of Ad objects found
        """
        city_id = city_id or self.config.city_id
        max_pages = max_pages or self.config.max_pages
        category = category or self.config.category
        
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
            
            if len(ads) == 0:
                break
            
            pagination_data = self._get_next_pagination(ads)
            if not pagination_data:
                break
            
            delay = self.config.delay_between_requests
            if delay > 0:
                await asyncio.sleep(delay)
        
        logger.info(f"Scraped {len(all_ads)} ads total")
        return all_ads
    
    async def stream(
        self,
        city_id: Optional[str] = None,
        max_pages: Optional[int] = None,
        category: Optional[str] = None,
    ) -> AsyncIterator[Ad]:
        """
        Stream ads as they're found (async generator).
        
        Example:
            async with scraper:
                async for ad in scraper.stream(max_pages=10):
                    await process_ad(ad)
        """
        city_id = city_id or self.config.city_id
        max_pages = max_pages or self.config.max_pages
        category = category or self.config.category
        
        pagination_data = None
        
        for page in range(max_pages):
            logger.info(f"Streaming page {page + 1}/{max_pages}")
            
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
                            
                            if self.on_ad_found:
                                await self._maybe_call(self.on_ad_found, ad)
                
                except Exception as e:
                    logger.error(f"Error fetching ad {token}: {e}")
                    if self.on_error:
                        await self._maybe_call(self.on_error, e)
            
            if not widgets:
                break
            
            pagination_data = None
            
            delay = self.config.delay_between_requests
            if delay > 0:
                await asyncio.sleep(delay)
    
    async def scrape_map(
        self,
        category: Optional[str] = None,
        bbox: Optional[Dict[str, float]] = None,
        city_id: Optional[str] = None,
        zoom: Optional[float] = None,
    ) -> List[MapAd]:
        """
        Scrape ads from the map view API.
        
        This returns ads with their coordinates, suitable for displaying on a map.
        
        Args:
            category: Category to filter by (default: config.category)
            bbox: Bounding box for map view (default: config.map_bbox)
            city_id: City ID (default: config.city_id)
            zoom: Zoom level (default: config.map_zoom)
            
        Returns:
            List of MapAd objects with coordinates
            
        Example:
            config = ScraperConfig.for_map_view(
                category="apartment-sell",
                bbox={
                    "min_latitude": 35.228049,
                    "min_longitude": 51.107464,
                    "max_latitude": 36.119353,
                    "max_longitude": 51.636307,
                },
                zoom=9.0,
            )
            scraper = DivarScraper(config=config)
            
            async with scraper:
                map_ads = await scraper.scrape_map()
                # Use map_ads for displaying on a map
        """
        category = category or self.config.category
        bbox = bbox or self.config.map_bbox
        city_id = city_id or self.config.city_id
        zoom = zoom or self.config.map_zoom
        
        if not bbox:
            # Default Tehran bbox
            bbox = {
                "min_latitude": 35.228049,
                "min_longitude": 51.107464,
                "max_latitude": 36.119353,
                "max_longitude": 51.636307,
            }
        
        # Build the map API request
        payload = {
            "city_ids": [city_id],
            "search_data": self._build_search_filters(category),
            "camera_info": {
                "bbox": bbox,
                "place_hash": f"{city_id}||{category}|",
                "zoom": zoom,
            },
        }
        
        try:
            response = await self._make_request("POST", self._map_url, json=payload)
        except Exception as e:
            logger.error(f"Map scrape failed: {e}")
            if self.on_error:
                await self._maybe_call(self.on_error, e)
            return []
        
        # Parse the map response
        map_ads = []
        widgets = response.get("list_widgets", [])
        
        for widget in widgets:
            data = widget.get("data", {})
            ad_data = data.get("action", {}).get("payload", {})
            
            if not ad_data:
                continue
            
            try:
                map_ad = MapAd.from_map_response(ad_data)
                map_ads.append(map_ad)
                
                if self.on_ad_found:
                    # Convert to Ad for callback compatibility
                    full_ad = await self._fetch_ad_details(map_ad.token, map_ad.token)
                    ad = self._extract_ad_from_response(full_ad, map_ad.token)
                    if ad:
                        await self._maybe_call(self.on_ad_found, ad)
                        
            except Exception as e:
                logger.error(f"Error parsing map ad: {e}")
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
        
        logger.info(f"Scraped {len(map_ads)} ads from map")
        return map_ads
    
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
        """
        city_id = city_id or self.config.city_id
        max_pages = max_pages_per_cycle
        category = category or self.config.category
        seen_tokens = set()
        
        while True:
            logger.info("Starting monitoring cycle")
            
            new_ads = []
            
            async for ad in self.stream(
                city_id=city_id,
                max_pages=max_pages,
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
    
    def load_cities(self, filepath: Optional[str] = None) -> List[City]:
        """
        Load cities from a JSON file.
        
        Args:
            filepath: Path to cities JSON file (default: config.cities_file)
            
        Returns:
            List of City objects
        """
        filepath = filepath or self.config.cities_file
        
        if not filepath:
            return []
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            cities = []
            if isinstance(data, list):
                for item in data:
                    cities.append(City.from_json(item))
            elif isinstance(data, dict):
                # Handle different JSON structures
                for key, value in data.items():
                    if isinstance(value, dict):
                        cities.append(City.from_json(value))
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                cities.append(City.from_json(item))
            
            return cities
            
        except Exception as e:
            logger.error(f"Error loading cities from {filepath}: {e}")
            return []
    
    def load_districts(self, filepath: Optional[str] = None) -> List[District]:
        """
        Load districts from a JSON file.
        
        Args:
            filepath: Path to districts JSON file (default: config.districts_file)
            
        Returns:
            List of District objects
        """
        filepath = filepath or self.config.districts_file
        
        if not filepath:
            return []
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            districts = []
            if isinstance(data, list):
                for item in data:
                    districts.append(District.from_json(item))
            elif isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, dict):
                        districts.append(District.from_json(value))
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                districts.append(District.from_json(item))
            
            return districts
            
        except Exception as e:
            logger.error(f"Error loading districts from {filepath}: {e}")
            return []
    
    async def search_by_city_and_district(
        self,
        city_id: str,
        district_id: Optional[str] = None,
        category: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> List[Ad]:
        """
        Search ads by city and optionally district.
        
        Args:
            city_id: City ID to search
            district_id: District ID to filter by (optional)
            category: Category to filter by
            max_pages: Maximum pages to scrape
            
        Returns:
            List of Ad objects
        """
        # Build custom filters with district if provided
        filters = self._build_search_filters(category)
        
        if district_id:
            if "form_data" not in filters:
                filters["form_data"] = {"data": {}}
            if "data" not in filters["form_data"]:
                filters["form_data"]["data"] = {}
            
            filters["form_data"]["data"]["districts"] = {
                "repeated_string": {"value": [district_id]}
            }
        
        city_id = city_id or self.config.city_id
        max_pages = max_pages or self.config.max_pages
        
        all_ads: List[Ad] = []
        pagination_data = None
        
        for page in range(max_pages):
            logger.info(f"Scanning page {page + 1}/{max_pages}")
            
            payload = {
                "city_ids": [city_id],
                "pagination_data": pagination_data,
                "disable_recommendation": False,
                "map_state": {"camera_info": {"bbox": {}}},
                "search_data": filters,
            }
            
            try:
                response = await self._make_request("POST", self._search_url, json=payload)
            except Exception as e:
                logger.error(f"Search failed: {e}")
                if self.on_error:
                    await self._maybe_call(self.on_error, e)
                break
            
            ads = []
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
                            ads.append(ad)
                            
                            if self.on_ad_found:
                                await self._maybe_call(self.on_ad_found, ad)
                
                except Exception as e:
                    logger.error(f"Error fetching ad {token}: {e}")
                    if self.on_error:
                        await self._maybe_call(self.on_error, e)
            
            if not widgets:
                break
            
            pagination_data = self._get_next_pagination(ads)
            if not pagination_data:
                break
            
            delay = self.config.delay_between_requests
            if delay > 0:
                await asyncio.sleep(delay)
            
            all_ads.extend(ads)
        
        return all_ads
