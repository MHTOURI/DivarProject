# Divar Scraper Library

A modular, extensible Python library for scraping listings from [Divar.ir](https://divar.ir), a popular Iranian classifieds website.

## Features

- **Async-first design** - Built for modern async Python applications
- **Modular & extensible** - Easy to customize and extend
- **Multiple storage backends** - Memory, SQLite, or JSON storage
- **Callback support** - Process ads in real-time as they're found
- **Streaming API** - Process ads one at a time without waiting
- **Monitoring mode** - Continuously monitor for new listings
- **Easy to build APIs** - Use as a foundation for your own API service

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
        keywords_to_filter=["املاک", "مشاور"],  # Filter agency ads
    )
    
    scraper = DivarScraper(config=config)
    
    async with scraper:
        ads = await scraper.search(max_pages=5)
        
        for ad in ads:
            print(f"{ad.title} - {ad.district}")

asyncio.run(main())
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

This library is designed to be the backend for your own API. Here's a complete FastAPI example:

```python
from fastapi import FastAPI, BackgroundTasks
from divar import DivarScraper, ScraperConfig
from divar.utils import SQLiteStorage

app = FastAPI()
storage = SQLiteStorage("ads.db")
scraper = DivarScraper()

@app.post("/scrape")
async def start_scrape(background_tasks: BackgroundTasks):
    async def scrape():
        async with scraper:
            async for ad in scraper.stream(max_pages=10):
                await storage.save(ad)
    
    background_tasks.add_task(scrape)
    return {"status": "started"}

@app.get("/ads")
async def get_ads():
    ads = await storage.get_all()
    return {"ads": [ad.to_dict() for ad in ads]}
```

See `examples/api_example.py` for a complete working API.

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

**Parameters:**
- `config` - Scraper configuration
- `on_ad_found` - Callback called for each ad found (sync or async)
- `on_error` - Callback called on errors
- `on_rate_limit` - Callback called when rate limited

#### Methods

**`async with scraper:`** - Context manager for lifecycle management

**`await scraper.start()`** - Initialize the scraper

**`await scraper.close()`** - Cleanup resources

**`await scraper.search(city_id=None, max_pages=None, category=None) -> List[Ad]`**
- Search for ads
- Returns list of Ad objects

**`async for ad in scraper.stream(city_id=None, max_pages=None, category=None)`**
- Async generator that yields ads as they're found
- Useful for real-time processing

**`async for batch in scraper.monitor(interval=60, max_pages_per_cycle=5)`**
- Continuously monitor for new ads
- Yields batches of new ads at each interval

### `ScraperConfig`

Configuration for the scraper.

```python
ScraperConfig(
    max_pages: int = 10,              # Max pages to scrape
    delay_between_requests: float = 2.0,  # Delay between requests (seconds)
    max_retries: int = 3,             # Max retry attempts
    timeout: int = 30,                # Request timeout (seconds)
    user_agent: str = None,           # Custom user agent
    proxies: List[str] = [],          # Proxy URLs
    city_id: str = "1",               # City ID (1=Tehran)
    category: str = "",               # Category filter
    keywords_to_ignore: List[str] = [],   # Skip ads containing these
    keywords_to_filter: List[str] = [],   # Filter out ads containing these
)
```

### `Ad`

Data model for an advertisement.

```python
Ad(
    token: str,           # Unique ID
    title: str,           # Title
    description: str,     # Description
    url: str,             # Web URL
    district: str,        # District/area
    price: str = None,    # Price if available
    category: str = "",   # Category
    images: List[str] = [],  # Image URLs
    phone: str = None,    # Contact phone
    special: bool = False,   # Special listing flag
    extra: dict = {},     # Additional data
)
```

**Methods:**
- `ad.to_dict()` - Convert to dictionary

### Storage Backends

#### MemoryStorage

In-memory storage (fast, data lost on restart).

```python
from divar.utils import MemoryStorage

storage = MemoryStorage()
await storage.save(ad)
ads = await storage.get_all()
```

#### SQLiteStorage

SQLite database storage (persistent, queryable).

```python
from divar.utils import SQLiteStorage

storage = SQLiteStorage("ads.db")
await storage.save(ad)
ads = await storage.get_all(limit=20, offset=0)
ads = await storage.get_by_district("تهران")
ads = await storage.search("پیشخوان")
count = await storage.count()
```

#### JSONStorage

JSON file storage (simple, human-readable).

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

### API Server

```bash
pip install fastapi uvicorn
python examples/api_example.py
# Visit http://localhost:8000/docs
```

## Project Structure

```
divar-scraper/
├── divar/
│   ├── __init__.py       # Package exports
│   ├── scraper.py        # Main DivarScraper class
│   ├── models.py         # Data models (Ad, ScraperConfig)
│   ├── exceptions.py     # Custom exceptions
│   └── utils/
│       ├── __init__.py
│       └── storage.py    # Storage backends
├── examples/
│   ├── basic_usage.py    # Basic usage example
│   └── api_example.py    # FastAPI example
├── pyproject.toml        # Package configuration
└── README.md
```

## Running as a Module

After installing, you can use it in your projects:

```python
# In your project
from divar import DivarScraper, ScraperConfig
from divar.utils import SQLiteStorage

# Build your own scraper service
class MyScraperService:
    def __init__(self, db_path: str):
        self.storage = SQLiteStorage(db_path)
        self.config = ScraperConfig(
            max_pages=10,
            delay_between_requests=3.0,
        )
        self.scraper = DivarScraper(config=self.config)
    
    async def scrape_and_save(self, max_pages: int = 5):
        async with self.scraper:
            async for ad in self.scraper.stream(max_pages=max_pages):
                await self.storage.save(ad)
    
    async def get_ads(self, district: str = None):
        if district:
            return await self.storage.get_by_district(district)
        return await self.storage.get_all()
```

## License

MIT License - feel free to use this library in your projects.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## Disclaimer

This library is for educational and personal use. Please respect Divar.ir's terms of service and rate limits. Use responsibly.
