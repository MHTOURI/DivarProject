from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RequestResult:

    success: bool

    status: int

    data: Optional[Dict[str, Any]] = None

    error: Optional[str] = None


@dataclass
class Proxy:

    url: str

    alive: bool = True

    failures: int = 0

    success: int = 0
