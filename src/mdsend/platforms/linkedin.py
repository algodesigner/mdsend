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
        "Authorization": f"Bearer {os.environ['MSEND_LINKEDIN_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _linkedin_register_upload(file_path: Path) -> tuple[str, str]:
    author = os.environ["MSEND_LINKEDIN_PERSON_URN"]

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
                "Authorization": f"Bearer {os.environ['MSEND_LINKEDIN_ACCESS_TOKEN']}",
                "Content-Type": "application/octet-stream",
            },
            data=f,
        )
    upload_resp.raise_for_status()

    return upload_url, asset_urn


def _extract_url(text: str) -> Optional[str]:
    """Return the first http/https URL found in the text, or None."""
    m = re.search(r"https?://[^\s]+", text)
    if not m:
        return None
    url = m.group(0).rstrip(".,;:!?)\"']")
    return url if url else None


def _check_response(resp: requests.Response):
    """Raise a detailed error if the LinkedIn API returned a non-2xx status."""
    if resp.status_code >= 400:
        body = resp.text
        msg = f"{resp.status_code} {resp.reason} for {resp.url}"
        if body:
            msg += f"\nResponse body: {body}"
        raise requests.HTTPError(msg, response=resp)


def post_to_linkedin(texts: list[str], media: list[Path]) -> dict:
    text = texts[0]
    author = os.environ["MSEND_LINKEDIN_PERSON_URN"]


    media_assets = []
    for fp in media:
        print(f"  [LinkedIn] Uploading media: {fp.name}")
        _, asset_urn = _linkedin_register_upload(fp)
        media_assets.append(asset_urn)

    share_content: dict = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }

    url = _extract_url(text)
    if url and not media_assets:
        clean_text = re.sub(r"https?://\S+", "", text)
        clean_text = re.sub(r"[ \t]+", " ", clean_text)
        lines = [line.strip() for line in clean_text.split("\n")]
        clean_text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        share_content["shareCommentary"]["text"] = clean_text or text
        share_content["shareMediaCategory"] = "ARTICLE"
        share_content["media"] = [
            {
                "status": "READY",
                "originalUrl": url,
            }
        ]

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
    _check_response(resp)
    post_id = resp.headers.get("X-RestLi-Id", "unknown")
    print(f"  [LinkedIn] Posted \u2014 post ID: {post_id}")
    return {"status": "ok", "platform": "linkedin", "post_id": post_id}
