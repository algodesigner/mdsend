"""
Mastodon platform handler — post text and images to Mastodon.
"""

import os
from pathlib import Path


def post_to_mastodon(texts: list[str], media: list[Path]) -> dict:
    from mastodon import Mastodon

    client = Mastodon(
        access_token=os.environ["MASTODON_ACCESS_TOKEN"],
        api_base_url=os.environ["MASTODON_INSTANCE"],
    )

    media_ids = []
    for fp in media:
        if fp.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif"):
            print(f"  [Mastodon] Skipping {fp.name} \u2014 only JPEG/PNG/GIF supported")
            continue
        print(f"  [Mastodon] Uploading media: {fp.name}")
        resp = client.media_post(media_file=str(fp))
        media_ids.append(resp["id"])

    kwargs = {"status": texts[0]}
    if media_ids:
        kwargs["media_ids"] = media_ids

    resp = client.status_post(**kwargs)
    post_id = resp["id"]
    print(f"  [Mastodon] Posted \u2014 post ID: {post_id}")
    return {"status": "ok", "platform": "mastodon", "post_id": post_id}
