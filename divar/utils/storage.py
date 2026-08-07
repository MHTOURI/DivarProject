"""
Storage backends for Divar scraper.

Provides different storage options for scraped ads:
- MemoryStorage: In-memory storage (fast, but data lost on restart)
- SQLiteStorage: SQLite database (persistent, queryable)
- JSONStorage: JSON file storage (simple, human-readable)

Example:
    from divar.utils import SQLiteStorage
    
    storage = SQLiteStorage("ads.db")
    await storage.save(ad)
    ads = await storage.get_all()
"""

import asyncio
import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pathlib import Path

from divar.models import Ad


class BaseStorage(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    async def save(self, ad: Ad) -> bool:
        """Save an ad. Returns True if new, False if duplicate."""
        pass
    
    @abstractmethod
    async def get(self, token: str) -> Optional[Ad]:
        """Get an ad by token."""
        pass
    
    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Ad]:
        """Get all ads with pagination."""
        pass
    
    @abstractmethod
    async def get_by_district(self, district: str, limit: int = 100) -> List[Ad]:
        """Get ads by district."""
        pass
    
    @abstractmethod
    async def search(self, query: str, limit: int = 100) -> List[Ad]:
        """Search ads by title or description."""
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
    """
    In-memory storage for ads.
    
    Fast but data is lost when the program ends.
    Useful for testing or temporary processing.
    """
    
    def __init__(self):
        self._ads: Dict[str, Ad] = {}
        self._lock = asyncio.Lock()
    
    async def save(self, ad: Ad) -> bool:
        async with self._lock:
            if ad.token in self._ads:
                return False
            self._ads[ad.token] = ad
            return True
    
    async def get(self, token: str) -> Optional[Ad]:
        async with self._lock:
            return self._ads.get(token)
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Ad]:
        async with self._lock:
            ads = list(self._ads.values())
            return ads[offset:offset + limit]
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Ad]:
        async with self._lock:
            ads = [ad for ad in self._ads.values() if ad.district == district]
            return ads[:limit]
    
    async def search(self, query: str, limit: int = 100) -> List[Ad]:
        async with self._lock:
            query = query.lower()
            ads = [
                ad for ad in self._ads.values()
                if query in ad.title.lower() or query in ad.description.lower()
            ]
            return ads[:limit]
    
    async def count(self) -> int:
        async with self._lock:
            return len(self._ads)
    
    async def clear(self) -> int:
        async with self._lock:
            count = len(self._ads)
            self._ads.clear()
            return count


class SQLiteStorage(BaseStorage):
    """
    SQLite storage for ads.
    
    Persistent storage that allows querying.
    Creates a SQLite database file.
    
    Example:
        storage = SQLiteStorage("ads.db")
        await storage.save(ad)
        ads = await storage.get_all()
    """
    
    def __init__(self, db_path: str = "divar_ads.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._memory_db = db_path == ":memory:"
        self._connection = None
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        if self._memory_db:
            # For in-memory databases, keep a persistent connection
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
                created_at TIMESTAMP,
                extra TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_district ON ads(district)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_title ON ads(title)
        """)
        
        if self._memory_db:
            self._connection.commit()
        else:
            conn.commit()
            conn.close()
    
    async def save(self, ad: Ad) -> bool:
        async with self._lock:
            try:
                if self._memory_db:
                    conn = self._connection
                else:
                    conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Check if exists
                cursor.execute("SELECT 1 FROM ads WHERE token = ?", (ad.token,))
                if cursor.fetchone():
                    if not self._memory_db:
                        conn.close()
                    return False
                
                images_json = json.dumps(ad.images) if ad.images else "[]"
                extra_json = json.dumps(ad.extra) if ad.extra else "{}"
                
                cursor.execute("""
                    INSERT INTO ads (token, title, description, url, district, price, category, images, phone, special, created_at, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ad.token,
                    ad.title,
                    ad.description,
                    ad.url,
                    ad.district,
                    ad.price,
                    ad.category,
                    images_json,
                    ad.phone,
                    1 if ad.special else 0,
                    ad.created_at.isoformat() if ad.created_at else None,
                    extra_json,
                ))
                
                conn.commit()
                if not self._memory_db:
                    conn.close()
                return True
                
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return False
    
    def _get_connection(self):
        """Get a database connection, using persistent connection for in-memory DBs."""
        if self._memory_db:
            return self._connection
        return sqlite3.connect(self.db_path)
    
    async def get(self, token: str) -> Optional[Ad]:
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
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Ad]:
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
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Ad]:
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
    
    async def search(self, query: str, limit: int = 100) -> List[Ad]:
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
    
    def _row_to_ad(self, row: sqlite3.Row) -> Ad:
        """Convert database row to Ad object."""
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
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )


class JSONStorage(BaseStorage):
    """
    JSON file storage for ads.
    
    Simple storage that saves ads to a JSON file.
    Good for small datasets or debugging.
    """
    
    def __init__(self, file_path: str = "ads.json"):
        self.file_path = Path(file_path)
        self._lock = asyncio.Lock()
        self._ensure_file()
    
    def _ensure_file(self):
        """Ensure the JSON file exists."""
        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")
    
    async def save(self, ad: Ad) -> bool:
        async with self._lock:
            try:
                ads = self._load_ads()
                
                if any(a["token"] == ad.token for a in ads):
                    return False
                
                ads.append(ad.to_dict())
                self._save_ads(ads)
                return True
                
            except Exception as e:
                print(f"Error saving to JSON: {e}")
                return False
    
    async def get(self, token: str) -> Optional[Ad]:
        async with self._lock:
            try:
                ads = self._load_ads()
                for ad_data in ads:
                    if ad_data["token"] == token:
                        return Ad(**ad_data)
                return None
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[Ad]:
        async with self._lock:
            try:
                ads = self._load_ads()
                return [Ad(**ad) for ad in ads[offset:offset + limit]]
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def get_by_district(self, district: str, limit: int = 100) -> List[Ad]:
        async with self._lock:
            try:
                ads = self._load_ads()
                filtered = [Ad(**ad) for ad in ads if ad.get("district") == district]
                return filtered[:limit]
                
            except Exception as e:
                print(f"Error loading from JSON: {e}")
                return []
    
    async def search(self, query: str, limit: int = 100) -> List[Ad]:
        async with self._lock:
            try:
                ads = self._load_ads()
                query = query.lower()
                filtered = [
                    Ad(**ad) for ad in ads
                    if query in ad.get("title", "").lower() 
                    or query in ad.get("description", "").lower()
                ]
                return filtered[:limit]
                
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
