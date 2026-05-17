"""
Mastodon platform handler — post text and images to Mastodon.
"""

import os
from pathlib import Path
from typing import Optional

M_THREAD_PREFIX = "\U0001f9f5 "


def _make_thread_prefix(index: int, total: int) -> str:
    return f"{M_THREAD_PREFIX}({index}/{total}) "


def post_to_mastodon(texts: list[str], media: list[Path]) -> dict:
    from mastodon import Mastodon

    client = Mastodon(
        access_token=os.environ["MSEND_MASTODON_ACCESS_TOKEN"],
        api_base_url=os.environ["MSEND_MASTODON_INSTANCE"],
    )

    media_ids = []
    for fp in media:
        if fp.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif"):
            print(f"  [Mastodon] Skipping {fp.name} \u2014 only JPEG/PNG/GIF supported")
            continue
        print(f"  [Mastodon] Uploading media: {fp.name}")
        resp = client.media_post(media_file=str(fp))
        media_ids.append(resp["id"])

    total = len(texts)
    in_reply_to_id: Optional[int] = None
    ids: list[int] = []

    for i, chunk in enumerate(texts):
        prefix = _make_thread_prefix(i + 1, total) if total > 1 else ""
        text = prefix + chunk

        kwargs = {"status": text}
        if i == 0 and media_ids:
            kwargs["media_ids"] = media_ids
        if in_reply_to_id is not None:
            kwargs["in_reply_to_id"] = in_reply_to_id

        try:
            resp = client.status_post(**kwargs)
        except Exception:
            print(
                f"  \u2717 [Mastodon] Failed at chunk {i+1}/{total}. "
                f"First {i} chunk(s) were posted. "
                f"Delete them manually from the Mastodon UI if needed."
            )
            raise

        post_id = resp["id"]
        ids.append(post_id)
        in_reply_to_id = post_id
        print(f"  [Mastodon] Posted chunk {i+1}/{total} \u2014 post ID: {post_id}")

    return {"status": "ok", "platform": "mastodon", "post_id": ids[0] if ids else None}