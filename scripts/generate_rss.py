#!/usr/bin/env python3
"""Generate the patch-notes RSS feed (feed.xml) from data/patch-notes.json.

The feed is generated, never committed: deploy-pages.yml runs this at deploy
time right before the Pages artifact upload, and ci.yml runs it on every PR as
a check. One <item> per dated notes batch, newest first. Stdlib only — the
site stays dependency-free.

Usage: python3 scripts/generate_rss.py [--data data/patch-notes.json] [--out feed.xml]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.dom.minidom import parse as parse_xml
from xml.sax.saxutils import escape

SITE_URL = "https://dreadnought-revival.github.io/Dreadnought-Revival-Page"
CHANNEL_TITLE = "Dreadnought Revival Patch Notes"
CHANNEL_DESCRIPTION = (
    "What plays differently after each Dreadnought Revival server and "
    "launcher update. Newest first."
)

# markdown **bold** markers from the notes data -> <strong> in the feed
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# characters that are never valid in XML 1.0 text nodes
BAD_XML_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(value: str) -> str:
    """Escape a notes string for XML, keeping **bold** as <strong>."""
    escaped = escape(BAD_XML_RE.sub("", value))
    return BOLD_RE.sub(r"<strong>\1</strong>", escaped)


def _pub_date(day: str) -> str:
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def _last_build_date(data: dict) -> str:
    raw = data.get("generated_at")
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return format_datetime(dt.astimezone(timezone.utc))
    return format_datetime(datetime.now(timezone.utc))


def _entry_html(entry: dict) -> str:
    parts: list[str] = []
    for section in entry["sections"]:
        parts.append(f"<p><strong>{_text(section['title'])}</strong></p>")
        bullets = "".join(f"<li>{_text(b)}</li>" for b in section["bullets"])
        parts.append(f"<ul>{bullets}</ul>")
    return "".join(parts)


def _validate(data: dict) -> None:
    notes = data.get("notes")
    if not isinstance(notes, list) or not notes:
        raise ValueError("patch-notes data has no notes")
    for entry in notes:
        day = entry.get("date")
        if not isinstance(day, str) or not DATE_RE.match(day):
            raise ValueError(f"bad or missing entry date: {day!r}")
        sections = entry.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError(f"{day}: no sections")
        for section in sections:
            if not isinstance(section.get("title"), str) or not section["title"].strip():
                raise ValueError(f"{day}: section without a title")
            bullets = section.get("bullets")
            if not isinstance(bullets, list) or not bullets:
                raise ValueError(f"{day}: section {section['title']!r} has no bullets")
            for bullet in bullets:
                if not isinstance(bullet, str) or not bullet.strip():
                    raise ValueError(f"{day}: empty bullet in {section['title']!r}")


def build_feed(data: dict) -> str:
    site = SITE_URL.rstrip("/")
    feed_url = f"{site}/feed.xml"
    notes_url = f"{site}/#patch-notes"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{escape(CHANNEL_TITLE)}</title>",
        f"    <link>{notes_url}</link>",
        f"    <description>{escape(CHANNEL_DESCRIPTION)}</description>",
        "    <language>en</language>",
        f'    <atom:link href="{feed_url}" rel="self" type="application/rss+xml" />',
        f"    <lastBuildDate>{_last_build_date(data)}</lastBuildDate>",
    ]
    for entry in data["notes"]:
        day = entry["date"]
        lines += [
            "    <item>",
            f"      <title>{escape('Patch notes ' + day)}</title>",
            f"      <link>{notes_url}</link>",
            f'      <guid isPermaLink="false">dreadnought-revival-patch-notes-{day}</guid>',
            f"      <pubDate>{_pub_date(day)}</pubDate>",
            f"      <description>{_entry_html(entry)}</description>",
            "    </item>",
        ]
    lines += ["  </channel>", "</rss>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=repo_root / "data" / "patch-notes.json"
    )
    parser.add_argument("--out", type=Path, default=repo_root / "feed.xml")
    args = parser.parse_args(argv)

    data = json.loads(args.data.read_text(encoding="utf-8"))
    _validate(data)
    xml = build_feed(data)
    args.out.write_text(xml, encoding="utf-8")

    # well-formedness gate: fail loudly rather than ship broken XML
    parse_xml(str(args.out))
    print(f"wrote {args.out} ({len(data['notes'])} item(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
