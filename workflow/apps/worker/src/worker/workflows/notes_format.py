"""Pure helpers for the patch-notes pipeline.

Only the standard library here: these helpers run inside the workflow's
deterministic sandbox and in plain pytest on a CI runner, with no SDK imports.
"""

from __future__ import annotations

import json
import re
from typing import Any

# GitHub never sends more than 20 commits per push payload; the cap is defense in depth.
MAX_COMMITS = 20
MAX_SUBJECT_LEN = 200

# Titles the site's patch-notes tab expects. The prompt asks the model to use these.
KNOWN_SECTION_TITLES = (
    "Team Deathmatch",
    "Team Elimination",
    "Conquest",
    "Onslaught",
    "Ceres Awakens",
    "Proving Grounds",
    "Havoc",
    "Turbo TDM",
    "Launcher",
    "Hangar",
    "Market",
    "Tech tree",
    "General",
    "Known issues / please report",
)

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


# ---------------------------------------------------------------------------
# GitHub push payload helpers
# ---------------------------------------------------------------------------


def repo_name(push: dict[str, Any]) -> str:
    repository = push.get("repository") or {}
    if isinstance(repository, dict):
        return str(repository.get("name") or "")
    return ""


def push_ref(push: dict[str, Any]) -> str:
    return str(push.get("ref") or "")


def default_branch_ref(push: dict[str, Any]) -> str | None:
    """The ref a push must target to be the default branch, or None if unknown."""
    repository = push.get("repository") or {}
    if isinstance(repository, dict) and repository.get("default_branch"):
        return f"refs/heads/{repository['default_branch']}"
    return None


def _is_merge_subject(subject: str) -> bool:
    return subject.startswith("Merge ") or subject.startswith("Revert commit ")


def commit_entries(push: dict[str, Any]) -> list[dict[str, str]]:
    """Player-relevant commits of a push payload: [{"sha", "subject"}], merge commits dropped."""
    commits = push.get("commits") or []
    if not isinstance(commits, list):
        return []
    entries: list[dict[str, str]] = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        message = str(commit.get("message") or "").strip()
        if not message:
            continue
        subject = message.splitlines()[0].strip()
        if not subject or _is_merge_subject(subject):
            continue
        entries.append(
            {
                "sha": str(commit.get("id") or commit.get("sha") or ""),
                "subject": subject[:MAX_SUBJECT_LEN],
            }
        )
        if len(entries) >= MAX_COMMITS:
            break
    return entries


# ---------------------------------------------------------------------------
# Connector-response helpers (the GitHub connector's shapes vary by version)
# ---------------------------------------------------------------------------


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def extract_file_text(result: Any) -> str:
    """Pull file text out of a GitHub `get_file_contents` connector response.

    The MCP connector returns ``[headerText, {"resource": {"uri", "text"}}]``
    (or attribute-based equivalents); tolerate the plain-string and bare
    resource shapes too so a connector update cannot break the pipeline.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        for item in result[1:] if len(result) > 1 else result:
            text = extract_file_text(item)
            if text:
                return text
        return ""
    resource = _field(result, "resource")
    if resource is not None:
        text = _field(resource, "text")
        if isinstance(text, str):
            return text
    content = _field(result, "content")
    if isinstance(content, str):
        return content
    return ""


def extract_pr_url(result: Any) -> str:
    """Best-effort pull-request URL from a `create_pull_request` response."""
    url = _field(result, "url")
    if isinstance(url, str) and url:
        return url
    if isinstance(result, list):
        for item in result:
            url = extract_pr_url(item)
            if url and url != "created":
                return url
    return "created"


# ---------------------------------------------------------------------------
# LLM batch handling
# ---------------------------------------------------------------------------


def build_prompt(date: str, subjects: list[str]) -> str:
    return (
        "You write player-facing patch notes for Dreadnought Revival, a community "
        "server for the discontinued game Dreadnought (UE4, Steam App 835860): "
        "5v5/8v8 sci-fi capital-ship combat with game modes like Team Deathmatch, "
        "Team Elimination, Conquest, Onslaught, Ceres Awakens, Proving Grounds, "
        "Havoc and Turbo TDM.\n\n"
        f"Today is {date}. Turn the following commit subjects from the server repo "
        "into a patch-notes batch for players.\n\n"
        "Rules:\n"
        "- Player perspective only. Skip chores, CI, refactors, internal tooling and "
        "anything players cannot feel in the game.\n"
        "- No commit hashes, ticket numbers, branch names, file paths or internal "
        "identifiers. Never mention commits or repos.\n"
        "- One change per bullet, phrased as Fixed/Added/Changed/Rebalanced/Tuned...\n"
        "- Put names of new ships, modules, maps, modes or cosmetics in **bold**.\n"
        "- When a change replaces old behavior players knew, add a short 'Before, ...' "
        "clause inside the bullet.\n"
        "- Group bullets into sections titled exactly one of: " + ", ".join(KNOWN_SECTION_TITLES[:-1]) + ", General.\n"
        "- End with a section titled 'Known issues / please report' containing one bullet "
        "inviting players to report issues on the community Discord.\n"
        "- If nothing is player-facing, return {\"sections\": []}.\n\n"
        "Answer with strict JSON only, no markdown: "
        '{\"sections\": [{\"title\": "...", \"bullets\": ["...", "..."]}]}\n\n'
        "Commit subjects:\n"
        + "\n".join(f"- {s}" for s in subjects)
    )


def parse_llm_batch(text: str) -> list[dict[str, Any]]:
    """Validate the model's JSON answer into [{"title": str, "bullets": [str]}]."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in model answer: {cleaned[:120]!r}")
    data = json.loads(cleaned[start : end + 1])
    sections_raw = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections_raw, list):
        raise ValueError("model answer has no 'sections' list")
    sections: list[dict[str, Any]] = []
    for section in sections_raw:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        bullets_raw = section.get("bullets") or []
        if not title or not isinstance(bullets_raw, list):
            continue
        bullets = [str(b).strip() for b in bullets_raw if str(b or "").strip()]
        if bullets:
            sections.append({"title": title, "bullets": bullets})
    return sections


# ---------------------------------------------------------------------------
# Patch-notes data merging
# ---------------------------------------------------------------------------


def _normalize_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        bullets = [str(b) for b in (section.get("bullets") or []) if str(b or "").strip()]
        if title and bullets:
            out.append({"title": title, "bullets": bullets})
    return out


def merge_batch(
    notes_data: dict[str, Any],
    date: str,
    sections: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Merge one generated batch into the patch-notes document.

    A batch for a date that already exists (a second push the same day) is
    merged into that day's entry: same-titled sections have their bullets
    appended and deduplicated, new sections are appended.
    """
    data = dict(notes_data) if isinstance(notes_data, dict) else {}
    notes = [n for n in (data.get("notes") or []) if isinstance(n, dict)]
    clean = _normalize_sections(sections)

    index = next((i for i, n in enumerate(notes) if str(n.get("date") or "") == date), None)
    if index is None:
        notes.insert(0, {"date": date, "sections": clean})
    else:
        existing: dict[str, Any] = dict(notes[index])
        merged_titles: list[dict[str, Any]] = list(
            _normalize_sections(existing.get("sections") or [])
        )
        for section in clean:
            same = next(
                (s for s in merged_titles if s["title"].lower() == section["title"].lower()),
                None,
            )
            if same is None:
                merged_titles.append(section)
            else:
                seen = {b.casefold() for b in same["bullets"]}
                for bullet in section["bullets"]:
                    if bullet.casefold() not in seen:
                        same["bullets"].append(bullet)
                        seen.add(bullet.casefold())
        existing["sections"] = merged_titles
        notes[index] = existing

    data["notes"] = notes
    data["generated_at"] = generated_at
    return data


def render_notes_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def bullet_count(sections: list[dict[str, Any]]) -> int:
    return sum(len(s.get("bullets") or []) for s in sections if isinstance(s, dict))


def build_pr_body(date: str, commits: list[dict[str, str]]) -> str:
    lines = [
        f"Player-facing patch notes for **{date}**, generated from {len(commits)} commit(s) "
        "pushed to Dreadnought-Revival-server.",
        "",
        "Source commits:",
        "",
    ]
    lines += [f"- `{c['sha'][:7]}` {c['subject']}" if c["sha"] else f"- {c['subject']}" for c in commits]
    lines += [
        "",
        "---",
        "",
        "Generated by the `revival-patch-notes` Studio workflow (webhook-triggered). "
        "The daily Vibe ops run reviews and merges this PR; CI validates the JSON "
        "before the site deploys.",
    ]
    return "\n".join(lines)
