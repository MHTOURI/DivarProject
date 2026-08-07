"""
Data models for Divar scraper.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


# All supported Divar categories
CATEGORIES = [
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
]

# Default search filters
DEFAULT_SEARCH_FILTERS = {
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


@dataclass
class Ad:
    """
    Represents a Divar advertisement/listing.
    """
    token: str
    title: str
    description: str = ""
    url: str = ""
    district: str = ""
    price: Optional[str] = None
    category: str = ""
    images: List[str] = field(default_factory=list)
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    special: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "token": self.token,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "district": self.district,
            "price": self.price,
            "category": self.category,
            "images": self.images,
            "phone": self.phone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "special": self.special,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "extra": self.extra,
        }
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Ad":
        """Create Ad from Divar API response."""
        seo = data.get("seo", {})
        web_info = seo.get("web_info", {})
        
        # Extract coordinates if available
        latitude = None
        longitude = None
        location = data.get("location", {})
        if location:
            latitude = location.get("latitude")
            longitude = location.get("longitude")
        
        return cls(
            token=data.get("token", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            url=data.get("share", {}).get("web_url", ""),
            district=web_info.get("district_persian", ""),
            price=data.get("price", ""),
            category=data.get("category", ""),
            images=data.get("images", []),
            phone=data.get("phone", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            special="ویژه" in data.get("title", "") or "special" in data.get("title", "").lower(),
            latitude=latitude,
            longitude=longitude,
            extra=data,
        )


@dataclass
class MapAd:
    """
    Represents an ad from the map view API.
    Contains coordinates for displaying on a map.
    """
    token: str
    title: str
    latitude: float
    longitude: float
    price: Optional[str] = None
    district: str = ""
    url: str = ""
    category: str = ""
    image: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "token": self.token,
            "title": self.title,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "price": self.price,
            "district": self.district,
            "url": self.url,
            "category": self.category,
            "image": self.image,
        }
    
    @classmethod
    def from_map_response(cls, data: Dict[str, Any]) -> "MapAd":
        """Create MapAd from map API response."""
        location = data.get("location", {})
        share = data.get("share", {})
        seo = data.get("seo", {})
        web_info = seo.get("web_info", {})
        
        # Get first image if available
        image = None
        images = data.get("images", [])
        if images and len(images) > 0:
            image = images[0].get("src") if isinstance(images[0], dict) else images[0]
        
        return cls(
            token=data.get("token", ""),
            title=data.get("title", ""),
            latitude=location.get("latitude", 0),
            longitude=location.get("longitude", 0),
            price=data.get("price", ""),
            district=web_info.get("district_persian", ""),
            url=share.get("web_url", ""),
            category=data.get("category", ""),
            image=image,
        )


@dataclass
class City:
    """Represents a city with its ID and districts."""
    id: str
    name: str
    slug: str
    districts: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "districts": self.districts,
        }
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "City":
        """Create City from JSON data."""
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name", data.get("slug", "")),
            slug=data.get("slug", ""),
            districts=data.get("districts", data.get("district_options", [])),
        )


@dataclass
class District:
    """Represents a district."""
    id: str
    name: str
    slug: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
        }
    
    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "District":
        """Create District from JSON data."""
        return cls(
            id=str(data.get("id", data.get("value", ""))),
            name=data.get("title", data.get("name", data.get("slug", ""))),
            slug=data.get("slug", data.get("value", "")),
        )


@dataclass
class ScraperConfig:
    """
    Configuration for the Divar scraper.
    """
    max_pages: int = 10
    delay_between_requests: float = 2.0
    max_retries: int = 3
    timeout: int = 30
    user_agent: Optional[str] = None
    proxies: List[str] = field(default_factory=list)
    city_id: str = "1"
    category: str = "residential-rent"
    keywords_to_ignore: List[str] = field(default_factory=list)
    keywords_to_filter: List[str] = field(default_factory=list)
    
    # Map scraping settings
    map_enabled: bool = False
    map_bbox: Optional[Dict[str, float]] = None  # Bounding box for map view
    map_zoom: float = 9.0
    
    # City/district files
    cities_file: Optional[str] = None  # Path to cities JSON file
    districts_file: Optional[str] = None  # Path to districts JSON file
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_pages": self.max_pages,
            "delay_between_requests": self.delay_between_requests,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "user_agent": self.user_agent,
            "proxies": self.proxies,
            "city_id": self.city_id,
            "category": self.category,
            "keywords_to_ignore": self.keywords_to_ignore,
            "keywords_to_filter": self.keywords_to_filter,
            "map_enabled": self.map_enabled,
            "map_bbox": self.map_bbox,
            "map_zoom": self.map_zoom,
            "cities_file": self.cities_file,
            "districts_file": self.districts_file,
        }
    
    @classmethod
    def for_category(cls, category: str, city_id: str = "1") -> "ScraperConfig":
        """Create config for a specific category."""
        return cls(
            category=category,
            city_id=city_id,
        )
    
    @classmethod
    def for_map_view(
        cls,
        category: str,
        bbox: Dict[str, float],
        city_id: str = "1",
        zoom: float = 9.0,
    ) -> "ScraperConfig":
        """Create config for map view scraping."""
        return cls(
            category=category,
            city_id=city_id,
            map_enabled=True,
            map_bbox=bbox,
            map_zoom=zoom,
        )


# City IDs for major Iranian cities
CITY_IDS = {
    "tehran": "1",
    "mashhad": "2",
    "ishafahan": "3",
    "tabriz": "4",
    "shiraz": "5",
    "kermanshah": "6",
    "avesina": "7",
    "yazd": "8",
    "kerman": "9",
    "ahlvaz": "10",
    "rahnm": "11",
    "qom": "12",
    "orkyz": "13",
    "kermanshah": "14",
    "amarin": "15",
    "sari": "16",
    "zanjan": "17",
    "khorramabad": "18",
    "bojnord": "19",
    "birjand": "20",
}
