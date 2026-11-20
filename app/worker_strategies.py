"""Strategy implementations for token acquisition.
These are thin wrappers around the core functions in worker_fox.py
to maintain a stable interface for external callers.
"""
from app.worker_fox import (
    _try_s2_autocomplete as _core_s2,
    _try_s3_organic as _core_s3,
    _try_s1_direct as _core_s1,
    FoxWorker,
)


def _try_s2_autocomplete(dwid, url, hash_id=None):
    """Wrapper for S2 autocomplete strategy."""
    return _core_s2(dwid, url)


def _try_s3_search_click(dwid, url, hash_id=None):
    """Wrapper for S3 organic search strategy (alias for compatibility)."""
    return _core_s3(dwid, url)


def _try_s1_direct_speak(dwid, url, hash_id=None):
    """Wrapper for S1 direct URL entry strategy."""
    return _core_s1(dwid, url)


__all__ = [
    "_try_s2_autocomplete",
    "_try_s3_search_click", 
    "_try_s1_direct_speak",
    "FoxWorker",
]