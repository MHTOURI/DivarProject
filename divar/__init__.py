"""
Divar Scraper Library

A modular, extensible Python library for scraping Divar.ir listings.
Designed to be used as a building block for custom APIs and applications.

Installation:
    pip install divar-scraper

Usage:
    from divar import DivarScraper
    
    scraper = DivarScraper()
    async with scraper:
        ads = await scraper.search_city("tehran", max_pages=5)
"""

from divar.scraper import DivarScraper
from divar.models import Ad, ScraperConfig
from divar.exceptions import DivarError, RateLimitError, ScraperError

__version__ = "1.0.0"
__author__ = "DivarProject"
__all__ = ["DivarScraper", "Ad", "ScraperConfig", "DivarError", "RateLimitError", "ScraperError"]
