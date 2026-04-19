import logging
import sys
import time
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Optional


log = logging.getLogger("teamhub")


def setup_logging(level: int = logging.INFO) -> None:
    """Настраивает форматирование. Вызывать один раз при старте приложения."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="[%(asctime)s.%(msecs)03d] %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("teamhub")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


_depth = threading.local()


def _get_depth() -> int:
    return getattr(_depth, "value", 0)


def _set_depth(v: int) -> None:
    _depth.value = v


def _prefix(symbol: str = " ") -> str:
    return "  " * _get_depth() + symbol


@asynccontextmanager
async def progress(label: str, log_threshold_ms: int = 0):
    log.info(f"{_prefix('▶')} {label}")
    _set_depth(_get_depth() + 1)
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _set_depth(_get_depth() - 1)
        log.error(f"{_prefix('✗')} {label} FAILED ({elapsed_ms} ms): {type(e).__name__}: {e}")
        raise
    else:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _set_depth(_get_depth() - 1)
        if elapsed_ms >= log_threshold_ms:
            log.info(f"{_prefix('✓')} {label} ({elapsed_ms} ms)")


@contextmanager
def progress_sync(label: str):
    log.info(f"{_prefix('▶')} {label}")
    _set_depth(_get_depth() + 1)
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _set_depth(_get_depth() - 1)
        log.error(f"{_prefix('✗')} {label} FAILED ({elapsed_ms} ms): {type(e).__name__}: {e}")
        raise
    else:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        _set_depth(_get_depth() - 1)
        log.info(f"{_prefix('✓')} {label} ({elapsed_ms} ms)")


def info(msg: str) -> None:
    log.info(f"{_prefix('·')} {msg}")


def warn(msg: str) -> None:
    log.warning(f"{_prefix('⚠')} {msg}")


def error(msg: str) -> None:
    log.error(f"{_prefix('✗')} {msg}")