#!/usr/bin/env python3
"""Regenerate data/patch-notes.json from commits in the server and launcher repos.

Run by the "Update patch notes" workflow (hourly, workflow_dispatch, and
repository_dispatch of type "update-patch-notes"). Needs GITHUB_TOKEN in the
environment. New commits are detected by SHA against the existing data file,
so re-runs are idempotent.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

REPOS = {
    "server": "Dreadnought-Revival/Dreadnought-Revival-server",
    "launcher": "Dreadnought-Revival/Dreadnought-Revival-Launcher",
}
DATA_FILE = "data/patch-notes.json"
MAX_ENTRIES = 100
INITIAL_LOOKBACK_DAYS = 30
MAX_PAGES = 5


def api_get(path, token):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "dreadnought-revival-page",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def load_existing():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {"entries": []}
    entries = data.get("entries") or []
    return entries, {e["sha"] for e in entries}


def fetch_new(token, since):
    new_entries = []
    for label, repo in REPOS.items():
        for page in range(1, MAX_PAGES + 1):
            commits = api_get(
                f"/repos/{repo}/commits?per_page=100&page={page}&since={since}", token
            )
            if not commits:
                break
            for c in commits:
                sha = c["sha"]
                message = c["commit"]["message"].split("\n")[0].strip()
                new_entries.append(
                    {
                        "repo": label,
                        "sha": sha,
                        "short_sha": sha[:7],
                        "date": c["commit"]["author"]["date"],
                        "message": message,
                        "url": c["html_url"],
                        "author": c["commit"]["author"]["name"],
                    }
                )
            if len(commits) < 100:
                break
    return new_entries


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is required")

    entries, known = load_existing()
    if entries:
        since = max(e["date"] for e in entries)
    else:
        since = (
            datetime.now(timezone.utc) - timedelta(days=INITIAL_LOOKBACK_DAYS)
        ).isoformat()

    fetched = fetch_new(token, since)
    new_entries = [e for e in fetched if e["sha"] not in known]

    merged = sorted(entries + new_entries, key=lambda e: e["date"], reverse=True)[:MAX_ENTRIES]
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entries": merged,
    }
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"patch notes: {len(new_entries)} new, {len(merged)} total")


if __name__ == "__main__":
    main()
