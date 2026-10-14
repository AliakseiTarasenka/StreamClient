import httpx
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from functools import wraps

from src.infrastructure.api.config import APIConfig


class CacheManager:
    """Simple in-memory cache with TTL"""

    def __init__(self, ttl_seconds: int = 5):
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value: str) -> None:
        self.cache[key] = (value, datetime.now())

    def invalidate(self, pattern: Optional[str] = None) -> None:
        if pattern:
            keys = [k for k in self.cache if pattern in k]
            for k in keys:
                del self.cache[k]
        else:
            self.cache.clear()

    def size(self) -> int:
        return len(self.cache)


class APIClient:
    """Base API client with HTTP connection pooling and config support"""

    def __init__(
        self,
        base_url: str | httpx.URL,
        headers: Dict[str, Any] | None = None,
        timeout: int = 30,
        max_connections: int = 100,
    ):
        # Load config if not provided
        config = APIConfig()

        self.base_url = base_url or config.api_default_url
        self.headers = headers or config.default_headers

        # init NON-BLOCKING async HTTP client
        self._client = httpx.AsyncClient(
            verify=False,
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=20),
            timeout=httpx.Timeout(timeout),
        )

    async def post(self, data: dict) -> str:
        """Make POST request"""
        response = await self._client.post(self.base_url, data=data, headers=self.headers)
        response.raise_for_status()
        return response.text

    async def close(self):
        await self._client.aclose()

    # Async context manager interface implementation : async with APIClient(base_url="...") as client
    async def __aenter__(self):
        return self

    # automatically close Httpx connection
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class APIClientPool(APIClient):
    """API client with caching capabilities"""

    def __init__(
        self,
        base_url: str | httpx.URL,
        timeout: int = 30,
        max_connections: int = 100,
        cache_ttl: int = 5,
    ):
        super().__init__(base_url, timeout=timeout, max_connections=max_connections)
        self.cache = CacheManager(ttl_seconds=cache_ttl)

    def _make_cache_key(self, data: dict) -> str:
        return f"{self.base_url}:{json.dumps(data, sort_keys=True)}"

    async def post(self, data: dict, use_cache: bool = True) -> str:
        if not use_cache:
            return await super().post(data)

        cache_key = self._make_cache_key(data)
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        result = await super().post(data)
        self.cache.set(cache_key, result)
        return result

    def invalidate_cache(self, pattern: Optional[str] = None):
        self.cache.invalidate(pattern)

    def get_cache_stats(self) -> dict:
        return {"size": self.cache.size(), "ttl_seconds": self.cache.ttl.seconds}

    # automatically close Httpx connection and clear cache
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)
        self.invalidate_cache()


def retry_on_failure(max_attempts: int = 3, delay: int = 1):
    """Retry decorator for async API calls"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPError as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        import asyncio

                        await asyncio.sleep(delay * (attempt + 1))
            raise last_exception

        return wrapper

    return decorator


class ResilientAPIClient(APIClientPool):
    """API client with retry logic"""

    @retry_on_failure(max_attempts=3, delay=1)
    async def post(self, data: dict, use_cache: bool = True) -> str:
        return await super().post(data, use_cache)
