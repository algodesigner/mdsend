"""
mdsend CLI — argument parsing and main entry point.
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from mdsend.core import ALL_PLATFORMS, POSTS_DIR, discover_posts
from mdsend.platforms import PLATFORM_HANDLERS


def parse_args(argv: list[str]) -> tuple[set[str], bool]:
    parser = argparse.ArgumentParser(
        prog="mdsend",
        description="Publish markdown posts to social media platforms.",
    )
    parser.add_argument(
        "--platforms",
        nargs="+",
        choices=sorted(ALL_PLATFORMS),
        default=sorted(ALL_PLATFORMS),
        help="Platforms to publish to (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview what would be posted without sending anything",
    )
    parser.add_argument(
        "--publish",
        action="store_false",
        dest="dry_run",
        help="Actually post live (default is dry-run)",
    )
    parsed = parser.parse_args(argv)
    return set(parsed.platforms), parsed.dry_run


def _cmd_new():
    """Handle the --new subcommand: create a post directory and open editor."""
    slug = "untitled"
    editor = os.environ.get("EDITOR", "vi")

    # Parse remaining args after --new
    args = sys.argv[sys.argv.index("--new") + 1 :]
    if args and not args[0].startswith("--"):
        raw = args[0]
        slug = (
            raw.lower().replace(" ", "-").replace("_", "-")
        )
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        slug = slug.strip("-") or "untitled"

    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    dir_name = f"{now}_{slug}"
    post_dir = POSTS_DIR / dir_name
    post_dir.mkdir(parents=True, exist_ok=True)

    template = (
        "---\n"
        "platforms: [linkedin, bluesky, mastodon]\n"
        "---\n\n\n"
    )

    (post_dir / "post.md").write_text(template)
    print(f"Created {post_dir / 'post.md'}")
    subprocess.run([editor, str(post_dir / "post.md")], check=False)


def main():
    if "--new" in sys.argv:
        _cmd_new()
        return

    platforms, dry_run = parse_args(sys.argv[1:])

    if not platforms:
        platforms = ALL_PLATFORMS

    if dry_run:
        print("\U0001f50d Dry-run mode \u2014 use --publish to post live.\n")

    posts = discover_posts()

    if not posts:
        print("No posts found.")
        return

    print(f"Found {len(posts)} post(s):\n")

    for post in posts:
        targets = post.target_platforms(platforms)

        if not targets:
            skip_reason = "no platforms selected (draft)"
            print(f"\u23ed\ufe0f  {post.name}/ \u2014 {skip_reason}")
            continue

        already = post.published_platforms()
        pending = targets - already

        if not pending:
            print(
                f"\u2705 {post.name}/ "
                f"\u2014 already published to all selected platforms"
            )
            continue

        print(f"\U0001f4c4 {post.name}/")
        for platform in sorted(pending):
            payload = post.prepare(platform)

            if dry_run:
                for i, chunk in enumerate(payload["texts"]):
                    preview = chunk[:80].replace("\n", " ")
                    print(
                        f"  [{platform}] chunk {i+1}/{len(payload['texts'])}: "
                        f"{len(chunk)} chars \u2014 {preview}"
                    )
                if payload["media"]:
                    names = [m.name for m in payload["media"]]
                    print(f"         media: {names}")
                continue

            handler = PLATFORM_HANDLERS[platform]
            try:
                result = handler(payload["texts"], payload["media"])
                post.mark_platform_published(platform, result)
                print(f"  \u2713 {platform}")
            except Exception as exc:
                print(f"  \u2717 {platform}: {exc}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
