"""
mdsend core — Post model, front matter parsing, text splitting, post discovery.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

POSTS_DIR = Path("posts")
PUBLISHED_DIR = POSTS_DIR / ".published"

PLATFORMS = {
    "linkedin": {
        "name": "LinkedIn",
        "max_chars": 3000,
        "media_count": 1,
    },
    "bluesky": {
        "name": "Bluesky",
        "max_chars": 300,
        "media_count": 4,
        "max_threads": 25,
    },
    "mastodon": {
        "name": "Mastodon",
        "max_chars": 500,
        "media_count": 4,
    },
}

ALL_PLATFORMS = set(PLATFORMS.keys())

THREAD_PREFIX_OVERHEAD = len("\U0001f9f5 (99/99) ")


# ============================================================================
# Front matter parser
# ============================================================================


def parse_front_matter(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = 1
    while end < len(lines) and lines[end].strip() != "---":
        end += 1

    if end >= len(lines):
        return {}, text

    header_block = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()

    fields: dict = {}
    for line in header_block.split("\n"):
        line = line.strip()
        m = re.match(r"(\w+)\s*:\s*(.+)", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if key == "platforms":
                val = val.strip("[]")
                fields[key] = [p.strip() for p in val.split(",") if p.strip()]
            else:
                fields[key] = val

    return fields, body


# ============================================================================
# Text truncation
# ============================================================================


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    print(f"  \u26a0\ufe0f  Text truncated from {len(text)} to {max_chars} chars")
    return text[: max_chars - 3].rsplit(" ", 1)[0] + "..."


# ============================================================================
# Post model
# ============================================================================


class Post:
    """A single post composed of markdown text and optional media files."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.md_file = directory / "post.md"
        self.media_files = sorted(
            p
            for p in directory.iterdir()
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov")
            and p.name != "post.md"
        )
        self._raw_text: Optional[str] = None
        self._fields: dict = {}
        self._body: Optional[str] = None

    @property
    def name(self) -> str:
        return self.directory.name

    # ------------------------------------------------------------------ #
    # Front matter and body
    # ------------------------------------------------------------------ #

    def _parse(self):
        if self._raw_text is not None:
            return
        raw = self.md_file.read_text(encoding="utf-8").strip()
        self._raw_text = raw
        self._fields, self._body = parse_front_matter(raw)

    @property
    def fields(self) -> dict:
        self._parse()
        return self._fields

    @property
    def body(self) -> str:
        self._parse()
        return self._body

    @property
    def text(self) -> str:
        if self._raw_text is None:
            self._parse()
        return self._raw_text

    # ------------------------------------------------------------------ #
    # Platform filtering
    # ------------------------------------------------------------------ #

    def target_platforms(self, cli_platforms: set[str]) -> set[str]:
        fm_platforms = self.fields.get("platforms")
        if fm_platforms is not None:
            if len(fm_platforms) == 0:
                return set()
            return set(fm_platforms) & cli_platforms
        return cli_platforms

    # ------------------------------------------------------------------ #
    # Published state (per-platform sentinels)
    # ------------------------------------------------------------------ #

    @property
    def sentinel_dir(self) -> Path:
        return PUBLISHED_DIR / self.name

    def published_platforms(self) -> set[str]:
        sentinel = self.sentinel_dir
        if not sentinel.is_dir():
            return set()
        return {p.name for p in sentinel.iterdir() if p.is_file()}

    def is_platform_published(self, platform: str) -> bool:
        return (self.sentinel_dir / platform).is_file()

    def mark_platform_published(self, platform: str, result: dict):
        sentinel = self.sentinel_dir
        sentinel.mkdir(parents=True, exist_ok=True)
        (sentinel / platform).write_text(json.dumps(result, indent=2))

    @property
    def published(self) -> bool:
        return self.published_platforms() == ALL_PLATFORMS

    # ------------------------------------------------------------------ #
    # Sorting
    # ------------------------------------------------------------------ #

    @property
    def sort_key(self) -> tuple:
        m = re.match(
            r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})_", self.name
        )
        if m:
            return (0, tuple(map(int, m.groups())))
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", self.name)
        if m:
            return (1, tuple(map(int, m.groups())))
        h = hashlib.sha256(self.text.encode()).hexdigest()[:8]
        return (2, h)

    # ------------------------------------------------------------------ #
    # Text splitting
    # ------------------------------------------------------------------ #

    @staticmethod
    def split_sentences(text: str) -> list[str]:
        if not text.strip():
            return [""]
        parts = re.split(r"(?<=[.!?])\s+|(?<=\n)\s*", text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def pack_thread(
        sentences: list[str], max_chars: int, max_threads: int
    ) -> list[str]:
        if not sentences or (len(sentences) == 1 and sentences[0] == ""):
            return [""]

        budget = max_chars - THREAD_PREFIX_OVERHEAD
        chunks: list[str] = []
        current: list[str] = []

        for sentence in sentences:
            candidate = " ".join(current + [sentence]) if current else sentence
            if len(candidate) <= budget:
                current.append(sentence)
            else:
                if current:
                    chunks.append(" ".join(current))
                    current = [sentence]
                else:
                    chunks.append(truncate(sentence, budget))

        if current:
            chunks.append(" ".join(current))

        if len(chunks) > max_threads:
            chunks = chunks[:max_threads]
            chunks[-1] = chunks[-1].rstrip() + "\u2026"

        return chunks

    # ------------------------------------------------------------------ #
    # Payload preparation
    # ------------------------------------------------------------------ #

    def prepare(self, platform: str) -> dict:
        cfg = PLATFORMS[platform]
        media = self.media_files[: cfg["media_count"]]

        if cfg.get("max_threads") and len(self.body) > cfg["max_chars"]:
            sentences = self.split_sentences(self.body)
            texts = self.pack_thread(
                sentences, cfg["max_chars"], cfg["max_threads"]
            )
            print(f"  \u26a0\ufe0f  Text split into {len(texts)} chunks for threading")
        else:
            texts = [truncate(self.body, cfg["max_chars"])]

        return {"texts": texts, "media": media}


# ============================================================================
# Post discovery
# ============================================================================


def discover_posts() -> list[Post]:
    posts = []
    for entry in sorted(POSTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        md_file = entry / "post.md"
        if md_file.exists():
            posts.append(Post(entry))
    posts.sort(key=lambda p: p.sort_key)
    return posts
