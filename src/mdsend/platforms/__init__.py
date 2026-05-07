"""
mdsend platform handlers — LinkedIn, Bluesky, Mastodon.
"""

from mdsend.platforms.linkedin import post_to_linkedin
from mdsend.platforms.bluesky import post_to_bluesky
from mdsend.platforms.mastodon import post_to_mastodon

PLATFORM_HANDLERS = {
    "linkedin": post_to_linkedin,
    "bluesky": post_to_bluesky,
    "mastodon": post_to_mastodon,
}

__all__ = ["PLATFORM_HANDLERS"]
