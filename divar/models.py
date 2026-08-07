"""
Data models for Divar scraper.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class Ad:
    """
    Represents a Divar advertisement/listing.
    
    Attributes:
        token: Unique identifier for the ad
        title: Ad title
        description: Ad description text
        url: Web URL to the ad
        district: District/area name
        price: Price if available
        category: Ad category
        images: List of image URLs
        phone: Contact phone number if available
        created_at: When the ad was created
        extra: Additional data from the API
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
            "extra": self.extra,
        }
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Ad":
        """Create Ad from Divar API response."""
        seo = data.get("seo", {})
        web_info = seo.get("web_info", {})
        
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
            special="special" in data.get("title", "").lower(),
            extra=data,
        )


@dataclass
class ScraperConfig:
    """
    Configuration for the Divar scraper.
    
    Attributes:
        max_pages: Maximum number of pages to scrape
        delay_between_requests: Delay between requests in seconds
        max_retries: Maximum retry attempts on failure
        timeout: Request timeout in seconds
        user_agent: Custom user agent (or None for random)
        proxies: List of proxy URLs
        filters: Custom search filters
        city_id: City ID to scrape (default: Tehran = "1")
        category: Category to filter by
        keywords_to_ignore: Keywords that cause ads to be skipped
        keywords_to_filter: Keywords for filtering ads (e.g., agency ads)
    """
    max_pages: int = 10
    delay_between_requests: float = 2.0
    max_retries: int = 3
    timeout: int = 30
    user_agent: Optional[str] = None
    proxies: List[str] = field(default_factory=list)
    filters: Optional[Dict[str, Any]] = None
    city_id: str = "1"
    category: str = ""
    keywords_to_ignore: List[str] = field(default_factory=list)
    keywords_to_filter: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_pages": self.max_pages,
            "delay_between_requests": self.delay_between_requests,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "user_agent": self.user_agent,
            "proxies": self.proxies,
            "filters": self.filters,
            "city_id": self.city_id,
            "category": self.category,
            "keywords_to_ignore": self.keywords_to_ignore,
            "keywords_to_filter": self.keywords_to_filter,
        }
