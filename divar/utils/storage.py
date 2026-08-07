"""
Storage backends for Divar scraper.

Provides different storage options for scraped ads:
- MemoryStorage: In-memory storage (fast, but data lost on restart)
- SQLiteStorage: SQLite database (persistent, queryable)
- JSONStorage: JSON file storage (simple, human-readable)
"""

import asyncio
import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from datetime import datetime

from divar.models import Ad, MapAd


class BaseStorage(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def save(self, ad: Union[Ad, MapAd]) -> bool:
        """Save an ad. Returns True if new, False if duplicate."""
        pass
    
    @abstractmethod
    async def get(self, token: str) -> Optional[Union[Ad, MapAd]]:
        """Get an ad by token."""
        pass
    
    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Union[Ad, MapAd]]:
        """Get all ads with pagination."""
        pass
    
    @abstractmethod
    async def get_by_district(self, district: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        """Get ads by district."""
        pass
    
    @abstractmethod
    async def search(self, query: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        """Search ads by title or description."""
        pass
    
    @abstractmethod
    async def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 100,
    ) -> List[MapAd]:
        """Get ads near a location (for map display)."""
        pass
    
    @abstractmethod
    async def count(self) -> int:
        """Get total ad count."""
        pass
    
    @abstractmethod
    async def clear(self) -> int:
        """Clear all ads. Returns number removed."""
        pass


class MemoryStorage(BaseStorage):
    """In-memory storage for ads."""
    
    def __init__(self):
        self._ads: Dict[str, Union[Ad, MapAd]] = {}
        self._lock = asyncio.Lock()
    
    async def save(self, ad: Union[Ad, MapAd]) -> bool:
        async with self._lock:
            if ad.token in self._ads:
                return False
            self._ads[ad.token] = ad
            return True
    
    async def get(self, token: str) -> Optional[Union[Ad, MapAd]]:
        async with self._lock:
            return self._ads.get(token)
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            ads = list(self._ads.values())
            return ads[offset:offset + limit]
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            ads = [
                ad for ad in self._ads.values()
                if hasattr(ad, 'district') and ad.district == district
            ]
            return ads[:limit]
    
    async def search(self, query: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            query = query.lower()
            ads = [
                ad for ad in self._ads.values()
                if hasattr(ad, 'title') and (
                    query in ad.title.lower() or
                    (hasattr(ad, 'description') and query in ad.description.lower())
                )
            ]
            return ads[:limit]
    
    async def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 100,
    ) -> List[MapAd]:
        """Get ads near a location (in-memory, returns empty for non-MapAd)."""
        async with self._lock:
            nearby = []
            for ad in self._ads.values():
                if isinstance(ad, MapAd) and ad.latitude and ad.longitude:
                    dist = self._haversine_distance(
                        latitude, longitude, ad.latitude, ad.longitude
                    )
                    if dist <= radius_km:
                        nearby.append(ad)
            
            nearby.sort(key=lambda x: self._haversine_distance(
                latitude, longitude, x.latitude, x.longitude
            ))
            return nearby[:limit]
    
    async def count(self) -> int:
        async with self._lock:
            return len(self._ads)
    
    async def clear(self) -> int:
        async with self._lock:
            count = len(self._ads)
            self._ads.clear()
            return count
    
    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km."""
        import math
        
        R = 6371  # Earth's radius in km
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat / 2) ** 2 + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c


class SQLiteStorage(BaseStorage):
    """SQLite storage for ads."""
    
    def __init__(self, db_path: str = "divar_ads.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._memory_db = db_path == ":memory:"
        self._connection = None
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        if self._memory_db:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = self._connection.cursor()
        else:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                token TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                url TEXT,
                district TEXT,
                price TEXT,
                category TEXT,
                images TEXT,
                phone TEXT,
                special INTEGER DEFAULT 0,
                latitude REAL,
                longitude REAL,
                created_at TIMESTAMP,
                extra TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ad_type TEXT DEFAULT 'regular'
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_district ON ads(district)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_category ON ads(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_latitude ON ads(latitude)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_longitude ON ads(longitude)")
        
        if self._memory_db:
            self._connection.commit()
        else:
            conn.commit()
            conn.close()
    
    def _get_connection(self):
        """Get a database connection."""
        if self._memory_db:
            return self._connection
        return sqlite3.connect(self.db_path)
    
    async def save(self, ad: Union[Ad, MapAd]) -> bool:
        async with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT 1 FROM ads WHERE token = ?", (ad.token,))
                if cursor.fetchone():
                    return False
                
                images_json = json.dumps(ad.images) if hasattr(ad, 'images') and ad.images else "[]"
                extra_json = json.dumps(ad.extra) if hasattr(ad, 'extra') and ad.extra else "{}"
                
                ad_type = "map" if isinstance(ad, MapAd) else "regular"
                
                cursor.execute("""
                    INSERT INTO ads (
                        token, title, description, url, district, price, category,
                        images, phone, special, latitude, longitude, created_at, extra, ad_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad.token,
                    ad.title,
                    getattr(ad, 'description', '') or '',
                    getattr(ad, 'url', '') or '',
                    getattr(ad, 'district', '') or '',
                    getattr(ad, 'price', '') or '',
                    getattr(ad, 'category', '') or '',
                    images_json,
                    getattr(ad, 'phone', '') or '',
                    1 if getattr(ad, 'special', False) else 0,
                    getattr(ad, 'latitude', None),
                    getattr(ad, 'longitude', None),
                    getattr(ad, 'created_at', None),
                    extra_json,
                    ad_type,
                ))
                
                conn.commit()
                return True
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return False
    
    async def get(self, token: str) -> Optional[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM ads WHERE token = ?", (token,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                return self._row_to_ad(row)
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT * FROM ads ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                )
                rows = cursor.fetchall()
                
                return [self._row_to_ad(row) for row in rows]
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return []
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT * FROM ads WHERE district = ? ORDER BY scraped_at DESC LIMIT ?",
                    (district, limit)
                )
                rows = cursor.fetchall()
                
                return [self._row_to_ad(row) for row in rows]
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return []
    
    async def search(self, query: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                search_pattern = f"%{query}%"
                cursor.execute(
                    """SELECT * FROM ads 
                       WHERE title LIKE ? OR description LIKE ?
                       ORDER BY scraped_at DESC LIMIT ?""",
                    (search_pattern, search_pattern, limit)
                )
                rows = cursor.fetchall()
                
                return [self._row_to_ad(row) for row in rows]
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return []
    
    async def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 100,
    ) -> List[MapAd]:
        """Get ads near a location using Haversine formula."""
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Use Haversine formula in SQL
                query = """
                    SELECT *, 
                           (6371 * acos(
                               cos(radians(?)) * cos(radians(latitude)) * 
                               cos(radians(longitude) - radians(?)) + 
                               sin(radians(?)) * sin(radians(latitude))
                           )) AS distance
                    FROM ads
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    HAVING distance <= ?
                    ORDER BY distance
                    LIMIT ?
                """
                
                cursor.execute(query, (latitude, longitude, latitude, radius_km, limit))
                rows = cursor.fetchall()
                
                return [self._row_to_map_ad(row) for row in rows]
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return []
    
    async def count(self) -> int:
        async with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM ads")
                count = cursor.fetchone()[0]
                
                return count
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return 0
    
    async def count_by_category(self, category: str) -> int:
        """Count ads by category."""
        async with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT COUNT(*) FROM ads WHERE category = ?",
                    (category,)
                )
                count = cursor.fetchone()[0]
                
                return count
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return 0
    
    async def get_by_category(self, category: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        """Get ads by category."""
        async with self._lock:
            try:
                conn = self._get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT * FROM ads WHERE category = ? ORDER BY scraped_at DESC LIMIT ?",
                    (category, limit)
                )
                rows = cursor.fetchall()
                
                return [self._row_to_ad(row) for row in rows]
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return []
    
    async def clear(self) -> int:
        async with self._lock:
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM ads")
                count = cursor.fetchone()[0]
                
                cursor.execute("DELETE FROM ads")
                conn.commit()
                
                return count
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return 0
    
    def _row_to_ad(self, row: sqlite3.Row) -> Union[Ad, MapAd]:
        """Convert database row to Ad or MapAd object."""
        ad_type = row.get("ad_type", "regular")
        
        if ad_type == "map":
            return MapAd(
                token=row["token"],
                title=row["title"],
                latitude=row["latitude"] or 0,
                longitude=row["longitude"] or 0,
                price=row["price"],
                district=row["district"] or "",
                url=row["url"] or "",
                category=row["category"] or "",
                image=None,
            )
        
        return Ad(
            token=row["token"],
            title=row["title"],
            description=row["description"] or "",
            url=row["url"] or "",
            district=row["district"] or "",
            price=row["price"],
            category=row["category"] or "",
            images=json.loads(row["images"]) if row["images"] else [],
            phone=row["phone"],
            special=bool(row["special"]),
            created_at=row["created_at"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )
    
    def _row_to_map_ad(self, row: sqlite3.Row) -> MapAd:
        """Convert database row to MapAd object."""
        return MapAd(
            token=row["token"],
            title=row["title"],
            latitude=row["latitude"] or 0,
            longitude=row["longitude"] or 0,
            price=row["price"],
            district=row["district"] or "",
            url=row["url"] or "",
            category=row["category"] or "",
            image=None,
        )


class JSONStorage(BaseStorage):
    """JSON file storage for ads."""
    
    def __init__(self, file_path: str = "ads.json"):
        self.file_path = Path(file_path)
        self._lock = asyncio.Lock()
        self._ensure_file()
    
    def _ensure_file(self):
        """Ensure the JSON file exists."""
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")
    
    async def save(self, ad: Union[Ad, MapAd]) -> bool:
        async with self._lock:
            try:
                ads = self._load_ads()
                
                if any(a["token"] == ad.token for a in ads):
                    return False
                
                ad_dict = ad.to_dict()
                ad_dict["ad_type"] = "map" if isinstance(ad, MapAd) else "regular"
                ads.append(ad_dict)
                self._save_ads(ads)
                return True
                
            except Exception as e:
                print(f"Error saving to JSON: {e}")
                return False
    
    async def get(self, token: str) -> Optional[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                ads = self._load_ads()
                for ad_data in ads:
                    if ad_data["token"] == token:
                        ad_type = ad_data.get("ad_type", "regular")
                        if ad_type == "map":
                            return MapAd(**{k: v for k, v in ad_data.items() if k != "ad_type"})
                        return Ad(**{k: v for k, v in ad_data.items() if k != "ad_type"})
                return None
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                ads = self._load_ads()
                result = []
                for ad_data in ads[offset:offset + limit]:
                    ad_type = ad_data.get("ad_type", "regular")
                    if ad_type == "map":
                        result.append(MapAd(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                    else:
                        result.append(Ad(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                return result
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                ads = self._load_ads()
                filtered = []
                for ad_data in ads:
                    if ad_data.get("district") == district:
                        ad_type = ad_data.get("ad_type", "regular")
                        if ad_type == "map":
                            filtered.append(MapAd(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                        else:
                            filtered.append(Ad(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                return filtered[:limit]
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def search(self, query: str, limit: int = 100) -> List[Union[Ad, MapAd]]:
        async with self._lock:
            try:
                ads = self._load_ads()
                query = query.lower()
                filtered = []
                for ad_data in ads:
                    if query in ad_data.get("title", "").lower() or \
                       query in ad_data.get("description", "").lower():
                        ad_type = ad_data.get("ad_type", "regular")
                        if ad_type == "map":
                            filtered.append(MapAd(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                        else:
                            filtered.append(Ad(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                return filtered[:limit]
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 100,
    ) -> List[MapAd]:
        """Get ads near a location (JSON storage, less efficient)."""
        async with self._lock:
            try:
                ads = self._load_ads()
                nearby = []
                
                for ad_data in ads:
                    if ad_data.get("latitude") and ad_data.get("longitude"):
                        dist = MemoryStorage._haversine_distance(
                            latitude, longitude,
                            ad_data["latitude"], ad_data["longitude"]
                        )
                        if dist <= radius_km:
                            nearby.append(MapAd(**{k: v for k, v in ad_data.items() if k != "ad_type"}))
                
                nearby.sort(key=lambda x: MemoryStorage._haversine_distance(
                    latitude, longitude, x.latitude, x.longitude
                ))
                return nearby[:limit]
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def count(self) -> int:
        async with self._lock:
            try:
                ads = self._load_ads()
                return len(ads)
                
            except Exception as e:
                print(f"Error counting JSON: {e}")
                return 0
    
    async def clear(self) -> int:
        async with self._lock:
            try:
                count = await self.count()
                self.file_path.write_text("[]", encoding="utf-8")
                return count
                
            except Exception as e:
                print(f"Error clearing JSON: {e}")
                return 0
    
    def _load_ads(self) -> List[Dict]:
        """Load ads from JSON file."""
        try:
            content = self.file_path.read_text(encoding="utf-8")
            return json.loads(content)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _save_ads(self, ads: List[Dict]):
        """Save ads to JSON file."""
        self.file_path.write_text(
            json.dumps(ads, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
