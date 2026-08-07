"""
Divar Scraper Library

A modular, extensible Python library for scraping Divar.ir listings.
Designed to be used as a building block for custom APIs and applications.

Installation:
    pip install divar-scraper

Usage:
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
    
    Map view example:
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
"""

from divar.scraper import DivarScraper
from divar.models import (
    Ad,
    MapAd,
    ScraperConfig,
    City,
    District,
    CATEGORIES,
    CITY_IDS,
    DEFAULT_SEARCH_FILTERS,
)
from divar.exceptions import DivarError, RateLimitError, ScraperError

__version__ = "1.0.0"
__author__ = "DivarProject"
__all__ = [
    "DivarScraper",
    "Ad",
    "MapAd",
    "ScraperConfig",
    "City",
    "District",
    "CATEGORIES",
    "CITY_IDS",
    "DEFAULT_SEARCH_FILTERS",
    "DivarError",
    "RateLimitError",
    "ScraperError",
]
