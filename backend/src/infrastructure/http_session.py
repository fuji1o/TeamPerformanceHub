import aiohttp
from typing import Optional

_session: Optional[aiohttp.ClientSession] = None


async def init_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False, limit=50, limit_per_host=20),
        )
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


def get_session() -> aiohttp.ClientSession:
    if _session is None or _session.closed:
        raise RuntimeError("HTTP session is not initialized. Call init_session() first.")
    return _session
