"""
Bluesky platform handler — post text, threaded posts, and images to Bluesky.
"""

import io
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


B_THREAD_PREFIX = "\U0001f9f5 "


def _make_thread_prefix(index: int, total: int) -> str:
    return f"{B_THREAD_PREFIX}({index}/{total}) "


def _extract_hashtag_facets(text: str) -> list:
    from atproto import models

    facets = []
    for m in re.finditer(r"(#\w+)", text):
        tag = m.group(1)[1:]
        byte_start = len(text[: m.start()].encode("utf-8"))
        byte_end = byte_start + len(m.group(1).encode("utf-8"))
        facets.append(
            models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byteStart=byte_start,
                    byteEnd=byte_end,
                ),
                features=[
                    models.AppBskyRichtextFacet.Tag(
                        tag=tag,
                    )
                ],
            )
        )
    return facets


def _extract_url_facets(text: str) -> list:
    from atproto import models

    facets = []
    for m in re.finditer(r"https?://\S+", text):
        url = m.group(0).rstrip(".,;:!?)\"']")
        if not url:
            continue
        byte_start = len(text[: m.start()].encode("utf-8"))
        byte_end = byte_start + len(m.group(0).encode("utf-8"))
        facets.append(
            models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byteStart=byte_start,
                    byteEnd=byte_end,
                ),
                features=[
                    models.AppBskyRichtextFacet.Link(uri=url),
                ],
            )
        )
    return facets


def _fetch_og_metadata(url: str) -> Optional[dict]:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; mdsend/0.3; "
                    "+https://github.com/vshurupov/mdsend)"
                ),
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    title = None
    m = re.search(
        r'<meta\s+[^>]*property="og:title"[^>]*content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    if m:
        title = m.group(1)
    else:
        m = re.search(
            r'<meta\s+[^>]*name="twitter:title"[^>]*content="([^"]*)"',
            html,
            re.IGNORECASE,
        )
        if m:
            title = m.group(1)
        else:
            m = re.search(r"<title>([^<]*)</title>", html, re.IGNORECASE)
            if m:
                title = m.group(1).strip()

    if not title:
        return None

    desc = None
    m = re.search(
        r'<meta\s+[^>]*property="og:description"[^>]*content="([^"]*)"',
        html,
        re.IGNORECASE,
    )
    if m:
        desc = m.group(1)
    else:
        m = re.search(
            r'<meta\s+[^>]*name="description"[^>]*content="([^"]*)"',
            html,
            re.IGNORECASE,
        )
        if m:
            desc = m.group(1)

    return {"title": title, "description": desc or ""}


def post_to_bluesky(texts: list[str], media: list[Path]) -> dict:
    from atproto import Client, models
    from PIL import Image as PilImage

    client = Client()
    client.login(
        os.environ["MSEND_BLUESKY_HANDLE"],
        os.environ["MSEND_BLUESKY_APP_PASSWORD"],
    )

    image_data = []
    for fp in media:
        if fp.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            print(f"  [Bluesky] Skipping {fp.name} \u2014 only JPEG/PNG supported")
            continue
        print(f"  [Bluesky] Uploading image: {fp.name}")

        MAX_BYTES = 1_900_000

        with PilImage.open(fp) as img:
            w, h = img.size

        file_size = fp.stat().st_size
        if file_size > MAX_BYTES:
            target_w, target_h = w, h
            print(
                f"         Compressing from {file_size:,} bytes "
                f"({w}x{h}) to fit {MAX_BYTES:,} byte limit"
            )
            with PilImage.open(fp) as img:
                while True:
                    ratio = (MAX_BYTES / file_size) ** 0.5
                    target_w = int(target_w * ratio)
                    target_h = int(target_h * ratio)
                    resized = img.resize((target_w, target_h), PilImage.LANCZOS)
                    buf = io.BytesIO()
                    resized.save(buf, format="PNG", optimize=True)
                    compressed_size = buf.tell()
                    if compressed_size <= MAX_BYTES or (target_w < 100 and target_h < 100):
                        break
                    file_size = compressed_size
                buf.seek(0)
                blob = client.com.atproto.repo.upload_blob(buf.read())
                print(f"         Compressed to {compressed_size:,} bytes ({target_w}x{target_h})")
            w, h = target_w, target_h
        else:
            with open(fp, "rb") as f:
                blob = client.com.atproto.repo.upload_blob(f.read())

        image_data.append(
            models.AppBskyEmbedImages.Image(
                alt=f"Image from post: {fp.stem}",
                image=blob.blob,
                aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(
                    width=w,
                    height=h,
                ),
            )
        )

    embed = None
    if image_data:
        embed = models.AppBskyEmbedImages.Main(images=image_data)

    now = datetime.utcnow().isoformat() + "Z"

    root_uri: Optional[str] = None
    root_cid: Optional[str] = None
    parent_uri: Optional[str] = None
    parent_cid: Optional[str] = None
    uris: list[str] = []

    total = len(texts)

    # --- URL link preview (best-effort, first chunk only) ---
    first_url = None
    external_embed = None
    if not image_data and texts:
        m = re.search(r"https?://\S+", texts[0])
        if m:
            first_url = m.group(0).rstrip(".,;:!?)\"']")

    if first_url:
        print(f"  [Bluesky] Fetching link preview for: {first_url}")
        og = _fetch_og_metadata(first_url)
        if og:
            external_embed = models.AppBskyEmbedExternal.Main(
                external=models.AppBskyEmbedExternal.External(
                    uri=first_url,
                    title=og["title"],
                    description=og["description"],
                )
            )
            print(f"  [Bluesky] Link card: {og['title']}")

    for i, chunk in enumerate(texts):
        prefix = _make_thread_prefix(i + 1, total) if total > 1 else ""
        post_text = prefix + chunk

        url_facets = _extract_url_facets(post_text)
        all_facets = (_extract_hashtag_facets(post_text) or []) + (url_facets or [])

        current_embed = embed if i == 0 else None
        if i == 0 and current_embed is None and external_embed:
            current_embed = external_embed

        reply_ref = None
        if root_uri is not None and parent_uri is not None:
            reply_ref = models.AppBskyFeedPost.ReplyRef(
                parent=models.ComAtprotoRepoStrongRef.Main(
                    uri=parent_uri,
                    cid=parent_cid,
                ),
                root=models.ComAtprotoRepoStrongRef.Main(
                    uri=root_uri,
                    cid=root_cid,
                ),
            )

        record = models.AppBskyFeedPost.Record(
            text=post_text,
            createdAt=now,
            embed=current_embed,
            reply=reply_ref,
            facets=all_facets or None,
        )

        try:
            resp = client.com.atproto.repo.create_record(
                models.ComAtprotoRepoCreateRecord.Data(
                    repo=client.me.did,
                    collection="app.bsky.feed.post",
                    record=record,
                )
            )
        except Exception:
            print(
                f"  \u2717 [Bluesky] Failed at chunk {i+1}/{total}. "
                f"First {i} chunk(s) were posted. "
                f"Delete them manually from the Bluesky UI if needed."
            )
            raise

        uri = resp.uri
        cid = resp.cid
        uris.append(uri)

        if root_uri is None:
            root_uri = uri
            root_cid = cid
        parent_uri = uri
        parent_cid = cid

        print(f"  [Bluesky] Posted chunk {i+1}/{total} \u2014 AT URI: {uri}")

    return {"status": "ok", "platform": "bluesky", "uris": uris}
