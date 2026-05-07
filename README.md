# mdsend — File-based social media publisher

Write markdown posts, run `mdsend`, and it cross-posts to your social media platforms.

## Supported platforms

| Platform        | Max chars | Max media | API auth            |
|-----------------|-----------|-----------|---------------------|
| LinkedIn        | 3,000     | 1 image   | OAuth 2.0 (Bearer)  |
| Bluesky         | 300       | 4 images  | AT Protocol (App Password) |
| Mastodon        | 500       | 4 images  | OAuth (Access Token) |

## How it works

Each post is a directory named `YYYY-MM-DD_HH-MM_slug/` containing:

- `post.md` — the post text (markdown or plain text)
- Optional media files (jpg, png, gif, mp4, mov)

```
posts/
├── 2026-05-03_15-30_my-thoughts/
│   ├── post.md
│   └── image.jpg
└── 2026-05-04_18-00_hello-world/
    └── post.md
```

## Per-post platform targeting

By default every post goes to all platforms.  To control this per post,
add an optional front matter block at the top of `post.md`:

```
---
platforms: [bluesky]
---

This post will only appear on Bluesky.
```

```
---
platforms: []
---

This post is a draft — it will never be published.
```

## Installation

```bash
pip install mdsend
```

Or from source:

```bash
git clone https://github.com/algodesigner/mdsend
cd mdsend
pip install -e .
```

## Setup

Create a `.env` file with your API credentials:

```bash
cp .env.example .env
```

Fill in the credentials for the platforms you want to use.  See `.env.example`
for the full list of required fields.

## Usage

```bash
# Preview what would be posted (default — no API calls made)
cd /path/to/your/posts
mdsend

# Actually post live
mdsend --publish

# Post to specific platforms
mdsend --platforms bluesky
mdsend --platforms bluesky --publish
```

### Creating a new post

```bash
# Create a post directory and open the editor
mdsend --new "my-post-slug"
```

This creates a directory like `2026-05-04_21-30_my-post-slug/` with
a `post.md` file containing a front matter template, then opens it in
your `$EDITOR` (or `vi` by default).

### Dry run

`mdsend` runs in dry-run mode by default — it prints what would be posted
without calling any API.  Use `--publish` to post live.

### Multi-post threading (Bluesky)

Posts longer than 300 characters are automatically split into a threaded
thread on Bluesky.  Each chunk is prefixed with `🧵 (n/N) ` so readers
know it's part of a multi-part post.

### Idempotent publishing

Each platform gets its own sentinel file under `posts/.published/`.
Re-running is safe — already-published platforms are skipped.

## License

BSD 3-Clause. See LICENSE.
