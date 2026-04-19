import asyncio
import hashlib
import json
import time
from functools import wraps
from typing import Any, Callable, Optional


class TTLCache:
    def __init__(self, default_ttl: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at != 0 and expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        expires_at = 0 if ttl == 0 else time.time() + ttl
        self._store[key] = (expires_at, value)

    def invalidate(self, prefix: Optional[str] = None) -> int:
        if prefix is None:
            count = len(self._store)
            self._store.clear()
            return count
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)

    def stats(self) -> dict:
        now = time.time()
        active = sum(1 for exp, _ in self._store.values() if exp == 0 or exp > now)
        return {"total": len(self._store), "active": active}


ttl_cache = TTLCache(default_ttl=300)

_inflight_locks: dict[str, asyncio.Lock] = {}


def _make_key(prefix: str, args: tuple, kwargs: dict) -> str:
    try:
        payload = json.dumps([args, kwargs], sort_keys=True, default=str)
    except TypeError:
        payload = repr((args, kwargs))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def cached(ttl: int = 300, key_prefix: Optional[str] = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            key_args = args[1:] if args and hasattr(args[0], "__class__") and not isinstance(args[0], (str, int, float, bool, list, dict, tuple)) else args
            key = _make_key(prefix, key_args, kwargs)

            cached_value = ttl_cache.get(key)
            if cached_value is not None:
                return cached_value

            lock = _inflight_locks.setdefault(key, asyncio.Lock())
            async with lock:
                cached_value = ttl_cache.get(key)
                if cached_value is not None:
                    return cached_value

                result = await func(*args, **kwargs)
                ttl_cache.set(key, result, ttl=ttl)
                return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key_args = args[1:] if args and hasattr(args[0], "__class__") and not isinstance(args[0], (str, int, float, bool, list, dict, tuple)) else args
            key = _make_key(prefix, key_args, kwargs)

            cached_value = ttl_cache.get(key)
            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)
            ttl_cache.set(key, result, ttl=ttl)
            return result

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
