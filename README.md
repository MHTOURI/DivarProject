# Divar Scraper Library

A modular, extensible Python library for scraping listings from [Divar.ir](https://divar.ir), a popular Iranian classifieds website.

## Features

- **Async-first design** - Built for modern async Python applications
- **Map View Support** - Scrape ads with coordinates for map display
- **Multiple Categories** - Support for all Divar categories (residential, commercial, etc.)
- **City & District Support** - Load cities and districts from JSON files
- **Multiple Storage Backends** - Memory, SQLite, or JSON storage
- **Callback Support** - Process ads in real-time as they're found
- **Streaming API** - Process ads one at a time without waiting
- **Monitoring Mode** - Continuously monitor for new listings
- **Easy to build APIs** - Use as a foundation for your own API service
- **Frontend-Ready** - Export data in formats perfect for map displays

## Categories Supported

```python
from divar import CATEGORIES

# All available categories:
# Residential - Sell
"house-villa-sell",
"apartment-sell",
"suite-apartment",
"residential-sell",
"commercial-sell",
"office-sell",
"presell",
"shop-sell",
"industry-agriculture-business-sell",

# Residential - Rent
"house-villa-rent",
"apartment-rent",
"suite-apartment",
"residential-rent",
"commercial-rent",
"office-rent",
"temporary-rent",
"shop-rent",
"industry-agriculture-business-rent",
```

## Installation

```bash
pip install divar-scraper
```

For API development:

```bash
pip install divar-scraper[api]
```

## Quick Start

### Basic Usage

```python
import asyncio
from divar import DivarScraper, ScraperConfig

async def main():
    config = ScraperConfig(
        max_pages=5,
        delay_between_requests=3.0,
        category="apartment-sell",  # See CATEGORIES for all options
    )
    
    scraper = DivarScraper(config=config)
    
    async with scraper:
        ads = await scraper.search(max_pages=5)
        
        for ad in ads:
            print(f"{ad.title} - {ad.district}")

asyncio.run(main())
```

### Map View Scraping

Scrape ads with coordinates for displaying on a map:

```python
from divar import DivarScraper, ScraperConfig

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
    
    for ad in map_ads:
        print(f"{ad.title} at ({ad.latitude}, {ad.longitude})")
        # Use these coordinates for map display
```

### With Storage

```python
from divar.utils import SQLiteStorage

storage = SQLiteStorage("ads.db")

async with scraper:
    async for ad in scraper.stream(max_pages=10):
        await storage.save(ad)
        print(f"Saved: {ad.title}")
```

### With Callbacks

```python
def on_ad_found(ad):
    # Process ad in real-time
    print(f"New ad: {ad.title}")
    # Save to database, send notification, etc.

scraper = DivarScraper(
    config=config,
    on_ad_found=on_ad_found,
)
```

## Building Your Own API

### FastAPI Example with Map Support

```python
from fastapi import FastAPI
from divar import DivarScraper, ScraperConfig
from divar.utils import SQLiteStorage

app = FastAPI()
storage = SQLiteStorage("ads.db")
scraper = DivarScraper()

@app.get("/map/{category}")
async def get_map_ads(category: str):
    """Get ads with coordinates for map display."""
    nearby = await storage.get_nearby(
        latitude=35.6892,
        longitude=51.3890,
        radius_km=50
    )
    
    # Filter by category
    ads = [ad for ad in nearby if ad.category == category]
    
    return {
        "ads": [ad.to_dict() for ad in ads],
        "total": len(ads)
    }

@app.get("/ads")
async def get_ads():
    ads = await storage.get_all()
    return {"ads": [ad.to_dict() for ad in ads]}
```

See `examples/api_example.py` for a complete working API with map endpoint.

## Frontend Integration

### Display Ads on a Map (Leaflet.js Example)

```html
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        #map { height: 600px; }
    </style>
</head>
<body>
    <div id="map"></div>
    
    <script>
        // Initialize map
        var map = L.map('map').setView([35.6892, 51.3890], 10);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        
        // Fetch ads from your API
        fetch('/api/map/apartment-sell')
            .then(res => res.json())
            .then(data => {
                data.ads.forEach(ad => {
                    L.marker([ad.latitude, ad.longitude])
                        .addTo(map)
                        .bindPopup(`<strong>${ad.title}</strong><br>${ad.price}`);
                });
            });
    </script>
</body>
</html>
```

## Documentation

### `DivarScraper`

Main scraper class.

#### Constructor

```python
DivarScraper(
    config: ScraperConfig = ScraperConfig(),
    on_ad_found: Callable[[Ad], Any] = None,
    on_error: Callable[[Exception], Any] = None,
    on_rate_limit: Callable[[int], Any] = None,
)
```

#### Methods

**`async with scraper:`** - Context manager for lifecycle management

**`await scraper.start()`** - Initialize the scraper

**`await scraper.close()`** - Cleanup resources

**`await scraper.search(city_id=None, max_pages=None, category=None) -> List[Ad]`**
- Search for ads using the list view API
- Returns list of Ad objects

**`async for ad in scraper.stream(city_id=None, max_pages=None, category=None)`**
- Async generator that yields ads as they're found
- Useful for real-time processing

**`await scraper.scrape_map(category=None, bbox=None, city_id=None, zoom=None) -> List[MapAd]`**
- Scrape ads from the map view API
- Returns MapAd objects with coordinates
- Perfect for displaying on maps

**`async for batch in scraper.monitor(interval=60, max_pages_per_cycle=5)`**
- Continuously monitor for new ads
- Yields batches of new ads at each interval

### `ScraperConfig`

Configuration for the scraper.

```python
ScraperConfig(
    max_pages: int = 10,
    delay_between_requests: float = 2.0,
    max_retries: int = 3,
    timeout: int = 30,
    user_agent: str = None,
    proxies: List[str] = [],
    city_id: str = "1",
    category: str = "residential-rent",
    keywords_to_ignore: List[str] = [],
    keywords_to_filter: List[str] = [],
    map_enabled: bool = False,
    map_bbox: Dict[str, float] = None,
    map_zoom: float = 9.0,
    cities_file: str = None,
    districts_file: str = None,
)
```

#### Class Methods

**`ScraperConfig.for_category(category, city_id="1")`** - Create config for a category

**`ScraperConfig.for_map_view(category, bbox, city_id="1", zoom=9.0)`** - Create config for map scraping

### `Ad`

Data model for an advertisement.

```python
Ad(
    token: str,
    title: str,
    description: str = "",
    url: str = "",
    district: str = "",
    price: str = None,
    category: str = "",
    images: List[str] = [],
    phone: str = None,
    created_at: datetime = None,
    special: bool = False,
    latitude: float = None,
    longitude: float = None,
    extra: dict = {},
)
```

**Methods:**
- `ad.to_dict()` - Convert to dictionary

### `MapAd`

Data model for map view advertisements (includes coordinates).

```python
MapAd(
    token: str,
    title: str,
    latitude: float,
    longitude: float,
    price: str = None,
    district: str = "",
    url: str = "",
    category: str = "",
    image: str = None,
)
```

**Methods:**
- `ad.to_dict()` - Convert to dictionary (includes latitude/longitude)

### Constants

**`CATEGORIES`** - List of all supported Divar categories

**`CITY_IDS`** - Dictionary of major city names to IDs

**`DEFAULT_SEARCH_FILTERS`** - Default search filter configuration

### Storage Backends

#### MemoryStorage

```python
from divar.utils import MemoryStorage

storage = MemoryStorage()
await storage.save(ad)
ads = await storage.get_all()
```

#### SQLiteStorage

```python
from divar.utils import SQLiteStorage

storage = SQLiteStorage("ads.db")
await storage.save(ad)
ads = await storage.get_all(limit=20, offset=0)
ads = await storage.get_by_district("تهران")
ads = await storage.search("پیشخوان")
ads = await storage.get_nearby(35.6892, 51.3890, radius_km=5)
count = await storage.count()
count = await storage.count_by_category("apartment-sell")
```

#### JSONStorage

```python
from divar.utils import JSONStorage

storage = JSONStorage("ads.json")
await storage.save(ad)
ads = await storage.get_all()
```

## Examples

### Basic Scraping

```bash
python examples/basic_usage.py
```

### API Server with Map Support

```bash
pip install fastapi uvicorn
python examples/api_example.py
# Visit http://localhost:8000
# API docs: http://localhost:8000/docs
```

## City and District Files

You can load cities and districts from JSON files:

```python
scraper = DivarScraper(config=ScraperConfig(
    cities_file="cities.json",
    districts_file="districts.json",
))

# Load cities
cities = scraper.load_cities()
for city in cities:
    print(f"{city.name}: {city.id}")

# Load districts
districts = scraper.load_districts("districts.json")
for district in districts:
    print(f"{district.name}: {district.id}")
```

JSON format for cities:
```json
[
  {
    "id": 1,
    "name": "تهران",
    "slug": "tehran",
    "districts": [
      {"id": "178", "name": "انسان‌وجان", "slug": "ensan-ojan"}
    ]
  }
]
```

## Project Structure

```
divar-scraper/
├── divar/
│   ├── __init__.py       # Package exports
│   ├── scraper.py        # Main DivarScraper class
│   ├── models.py         # Data models (Ad, MapAd, ScraperConfig, etc.)
│   ├── exceptions.py     # Custom exceptions
│   ├── py.typed          # Type hints marker
│   └── utils/
│       ├── __init__.py
│       └── storage.py    # Storage backends
├── examples/
│   ├── basic_usage.py    # Basic usage example
│   └── api_example.py    # FastAPI example with map support
├── pyproject.toml        # Package configuration
└── README.md
```

## License

MIT License - feel free to use this library in your projects.

## Disclaimer

This library is for educational and personal use. Please respect Divar.ir's terms of service and rate limits. Use responsibly.
