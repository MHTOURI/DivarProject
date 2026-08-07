"""
FastAPI example for Divar scraper library.

This example shows how to build a REST API on top of the Divar scraper.
Users can use this as a starting point for their own API service.

Run:
    pip install fastapi uvicorn
    python api_example.py
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List
import asyncio
import logging

from divar import DivarScraper, ScraperConfig
from divar.utils import SQLiteStorage
from divar.models import Ad

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Divar Scraper API",
    description="API for scraping Divar.ir listings",
    version="1.0.0"
)

# Global scraper instance
scraper: Optional[DivarScraper] = None
storage = SQLiteStorage("divar_ads.db")
scraper_lock = asyncio.Lock()


# Pydantic models for API
class ScraperRequest(BaseModel):
    """Request model for starting a scrape."""
    city_id: str = Field(default="1", description="City ID (1=Tehran)")
    max_pages: int = Field(default=5, ge=1, le=50, description="Max pages to scrape")
    category: Optional[str] = Field(default=None, description="Category filter")
    delay: float = Field(default=3.0, ge=1.0, le=10.0, description="Delay between requests")


class AdResponse(BaseModel):
    """Response model for an ad."""
    token: str
    title: str
    description: str = ""
    url: str = ""
    district: str = ""
    price: Optional[str] = None
    category: str = ""
    images: List[str] = []
    phone: Optional[str] = None
    special: bool = False


class AdsResponse(BaseModel):
    """Response model for list of ads."""
    ads: List[AdResponse]
    total: int
    page: int
    page_size: int


# Startup event
@app.on_event("startup")
async def startup():
    """Initialize scraper on startup."""
    global scraper
    config = ScraperConfig(
        max_pages=10,
        delay_between_requests=3.0,
        keywords_to_filter=["املاک", "مشاور", "بنگاه"],
    )
    scraper = DivarScraper(config=config)
    await scraper.start()
    logger.info("Scraper initialized")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    global scraper
    if scraper:
        await scraper.close()
        logger.info("Scraper closed")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Divar Scraper API", "docs": "/docs"}


@app.get("/ads", response_model=AdsResponse)
async def get_ads(
    page: int = 1,
    page_size: int = 20,
    district: Optional[str] = None,
    search: Optional[str] = None,
):
    """
    Get scraped ads with pagination and filtering.
    
    - **page**: Page number (1-based)
    - **page_size**: Number of ads per page
    - **district**: Filter by district name
    - **search**: Search in title and description
    """
    offset = (page - 1) * page_size
    
    if search:
        ads = await storage.search(search, limit=page_size, offset=offset)
    elif district:
        ads = await storage.get_by_district(district, limit=page_size, offset=offset)
    else:
        ads = await storage.get_all(limit=page_size, offset=offset)
    
    total = await storage.count()
    
    return AdsResponse(
        ads=[AdResponse(**ad.to_dict()) for ad in ads],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get("/ads/{token}")
async def get_ad(token: str):
    """Get a specific ad by token."""
    ad = await storage.get(token)
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
    return AdResponse(**ad.to_dict())


@app.get("/stats")
async def get_stats():
    """Get scraping statistics."""
    total = await storage.count()
    return {"total_ads": total}


@app.post("/scrape")
async def start_scrape(
    request: ScraperRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start scraping Divar in the background.
    
    Returns immediately while scraping happens in background.
    """
    async def scrape_task():
        async with scraper_lock:
            config = ScraperConfig(
                max_pages=request.max_pages,
                delay_between_requests=request.delay,
                city_id=request.city_id,
                category=request.category,
                keywords_to_filter=["املاک", "مشاور", "بنگاه"],
            )
            
            # Create temporary scraper for this task
            temp_scraper = DivarScraper(config=config)
            
            async with temp_scraper:
                async for ad in temp_scraper.stream(
                    city_id=request.city_id,
                    max_pages=request.max_pages,
                    category=request.category,
                ):
                    await storage.save(ad)
                    logger.info(f"Saved: {ad.title[:50]}")
    
    background_tasks.add_task(scrape_task)
    
    return {
        "message": "Scraping started",
        "city_id": request.city_id,
        "max_pages": request.max_pages,
    }


@app.post("/scrape/sync")
async def scrape_sync(request: ScraperRequest):
    """
    Scrape Divar synchronously (blocks until complete).
    
    Use this for small scraping jobs or testing.
    """
    async with scraper_lock:
        config = ScraperConfig(
            max_pages=request.max_pages,
            delay_between_requests=request.delay,
            city_id=request.city_id,
            category=request.category,
            keywords_to_filter=["املاک", "مشاور", "بنگاه"],
        )
        
        temp_scraper = DivarScraper(config=config)
        
        async with temp_scraper:
            ads = await temp_scraper.search(
                city_id=request.city_id,
                max_pages=request.max_pages,
                category=request.category,
            )
            
            for ad in ads:
                await storage.save(ad)
        
        return {
            "message": f"Scraped {len(ads)} ads",
            "city_id": request.city_id,
            "max_pages": request.max_pages,
            "ads_found": len(ads),
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
