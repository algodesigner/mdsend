"""
LinkedIn platform handler — post text, images, and link previews to LinkedIn.
"""

import os
import re
from pathlib import Path
from typing import Optional

import requests

LINKEDIN_API = "https://api.linkedin.com/v2"


def _linkedin_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _linkedin_register_upload(file_path: Path) -> tuple[str, str]:
    author = os.environ["LINKEDIN_PERSON_URN"]

    register_payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": author,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent",
                }
            ],
        }
    }
    resp = requests.post(
        f"{LINKEDIN_API}/assets?action=registerUpload",
        headers=_linkedin_headers(),
        json=register_payload,
    )
    resp.raise_for_status()
    data = resp.json()

    upload_url = data["value"]["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn = data["value"]["asset"]

    with open(file_path, "rb") as f:
        upload_resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
                "Content-Type": "application/octet-stream",
            },
            data=f,
        )
    upload_resp.raise_for_status()

    return upload_url, asset_urn


def _extract_url(text: str) -> Optional[str]:
    """Return the first http/https URL found in the text, or None."""
    m = re.search(r"https?://\S+", text)
    return m.group(0) if m else None


def post_to_linkedin(texts: list[str], media: list[Path]) -> dict:
    text = texts[0]
    author = os.environ["LINKEDIN_PERSON_URN"]

    media_assets = []
    for fp in media:
        print(f"  [LinkedIn] Uploading media: {fp.name}")
        _, asset_urn = _linkedin_register_upload(fp)
        media_assets.append(asset_urn)

    share_category = "NONE"
    share_content: dict = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": share_category,
    }

    url = _extract_url(text)
    if url and not media_assets:
        share_category = "ARTICLE"
        share_content["shareMediaCategory"] = share_category
        share_content["article"] = {"source": url}

    share_body = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content,
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    if media_assets:
        share_body["specificContent"][
            "com.linkedin.ugc.ShareContent"
        ]["shareMediaCategory"] = "IMAGE"
        share_body["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
            {
                "status": "READY",
                "description": {"text": text[:200]},
                "media": asset_urn,
                "title": {"text": text[:100]},
            }
            for asset_urn in media_assets
        ]

    resp = requests.post(
        f"{LINKEDIN_API}/ugcPosts",
        headers=_linkedin_headers(),
        json=share_body,
    )
    resp.raise_for_status()
    post_id = resp.headers.get("X-RestLi-Id", "unknown")
    print(f"  [LinkedIn] Posted \u2014 post ID: {post_id}")
    return {"status": "ok", "platform": "linkedin", "post_id": post_id}
