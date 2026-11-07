"""Pure helpers for the patch-notes pipeline.

Only the standard library here: these helpers run inside the workflow's
deterministic sandbox and in plain pytest on a CI runner, with no SDK imports.

The format follows the server repo's ``dreadnought-patch-notes`` skill
(``.claude/skills/dreadnought-patch-notes``): every commit ends its body with a
``Patch notes:`` block of per-mode, player-worded lines (or ``Patch notes:
none (internal)`` for work players never see), and the notes are built starting
from those blocks. Commits without a block (pre-convention) fall back to their
subject, which the model phrases for players.
"""

from __future__ import annotations

import json
import re
from typing import Any

# GitHub never sends more than 20 commits per push payload; the cap is defense in depth.
MAX_COMMITS = 20
MAX_SUBJECT_LEN = 200

# The section order the skill prescribes: game modes first (in the skill's
# order), then the cross-mode section, then the out-of-match areas, and
# General. ``All game modes`` sits after the modes because a player reads
# their own mode's section first and then the everything-section. Batches
# carry no known-issues closer: issue reporting is the site's link to the
# server repo's GitHub issue tracker.
KNOWN_SECTION_TITLES = (
    "Team Deathmatch",
    "Team Elimination",
    "Conquest",
    "Onslaught",
    "Ceres Awakens",
    "Proving Grounds",
    "Havoc",
    "Turbo TDM",
    "Escalation",
    "All game modes",
    "Launcher",
    "Hangar",
    "Market",
    "Tech tree",
    "Social",
    "General",
)
SECTION_ORDER = KNOWN_SECTION_TITLES

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")
_PATCH_NOTES_RE = re.compile(r"^patch notes:\s*(.*)$", re.IGNORECASE)
_INTERNAL_BLOCK = "none (internal)"


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
    """Player-relevant commits of a push payload: [{"sha", "subject", "message"}].

    Merge commits and empty messages are dropped; the full message is kept so the
    ``Patch notes:`` block can be parsed out of it later.
    """
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
                "message": message,
            }
        )
        if len(entries) >= MAX_COMMITS:
            break
    return entries


def patch_note_lines(message: str) -> list[str] | None:
    """The ``Patch notes:`` block of a commit message.

    Returns the block's bullet lines without their leading ``-``, ``[]`` when the
    block says ``none (internal)`` (explicitly internal: drop the commit), or
    ``None`` when the commit has no block (pre-convention commit: fall back to
    its subject).
    """
    if not message:
        return None
    lines = message.splitlines()
    for idx, line in enumerate(lines):
        match = _PATCH_NOTES_RE.match(line.strip())
        if not match:
            continue
        rest = match.group(1).strip()
        if rest.lower() == _INTERNAL_BLOCK:
            return []
        out: list[str] = []
        if rest:
            if rest.startswith("-"):
                rest = rest[1:].strip()
            if rest:
                out.append(rest)
        for follow in lines[idx + 1:]:
            stripped = follow.strip()
            if not stripped.startswith("-"):
                break  # blank line, paragraph or trailer: the block is over
            bullet = stripped[1:].strip()
            if bullet:
                out.append(bullet)
        return out
    return None


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


def pr_url_number(url: str) -> int | None:
    """The PR number from a github.com ``.../pull/N`` URL, or None.

    The publish activity returns the PR's ``html_url``; the auto-merge step
    needs the number for the merge API. An unparseable URL means auto-merge is
    skipped, not failed: the PR still exists for the daily ops run.
    """
    match = re.search(r"/pull/(\d+)", url)
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# LLM batch handling
# ---------------------------------------------------------------------------


def _canonical_title(title: str) -> str:
    """Map a model-written section title onto the skill's canonical spelling."""
    for known in KNOWN_SECTION_TITLES:
        if known.casefold() == title.strip().casefold():
            return known
    return title


def build_prompt(date: str, notes_lines: list[str], subjects: list[str]) -> str:
    """Ask the model for one player-facing batch.

    ``notes_lines`` are the commits' ``Patch notes:`` block lines (already
    player-worded, each prefixed with its game mode or area). ``subjects`` are
    the bare subjects of commits without a block, which the model phrases for
    players itself.
    """
    return (
        "You write player-facing patch notes for Dreadnought Revival, a community "
        "server for the discontinued game Dreadnought (UE4, Steam 835860): "
        "5v5/8v8 sci-fi capital-ship combat with game modes like Team Deathmatch, "
        "Team Elimination, Conquest, Onslaught, Ceres Awakens, Proving Grounds, "
        "Havoc, Turbo TDM and Escalation.\n\n"
        f"Today is {date}. Build one patch-notes batch for players from the "
        "commits below.\n\n"
        "Most commits end with a \"Patch notes:\" block whose lines are already "
        "written for players, each prefixed with the game mode or area it belongs "
        "to (for example \"Conquest: Captured points now show as your team's "
        "territory on the minimap.\"). Those lines are the source of truth: sort "
        "each line into the section its prefix names, stripping the prefix from "
        "the bullet. Every block line MUST appear in the batch, under the section "
        "its prefix names: never drop a line, never merge a line away into "
        "another section's bullet, and lines naming different modes go to "
        "different sections, each with at least one bullet of its own. You may "
        "reword a line for players or merge duplicate lines that describe the "
        "same change (keeping the newer wording), but the change itself must "
        "survive. A dropped block line fails the run. Commits marked "
        "\"Patch notes: none (internal)\" have already been dropped.\n\n"
        "Commits without a block (older style) are given as bare subjects: write "
        "bullets for them in the same style, but only for what players can feel "
        "in the game.\n\n"
        "Rules:\n"
        "- Map each change to the game mode it actually affects, never a mode it "
        "does not touch: the mode a \"Patch notes:\" line names, or the mode the "
        "commit's context makes clear. A change that affects every mode (scoring, "
        "bots, rewards, matchmaker-wide behavior) goes under \"All game modes\"; "
        "chat, squads and social features under \"Social\"; launcher, hangar, "
        "market and tech tree under their own sections. When a commit touches two "
        "modes, give each mode its own bullet. If you cannot tell the mode, use "
        "\"General\" rather than guessing.\n"
        "- Group bullets into sections titled exactly one of: "
        + ", ".join(KNOWN_SECTION_TITLES) + ".\n"
        "- Order the sections exactly like that list.\n"
        "- One change per bullet, one or two plain sentences.\n"
        "- \"Before, ...\" clauses are good when a change replaces behavior players knew.\n"
        "- Bold a map or feature name when it is new or back.\n"
        "- Map names as players know them: Ryugu Haven (Space02), Elysium (Paradise), "
        "Amirani, Juno (Space03), Cronian Rapids (Space04), Thebe (DansMap). "
        "Never the internal path.\n"
        "- Never invent. If a value is our best estimate, say so plainly.\n"
        "- No internals: no commit hashes, file names, offsets, function names or "
        "log lines. Never mention commits or repos.\n"
        "- No \"Known issues\" section and no requests to report: the site links "
        "the server's issue tracker for that.\n"
        "- If nothing is player-facing, return {\"sections\": []}.\n\n"
        "Answer with strict JSON only, no markdown: "
        '{"sections": [{"title": "...", "bullets": ["...", "..."]}]}\n\n'
        "Patch-notes lines from the commits' blocks:\n"
        + ("\n".join(f"- {line}" for line in notes_lines) if notes_lines else "- (none)")
        + "\n\n"
        "Commits without a block (bare subjects):\n"
        + ("\n".join(f"- {s}" for s in subjects) if subjects else "- (none)")
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
        title = _canonical_title(str(section.get("title") or ""))
        bullets_raw = section.get("bullets") or []
        if not title or not isinstance(bullets_raw, list):
            continue
        bullets = [str(b).strip() for b in bullets_raw if str(b or "").strip()]
        if bullets:
            sections.append({"title": title, "bullets": bullets})
    return sections


def sort_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order sections the way the skill prescribes; unknown titles go last."""
    def rank(section: dict[str, Any]) -> tuple[int, Any]:
        title = str(section.get("title") or "").strip()
        for position, known in enumerate(SECTION_ORDER):
            if known.casefold() == title.casefold():
                return (0, position)
        return (1, title.lower())

    return sorted(sections, key=rank)


def missing_block_sections(
    sections: list[dict[str, Any]], notes_lines: list[str]
) -> list[str]:
    """Canonical section titles that block lines name but the batch lacks.

    Only lines whose prefix (the text before the first colon) canonicalizes to a
    known section title are checked: the author of a ``Patch notes:`` block
    names the mode on purpose, so a batch without that section dropped a change.
    Lines with no colon or an unknown prefix stay the model's call (it decides
    placement), so they never fail the gate.
    """
    present = {
        str(s.get("title") or "").strip().casefold()
        for s in sections
        if isinstance(s, dict)
    }
    missing: list[str] = []
    for line in notes_lines:
        if ":" not in line:
            continue
        prefix = line.split(":", 1)[0].strip()
        if not prefix:
            continue
        title = _canonical_title(prefix)
        if title not in KNOWN_SECTION_TITLES:
            continue
        if title.casefold() not in present and title not in missing:
            missing.append(title)
    return missing


def validate_block_coverage(
    sections: list[dict[str, Any]], notes_lines: list[str]
) -> None:
    """Fail loudly when the model drops a ``Patch notes:`` block line's section.

    A silent skip (a mode's change never reaching the site) is the pipeline's
    worst failure mode: it publishes incomplete notes and nobody notices. So
    the workflow calls this before merging, and a raise here fails the run and
    lets the trigger retry instead of publishing an incomplete batch.
    """
    missing = missing_block_sections(sections, notes_lines)
    if missing:
        raise ValueError(
            "patch-notes batch dropped section(s) named by commit block lines: "
            + ", ".join(missing)
            + "; refusing to publish incomplete notes"
        )


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
        "The workflow squash-merges this PR automatically once CI is green (its "
        "branch is deleted after); if CI fails it stays open for the daily Vibe "
        "ops run. CI validates the JSON before the site deploys.",
    ]
    return "\n".join(lines)
