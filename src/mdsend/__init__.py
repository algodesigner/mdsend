"""
mdsend — file-based social media publisher.

Publishes markdown posts to LinkedIn, Bluesky, and Mastodon.
"""

from mdsend.core import (
    Post,
    discover_posts,
    truncate,
    parse_front_matter,
    _extract_url,
    ALL_PLATFORMS,
    THREAD_PREFIX_OVERHEAD,
)
from mdsend.cli import main, parse_args

__all__ = [
    "Post",
    "discover_posts",
    "truncate",
    "parse_front_matter",
    "ALL_PLATFORMS",
    "THREAD_PREFIX_OVERHEAD",
    "_extract_url",
    "main",
    "parse_args",
]
