"""
FastAPI example for Divar scraper library with map support.

This example shows how to build a REST API with map visualization support.

Run:
    pip install fastapi uvicorn
    python api_example.py
    
Visit:
    - http://localhost:8000/docs - API documentation
    - http://localhost:8000/ - Simple map demo page
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
import asyncio
import logging
from datetime import datetime

from divar import (
    DivarScraper, 
    ScraperConfig, 
    Ad, 
    MapAd,
    CATEGORIES,
    CITY_IDS,
)
from divar.utils import SQLiteStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Divar Scraper API",
    description="API for scraping Divar.ir listings with map support",
    version="1.0.0"
)

scraper: Optional[DivarScraper] = None
storage = SQLiteStorage("divar_ads.db")
scraper_lock = asyncio.Lock()


# ============== Pydantic Models ==============

class ScraperRequest(BaseModel):
    city_id: str = Field(default="1", description="City ID (1=Tehran)")
    max_pages: int = Field(default=5, ge=1, le=50, description="Max pages to scrape")
    category: str = Field(default="residential-rent", description="Category to scrape")
    delay: float = Field(default=3.0, ge=1.0, le=10.0, description="Delay between requests")


class MapScraperRequest(BaseModel):
    category: str = Field(default="apartment-sell", description="Category to scrape")
    min_latitude: float = Field(default=35.228049, description="Min latitude")
    min_longitude: float = Field(default=51.107464, description="Min longitude")
    max_latitude: float = Field(default=36.119353, description="Max latitude")
    max_longitude: float = Field(default=51.636307, description="Max longitude")
    zoom: float = Field(default=9.0, ge=1.0, le=20.0, description="Zoom level")


class AdResponse(BaseModel):
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
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: Optional[str] = None


class MapAdResponse(BaseModel):
    """Response model for map ads (includes coordinates)."""
    token: str
    title: str
    latitude: float
    longitude: float
    price: Optional[str] = None
    district: str = ""
    url: str = ""
    category: str = ""
    image: Optional[str] = None


class AdsResponse(BaseModel):
    ads: List[AdResponse]
    total: int
    page: int
    page_size: int


class MapAdsResponse(BaseModel):
    ads: List[MapAdResponse]
    total: int
    bbox: dict


class StatsResponse(BaseModel):
    total_ads: int
    categories: dict
    districts: List[dict]


# ============== Startup/Shutdown ==============

@app.on_event("startup")
async def startup():
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
    global scraper
    if scraper:
        await scraper.close()
        logger.info("Scraper closed")


# ============== Main Endpoints ==============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Simple map demo page."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Divar Map Demo</title>
        <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            #map { height: 100vh; width: 100%; }
            .info { position: absolute; top: 10px; right: 10px; z-index: 1000; 
                    background: white; padding: 10px; border-radius: 5px; 
                    box-shadow: 0 0 10px rgba(0,0,0,0.2); }
        </style>
    </head>
    <body>
        <div class="info">
            <h3>Divar Map Demo</h3>
            <p>Loading ads from API...</p>
        </div>
        <div id="map"></div>
        <script>
            // Initialize map centered on Tehran
            var map = L.map('map').setView([35.6892, 51.3890], 10);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);
            
            // Fetch ads from API
            fetch('/api/map/apartment-sell')
                .then(res => res.json())
                .then(data => {
                    document.querySelector('.info').innerHTML = 
                        `<h3>Divar Map Demo</h3><p>${data.total} ads loaded</p>`;
                    
                    // Add markers for each ad
                    data.ads.forEach(ad => {
                        var marker = L.marker([ad.latitude, ad.longitude]).addTo(map);
                        marker.bindPopup(`
                            <strong>${ad.title}</strong><br>
                            ${ad.district}<br>
                            ${ad.price || '価格未定'}
                            <br>
                            <a href="${ad.url}" target="_blank">View on Divar</a>
                        `);
                    });
                })
                .catch(err => {
                    console.error(err);
                    document.querySelector('.info').innerHTML = 
                        '<h3>Error</h3><p>Could not load ads</p>';
                });
        </script>
    </body>
    </html>
    """


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get scraping statistics."""
    total = await storage.count()
    
    # Count by category
    categories = {}
    for cat in CATEGORIES:
        count = await storage.count_by_category(cat)
        if count > 0:
            categories[cat] = count
    
    # Get districts
    ads = await storage.get_all(limit=1000)
    districts = {}
    for ad in ads:
        if ad.district:
            districts[ad.district] = districts.get(ad.district, 0) + 1
    
    return StatsResponse(
        total_ads=total,
        categories=categories,
        districts=[{"name": k, "count": v} for k, v in sorted(districts.items(), key=lambda x: -x[1])[:20]]
    )


@app.get("/ads", response_model=AdsResponse)
async def get_ads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    district: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
):
    """Get scraped ads with pagination and filtering."""
    offset = (page - 1) * page_size
    
    if search:
        ads = await storage.search(search, limit=page_size, offset=offset)
    elif district:
        ads = await storage.get_by_district(district, limit=page_size, offset=offset)
    elif category:
        ads = await storage.get_by_category(category, limit=page_size, offset=offset)
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


@app.get("/map/{category}", response_model=MapAdsResponse)
async def get_map_ads(
    category: str,
    min_lat: float = Query(35.228049, description="Min latitude"),
    min_lon: float = Query(51.107464, description="Min longitude"),
    max_lat: float = Query(36.119353, description="Max latitude"),
    max_lon: float = Query(51.636307, description="Max longitude"),
    zoom: float = Query(9.0, description="Zoom level"),
    limit: int = Query(500, ge=1, le=2000, description="Max ads to return"),
):
    """
    Get ads for map display.
    
    Returns ads with coordinates for the given category within the bounding box.
    """
    # First try to get from storage
    nearby = await storage.get_nearby(
        (min_lat + max_lat) / 2,
        (min_lon + max_lon) / 2,
        radius_km=50,  # Large radius to cover the bbox
        limit=limit,
    )
    
    # Filter by category and bbox
    filtered = [
        ad for ad in nearby
        if ad.category == category
        and min_lat <= ad.latitude <= max_lat
        and min_lon <= ad.longitude <= max_lon
    ]
    
    return MapAdsResponse(
        ads=[MapAdResponse(**ad.to_dict()) for ad in filtered],
        total=len(filtered),
        bbox={
            "min_latitude": min_lat,
            "min_longitude": min_lon,
            "max_latitude": max_lat,
            "max_longitude": max_lon,
        }
    )


@app.post("/scrape")
async def start_scrape(
    request: ScraperRequest,
    background_tasks: BackgroundTasks,
):
    """Start scraping Divar in the background."""
    async def scrape_task():
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
        "category": request.category,
        "max_pages": request.max_pages,
    }


@app.post("/scrape/map")
async def start_map_scrape(
    request: MapScraperRequest,
    background_tasks: BackgroundTasks,
):
    """Start scraping map data in the background."""
    async def scrape_map_task():
        async with scraper_lock:
            config = ScraperConfig.for_map_view(
                category=request.category,
                bbox={
                    "min_latitude": request.min_latitude,
                    "min_longitude": request.min_longitude,
                    "max_latitude": request.max_latitude,
                    "max_longitude": request.max_longitude,
                },
                zoom=request.zoom,
            )
            
            temp_scraper = DivarScraper(config=config)
            
            async with temp_scraper:
                map_ads = await temp_scraper.scrape_map()
                
                for ad in map_ads:
                    await storage.save(ad)
                    logger.info(f"Saved map ad: {ad.title[:50]}")
    
    background_tasks.add_task(scrape_map_task)
    
    return {
        "message": "Map scraping started",
        "category": request.category,
        "bbox": {
            "min_latitude": request.min_latitude,
            "min_longitude": request.min_longitude,
            "max_latitude": request.max_latitude,
            "max_longitude": request.max_longitude,
        },
    }


@app.get("/categories")
async def get_categories():
    """Get all available categories."""
    return {
        "categories": CATEGORIES,
        "count": len(CATEGORIES),
    }


@app.get("/cities")
async def get_cities():
    """Get major city IDs."""
    return {
        "cities": CITY_IDS,
        "count": len(CITY_IDS),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
