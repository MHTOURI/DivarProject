"""
Basic usage example for Divar scraper library.

This example shows how to use the DivarScraper to scrape ads
and save them to a SQLite database.
"""

import asyncio
import logging
from divar import DivarScraper, ScraperConfig
from divar.utils import SQLiteStorage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def main():
    # Create configuration
    config = ScraperConfig(
        max_pages=5,
        delay_between_requests=3.0,  # Be respectful to the server
        keywords_to_filter=["املاک", "مشاور", "بنگاه"],  # Filter out agency ads
    )
    
    # Create storage backend
    storage = SQLiteStorage("divar_ads.db")
    
    # Create scraper with callbacks
    scraper = DivarScraper(
        config=config,
        on_ad_found=lambda ad: print(f"Found: {ad.title[:50]}..."),
    )
    
    async with scraper:
        # Search for ads
        ads = await scraper.search(max_pages=5)
        
        print(f"\nFound {len(ads)} ads\n")
        
        # Save to storage
        for ad in ads:
            saved = await storage.save(ad)
            if saved:
                print(f"Saved: {ad.title[:50]}")
    
    # Query saved ads
    print("\n--- Saved Ads ---")
    saved_ads = await storage.get_all(limit=10)
    for ad in saved_ads:
        print(f"- {ad.title} ({ad.district})")


async def streaming_example():
    """Example showing how to stream ads as they're found."""
    config = ScraperConfig(max_pages=3, delay_between_requests=2.0)
    storage = SQLiteStorage("divar_ads.db")
    
    scraper = DivarScraper(config=config)
    
    async with scraper:
        async for ad in scraper.stream(max_pages=3):
            # Process each ad as it's found
            await storage.save(ad)
            print(f"Streamed: {ad.title[:50]} - {ad.district}")


async def monitoring_example():
    """Example showing how to monitor for new ads continuously."""
    config = ScraperConfig(
        max_pages=3,
        delay_between_requests=2.0,
        keywords_to_filter=["املاک", "مشاور"],
    )
    
    storage = SQLiteStorage("divar_ads.db")
    
    async def notify_new_ad(ad):
        """Callback for new ads."""
        print(f"\n🔔 NEW AD: {ad.title}")
        print(f"   District: {ad.district}")
        print(f"   URL: {ad.url}\n")
    
    scraper = DivarScraper(
        config=config,
        on_ad_found=notify_new_ad,
    )
    
    async with scraper:
        # Monitor for 5 minutes (for demo purposes)
        async for batch in scraper.monitor(
            interval=60.0,  # Check every 60 seconds
            max_pages_per_cycle=2,
            timeout=300,  # Stop after 5 minutes
        ):
            print(f"Batch of {len(batch)} new ads received")
            for ad in batch:
                await storage.save(ad)


if __name__ == "__main__":
    # Run basic example
    asyncio.run(main())
    
    # Uncomment to run other examples
    # asyncio.run(streaming_example())
    # asyncio.run(monitoring_example())
