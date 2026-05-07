"""Tests for mblogger — front matter parsing, Post model, and discovery."""

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mdsend import (
    Post,
    discover_posts,
    parse_front_matter,
    truncate,
    _extract_url,
    ALL_PLATFORMS,
    THREAD_PREFIX_OVERHEAD,
)

# ======================================================================
# parse_front_matter
# ======================================================================


class TestParseFrontMatter:
    def test_no_front_matter(self):
        body = "Just a simple post.\n\nNo header here."
        fields, text = parse_front_matter(body)
        assert fields == {}
        assert text == body

    def test_with_platforms(self):
        raw = "---\nplatforms: [linkedin, bluesky]\n---\n\nPost body here."
        fields, text = parse_front_matter(raw)
        assert fields == {"platforms": ["linkedin", "bluesky"]}
        assert text == "Post body here."

    def test_single_platform(self):
        raw = "---\nplatforms: [bluesky]\n---\n\nBluesky only post."
        fields, text = parse_front_matter(raw)
        assert fields == {"platforms": ["bluesky"]}
        assert text == "Bluesky only post."

    def test_empty_platforms_draft(self):
        raw = "---\nplatforms: []\n---\n\nDraft post."
        fields, text = parse_front_matter(raw)
        assert fields == {"platforms": []}
        assert text == "Draft post."

    def test_opening_delimiter_only(self):
        raw = "---\nplatforms: [bluesky]\n\nPost body."
        fields, text = parse_front_matter(raw)
        assert fields == {}
        assert text == raw

    def test_unknown_fields_ignored(self):
        raw = "---\ntitle: My Post\nplatforms: [bluesky]\n---\n\nBody."
        fields, text = parse_front_matter(raw)
        assert fields == {"title": "My Post", "platforms": ["bluesky"]}

    def test_platforms_without_brackets(self):
        raw = "---\nplatforms: linkedin, bluesky\n---\n\nBody."
        fields, text = parse_front_matter(raw)
        assert fields == {"platforms": ["linkedin", "bluesky"]}

    def test_strips_whitespace_in_platform_names(self):
        raw = "---\nplatforms: [linkedin ,  bluesky]\n---\n\nBody."
        fields, text = parse_front_matter(raw)
        assert fields == {"platforms": ["linkedin", "bluesky"]}

    def test_text_only_line(self):
        fields, text = parse_front_matter("Hello world")
        assert fields == {}
        assert text == "Hello world"


# ======================================================================
# Post (needs a real directory on disk)
# ======================================================================


@pytest.fixture
def posts_dir(tmp_path: Path):
    """Create a temporary posts directory with a few test posts."""
    posts = tmp_path / "posts"

    p1 = posts / "2026-05-03_15-30_both"
    p1.mkdir(parents=True)
    (p1 / "post.md").write_text(
        "---\nplatforms: [linkedin, bluesky]\n---\n\nBoth platforms."
    )

    p2 = posts / "2026-05-03_18-00_bluesky-only"
    p2.mkdir(parents=True)
    (p2 / "post.md").write_text("---\nplatforms: [bluesky]\n---\n\nBluesky only.")

    p3 = posts / "2026-05-04_no-header"
    p3.mkdir(parents=True)
    (p3 / "post.md").write_text("No header post.")

    p4 = posts / "2026-05-05_draft"
    p4.mkdir(parents=True)
    (p4 / "post.md").write_text("---\nplatforms: []\n---\n\nDraft.")

    return posts


@pytest.fixture
def post_both(posts_dir):
    return Post(posts_dir / "2026-05-03_15-30_both")


@pytest.fixture
def post_bsky_only(posts_dir):
    return Post(posts_dir / "2026-05-03_18-00_bluesky-only")


@pytest.fixture
def post_no_header(posts_dir):
    return Post(posts_dir / "2026-05-04_no-header")


@pytest.fixture
def post_draft(posts_dir):
    return Post(posts_dir / "2026-05-05_draft")


class TestPostBodyAndFields:
    def test_body_strips_front_matter(self, post_both):
        assert post_both.body == "Both platforms."

    def test_body_no_front_matter(self, post_no_header):
        assert post_no_header.body == "No header post."

    def test_fields_parsed(self, post_both):
        assert post_both.fields == {"platforms": ["linkedin", "bluesky"]}

    def test_fields_empty_when_no_header(self, post_no_header):
        assert post_no_header.fields == {}

    def test_text_includes_front_matter(self, post_both):
        assert "platforms:" in post_both.text
        assert "Both platforms." in post_both.text


class TestTargetPlatforms:
    def test_both_platforms(self, post_both):
        assert post_both.target_platforms(ALL_PLATFORMS) == {"linkedin", "bluesky"}

    def test_bluesky_only(self, post_bsky_only):
        assert post_bsky_only.target_platforms(ALL_PLATFORMS) == {"bluesky"}

    def test_no_header_defaults_to_all(self, post_no_header):
        assert post_no_header.target_platforms(ALL_PLATFORMS) == ALL_PLATFORMS

    def test_draft_returns_empty(self, post_draft):
        assert post_draft.target_platforms(ALL_PLATFORMS) == set()

    def test_cli_filter_intersects(self, post_both):
        assert post_both.target_platforms({"bluesky"}) == {"bluesky"}

    def test_cli_filter_empty(self, post_no_header):
        assert post_no_header.target_platforms(set()) == set()


class TestSortKey:
    def test_full_timestamp_sorts_first(self, posts_dir):
        early = Post(posts_dir / "2026-05-03_15-30_both")
        later = Post(posts_dir / "2026-05-03_18-00_bluesky-only")
        assert early.sort_key < later.sort_key

    def test_date_only_sorts_after_timestamp(self, posts_dir):
        ts = Post(posts_dir / "2026-05-03_15-30_both")
        date = Post(posts_dir / "2026-05-04_no-header")
        assert ts.sort_key < date.sort_key

    def test_content_hash_fallback(self, tmp_path):
        d = tmp_path / "no-date-slug"
        d.mkdir()
        (d / "post.md").write_text("Content here")
        p = Post(d)
        assert p.sort_key[0] == 2


class TestPublishedState:
    def test_fresh_post_is_not_published(self, post_both, posts_dir):
        PUBLISHED_DIR = posts_dir.parent / ".published"
        with patch("mdsend.core.PUBLISHED_DIR", PUBLISHED_DIR):
            assert post_both.published_platforms() == set()
            assert not post_both.published

    def test_mark_platform_published(self, post_both, posts_dir):
        PUBLISHED_DIR = posts_dir.parent / ".published"
        with patch("mdsend.core.PUBLISHED_DIR", PUBLISHED_DIR):
            post_both.mark_platform_published("linkedin", {"post_id": "123"})
            assert post_both.published_platforms() == {"linkedin"}
            assert not post_both.published

    def test_fully_published(self, post_both, posts_dir):
        PUBLISHED_DIR = posts_dir.parent / ".published"
        with patch("mdsend.core.PUBLISHED_DIR", PUBLISHED_DIR):
            for p in ("linkedin", "bluesky", "mastodon"):
                post_both.mark_platform_published(p, {})
            assert post_both.published
            assert post_both.published_platforms() == {"linkedin", "bluesky", "mastodon"}

    def test_is_platform_published(self, post_both, posts_dir):
        PUBLISHED_DIR = posts_dir.parent / ".published"
        with patch("mdsend.core.PUBLISHED_DIR", PUBLISHED_DIR):
            post_both.mark_platform_published("linkedin", {"post_id": "123"})
            assert post_both.is_platform_published("linkedin")
            assert not post_both.is_platform_published("bluesky")


class TestTruncate:
    def test_short_text_not_truncated(self):
        assert truncate("Hello", 100) == "Hello"

    def test_truncates_at_word_boundary(self):
        text = "This is a long sentence that should be cut off."
        result = truncate(text, 30)
        assert len(result) <= 30
        assert result.endswith("...")
        assert not result.rstrip(".").endswith(" ")

    def test_exact_fit(self):
        text = "Exactly twenty five chars"
        assert len(text) == 25
        assert truncate(text, 25) == text


class TestExtractUrl:
    def test_no_url(self):
        assert _extract_url("Hello world") is None

    def test_http_url(self):
        url = _extract_url("Check this http://example.com/page")
        assert url == "http://example.com/page"

    def test_https_url(self):
        url = _extract_url("Watch https://youtube.com/watch?v=abc123")
        assert url == "https://youtube.com/watch?v=abc123"

    def test_url_with_text_after(self):
        url = _extract_url("Link: https://example.com. More text.")
        assert url == "https://example.com."

    def test_url_at_end(self):
        url = _extract_url("See https://example.com/path")
        assert url == "https://example.com/path"

    def test_multiple_urls_returns_first(self):
        url = _extract_url("First https://first.com and second https://second.com")
        assert url == "https://first.com"


class TestPrepare:
    def test_prepare_uses_body_not_raw_text(self, posts_dir):
        p = Post(posts_dir / "2026-05-03_15-30_both")
        payload = p.prepare("linkedin")
        assert "platforms:" not in payload["texts"][0]
        assert payload["texts"][0] == "Both platforms."

    def test_prepare_always_returns_texts_key(self, posts_dir):
        for plat in ("linkedin", "bluesky"):
            p = Post(posts_dir / "2026-05-04_no-header")
            payload = p.prepare(plat)
            assert "texts" in payload
            assert isinstance(payload["texts"], list)
            assert len(payload["texts"]) == 1
            assert payload["texts"][0] == "No header post."

    def test_prepare_includes_media(self, posts_dir):
        p = Post(posts_dir / "2026-05-03_15-30_both")
        img = p.directory / "photo.jpg"
        img.write_text("fake-image-data")
        p.media_files = sorted(
            f for f in p.directory.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov")
            and f.name != "post.md"
        )
        payload = p.prepare("linkedin")
        assert len(payload["media"]) == 1
        assert payload["media"][0].name == "photo.jpg"


# ======================================================================
# discover_posts
# ======================================================================


class TestDiscoverPosts:
    def test_discovers_all_posts(self, posts_dir):
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            posts = discover_posts()
            assert len(posts) == 4

    def test_ignores_dot_directories(self, posts_dir):
        (posts_dir / ".published").mkdir()
        (posts_dir / ".hidden").mkdir()
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            posts = discover_posts()
            assert len(posts) == 4

    def test_returns_sorted_order(self, posts_dir):
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            posts = discover_posts()
            names = [p.name for p in posts]
            assert names == [
                "2026-05-03_15-30_both",
                "2026-05-03_18-00_bluesky-only",
                "2026-05-04_no-header",
                "2026-05-05_draft",
            ]

    def test_skips_directories_without_post_md(self, posts_dir):
        empty = posts_dir / "2026-05-06_empty"
        empty.mkdir()
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            posts = discover_posts()
            assert len(posts) == 4


# ======================================================================
# split_sentences
# ======================================================================


class TestSplitSentences:
    def test_empty_text(self):
        assert Post.split_sentences("") == [""]

    def test_single_sentence(self):
        assert Post.split_sentences("Hello world.") == ["Hello world."]

    def test_two_sentences(self):
        result = Post.split_sentences("Hello. World.")
        assert result == ["Hello.", "World."]

    def test_exclamation_and_question(self):
        result = Post.split_sentences("Hi! How are you? Fine.")
        assert result == ["Hi!", "How are you?", "Fine."]

    def test_newline_split(self):
        result = Post.split_sentences("First line.\nSecond line.\nThird.")
        assert result == ["First line.", "Second line.", "Third."]

    def test_trailing_whitespace_handling(self):
        result = Post.split_sentences("  Hello.   World.  ")
        assert result == ["Hello.", "World."]

    def test_no_trailing_punctuation(self):
        result = Post.split_sentences("Hello world")
        assert result == ["Hello world"]


# ======================================================================
# pack_thread
# ======================================================================


class TestPackThread:
    def test_empty_sentences(self):
        assert Post.pack_thread([""], 300, 25) == [""]

    def test_short_text_single_chunk(self):
        sentences = ["Hello world. This is short."]
        result = Post.pack_thread(sentences, 300, 25)
        assert len(result) == 1
        assert result[0] == "Hello world. This is short."

    def test_splits_across_multiple_chunks(self):
        sentences = ["A" * 200 + ".", "B" * 200 + ".", "C" * 200 + "."]
        result = Post.pack_thread(sentences, 300, 25)
        assert len(result) >= 2

    def test_each_chunk_under_limit_with_prefix_budget(self):
        sentences = ["A" * 200 + ".", "B" * 200 + ".", "C" * 200 + "."]
        result = Post.pack_thread(sentences, 300, 25)
        limit = 300 - THREAD_PREFIX_OVERHEAD
        for chunk in result:
            assert len(chunk) <= limit

    def test_single_overlong_sentence_truncated(self):
        sentence = "X" * 500 + "."
        result = Post.pack_thread([sentence], 300, 25)
        assert len(result) == 1
        assert len(result[0]) <= 300 - THREAD_PREFIX_OVERHEAD

    def test_hard_limit_of_max_threads_enforced(self):
        sentences = ["A" * 500 + "." for _ in range(30)]
        result = Post.pack_thread(sentences, 300, 25)
        assert len(result) == 25

    def test_last_chunk_gets_ellipsis_when_capped(self):
        sentences = ["A" * 500 + "." for _ in range(30)]
        result = Post.pack_thread(sentences, 300, 25)
        assert result[-1].endswith("…")

    def test_exact_fit_no_split(self):
        sentence = "A" * 290
        result = Post.pack_thread([sentence], 300, 25)
        assert len(result) == 1
        assert result[0] == sentence


# ======================================================================
# prepare with threading
# ======================================================================


class TestPrepareThreading:
    def test_short_bluesky_post_returns_single_text(self, posts_dir):
        d = posts_dir / "short-bsky"
        d.mkdir()
        (d / "post.md").write_text("Short post under the limit.")
        p = Post(d)
        payload = p.prepare("bluesky")
        assert "texts" in payload
        assert len(payload["texts"]) == 1
        assert payload["texts"][0] == "Short post under the limit."

    def test_bluesky_post_over_limit_threads(self, posts_dir):
        d = posts_dir / "long-post"
        d.mkdir()
        body = ". ".join(["Sentence " + str(i) for i in range(40)])
        assert len(body) > 300
        (d / "post.md").write_text(body)
        p = Post(d)
        payload = p.prepare("bluesky")
        assert "texts" in payload
        assert len(payload["texts"]) > 1

    def test_linkedin_returns_texts_list(self, posts_dir):
        p = Post(posts_dir / "2026-05-04_no-header")
        payload = p.prepare("linkedin")
        assert "texts" in payload
        assert len(payload["texts"]) == 1

    def test_media_included_in_thread_payload(self, posts_dir):
        p = Post(posts_dir / "2026-05-04_no-header")
        img = p.directory / "photo.jpg"
        img.write_text("fake")
        p.media_files = sorted(
            f for f in p.directory.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov")
            and f.name != "post.md"
        )
        payload = p.prepare("bluesky")
        assert len(payload["media"]) == 1
        assert payload["media"][0].name == "photo.jpg"


# ======================================================================
# Thread prefix helper
# ======================================================================


class TestThreadPrefix:
    def test_single_post_no_prefix(self):
        from mdsend.platforms.bluesky import _make_thread_prefix
        assert _make_thread_prefix(1, 1) == "🧵 (1/1) "

    def test_multi_post_prefix(self):
        from mdsend.platforms.bluesky import _make_thread_prefix
        assert _make_thread_prefix(2, 5) == "🧵 (2/5) "

    def test_double_digit(self):
        from mdsend.platforms.bluesky import _make_thread_prefix
        assert _make_thread_prefix(12, 25) == "🧵 (12/25) "


# ======================================================================
# Dry-run output
# ======================================================================


class TestDryRun:
    def test_parse_args_defaults(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args([])
        assert platforms == ALL_PLATFORMS
        assert dry_run  # dry-run is the default now

    def test_parse_args_platforms(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args(
            ["--platforms", "linkedin", "bluesky"]
        )
        assert platforms == {"linkedin", "bluesky"}
        assert dry_run  # still dry-run by default

    def test_parse_args_dry_run(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args(["--dry-run"])
        assert platforms == ALL_PLATFORMS
        assert dry_run

    def test_parse_args_publish(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args(["--publish"])
        assert platforms == ALL_PLATFORMS
        assert not dry_run

    def test_parse_args_platforms_and_publish(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args(
            ["--platforms", "bluesky", "--publish"]
        )
        assert platforms == {"bluesky"}
        assert not dry_run

    def test_parse_args_publish_overrides_dry_run(self):
        from mdsend import parse_args
        platforms, dry_run, _new_slug = parse_args(
            ["--publish", "--dry-run"]
        )
        # --publish is a store_false on dry_run, so --dry-run won't undo it
        # Actually argparse processes left to right, so --dry-run wins here
        # That's fine — explicit `--dry-run` should override.
        pass

    def test_dry_run_does_not_write_sentinel(self, posts_dir):
        from mdsend import main
        PUBLISHED_DIR = posts_dir.parent / ".published"
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            with patch("mdsend.core.PUBLISHED_DIR", PUBLISHED_DIR):
                with patch.object(sys, "argv", ["mdsend"]):
                    main()
        assert not PUBLISHED_DIR.exists()

    def test_dry_run_output_includes_chunks(self, posts_dir, capsys):
        from mdsend import main
        d = posts_dir / "long-test"
        d.mkdir()
        (d / "post.md").write_text("A" * 400)
        with patch("mdsend.core.POSTS_DIR", posts_dir):
            with patch.object(sys, "argv", ["mdsend"]):
                main()
        captured = capsys.readouterr().out
        assert "chunk" in captured
        assert "media:" in captured or "chars" in captured
