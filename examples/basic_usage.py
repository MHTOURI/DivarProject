"""
Basic usage examples for Divar scraper library.
"""

import asyncio
import logging
from divar import (
    DivarScraper, 
    ScraperConfig, 
    Ad, 
    MapAd,
    CATEGORIES,
    CITY_IDS,
)
from divar.utils import SQLiteStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def example_basic_search():
    """Basic search example."""
    print("\n=== Basic Search Example ===\n")
    
    config = ScraperConfig(
        max_pages=2,
        delay_between_requests=3.0,
        category="residential-rent",
        keywords_to_filter=["املاک", "مشاور", "بنگاه"],
    )
    
    storage = SQLiteStorage("divar_ads.db")
    
    scraper = DivarScraper(
        config=config,
        on_ad_found=lambda ad: print(f"Found: {ad.title[:50]}..."),
    )
    
    async with scraper:
        ads = await scraper.search(max_pages=2)
        
        print(f"\nFound {len(ads)} ads\n")
        
        for ad in ads:
            saved = await storage.save(ad)
            if saved:
                print(f"Saved: {ad.title[:50]} - {ad.district}")


async def example_all_categories():
    """Example showing all available categories."""
    print("\n=== All Available Categories ===\n")
    
    for cat in CATEGORIES:
        print(f"  - {cat}")
    
    print(f"\nTotal categories: {len(CATEGORIES)}")


async def example_city_ids():
    """Example showing available city IDs."""
    print("\n=== Major City IDs ===\n")
    
    for city, city_id in CITY_IDS.items():
        print(f"  - {city}: {city_id}")


async def example_map_view():
    """Example showing map view scraping."""
    print("\n=== Map View Example ===\n")
    
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
        
        print(f"Found {len(map_ads)} ads on map\n")
        
        for ad in map_ads[:10]:  # Show first 10
            print(f"  {ad.title[:40]} at ({ad.latitude:.4f}, {ad.longitude:.4f})")
        
        if len(map_ads) > 10:
            print(f"  ... and {len(map_ads) - 10} more")


async def example_storage_operations():
    """Example showing storage operations."""
    print("\n=== Storage Operations Example ===\n")
    
    storage = SQLiteStorage("divar_ads.db")
    
    # Count total ads
    total = await storage.count()
    print(f"Total ads in database: {total}")
    
    # Count by category
    for cat in ["apartment-sell", "residential-rent", "house-villa-sell"]:
        count = await storage.count_by_category(cat)
        print(f"  {cat}: {count}")
    
    # Search
    results = await storage.search("پیشخوان")
    print(f"\nSearch for 'پیشخوان': {len(results)} results")
    
    # Get nearby (for map display)
    nearby = await storage.get_nearby(35.6892, 51.3890, radius_km=3)
    print(f"\nAds near Tehran center (3km): {len(nearby)}")


async def example_stream():
    """Example showing streaming ads."""
    print("\n=== Streaming Example ===\n")
    
    config = ScraperConfig(
        max_pages=3,
        delay_between_requests=2.0,
        category="apartment-rent",
    )
    
    scraper = DivarScraper(config=config)
    
    async with scraper:
        count = 0
        async for ad in scraper.stream(max_pages=3):
            print(f"Streamed: {ad.title[:40]} - {ad.district}")
            count += 1
            if count >= 10:  # Limit for demo
                break
        
        print(f"\nStreamed {count} ads total")


async def main():
    """Run all examples."""
    await example_all_categories()
    await example_city_ids()
    await example_basic_search()
    await example_map_view()
    await example_storage_operations()
    await example_stream()
    
    print("\n=== All Examples Completed ===\n")


if __name__ == "__main__":
    asyncio.run(main())
