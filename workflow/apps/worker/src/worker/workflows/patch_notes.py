"""Patch-notes pipeline: a push to the server repo becomes a player-facing PR on the site.

Unattended by design: a GitHub webhook trigger starts this workflow, so it runs
under the deployment's service identity, not a user's. GitHub is therefore not
reached through the OAuth connector (that would need a workspace-shared
credential) but through :mod:`worker.workflows.github_rest`, authenticating with
the fine-grained PAT bound to ``GITHUB_TOKEN`` from the workspace Secrets
Manager; model calls authenticate through the same worker identity. Never enable
``on_behalf_of`` here: webhook-started runs have no triggering user and OBO
runs would be rejected.

The format follows the server repo's ``dreadnought-patch-notes`` skill: commits
end their body with a ``Patch notes:`` block of per-mode, player-worded lines,
and the notes batch is built starting from those blocks. Commits marked
``Patch notes: none (internal)`` are dropped; commits without a block
(pre-convention) fall back to their subject, which the model phrases for
players. The generation activity validates its own batch before returning —
JSON shape and coverage of every block line's named section — so a retry
regenerates the batch and, once retries are exhausted, the execution is marked
failed instead of publishing incomplete notes. The PR is then squash-merged
automatically once its CI is green and its branch deleted; if CI fails or stays
pending the PR is left open for the daily ops run — nothing is force-merged.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Any

import pydantic

import mistralai.workflows as workflows
from mistralai.workflows import Depends, workflow
from mistralai.workflows.plugins.mistralai import ChatCompletionResponse, get_mistral_client

from worker.workflows import notes_format

OWNER = "Dreadnought-Revival"
PAGE_REPO = "Dreadnought-Revival-Page"
SERVER_REPO = "Dreadnought-Revival-server"
NOTES_PATH = "data/patch-notes.json"
MODEL = "mistral-medium-latest"

# Auto-merge budget: CI on a patch-notes PR (only data/ changes, so just the
# "checks" job) takes seconds; 15 minutes is the cap before the PR is left
# open for the daily ops run. The finalize activity's start-to-close timeout
# sits above it so the deadline is always the activity's own decision.
CI_WAIT_SECONDS = 15 * 60
CI_POLL_SECONDS = 15.0


def _github_token() -> str:
    # Imported inside the activity (not at module import): the workflow module is
    # re-imported inside Temporal's sandbox, where reading the environment at import
    # time is restricted; activities run unsandboxed, so this stays safe.
    from env.github import env as github_settings

    token = github_settings.github_token
    if not token:
        raise RuntimeError(
            "github_token is not configured: bind the workspace secret github_token "
            "to the GITHUB_TOKEN environment variable on the revival-ops deployment"
        )
    return token


class WebhookEvent(pydantic.BaseModel):
    """The wrapped HTTP request a webhook trigger delivers to the entrypoint."""

    method: str = "POST"
    path: str = "/"
    headers: dict[str, str] = pydantic.Field(default_factory=dict)
    query_params: dict[str, str] = pydantic.Field(default_factory=dict)
    body: dict[str, Any] | None = None
    raw_body: str | None = None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


# ---------------------------------------------------------------------------
# Activities: every side effect lives here, off the deterministic workflow path
# ---------------------------------------------------------------------------


@workflows.activity(name="fetch-patch-notes")
async def fetch_patch_notes() -> str:
    """Read the current data/patch-notes.json from the page repo."""
    from worker.workflows import github_rest

    return await github_rest.get_file_text(
        OWNER, PAGE_REPO, NOTES_PATH, token=_github_token()
    )


@workflows.activity(name="generate-note-batch", retry_policy_max_attempts=3)
async def generate_note_batch(
    date: str,
    notes_lines: list[str],
    subjects: list[str],
    client=Depends(get_mistral_client),
) -> str:
    """Turn the commits' patch-notes block lines (plus fallback subjects) into one
    player-facing batch; returns the model's JSON."""
    response: ChatCompletionResponse = await client.chat.complete_async(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the patch-notes writer for Dreadnought Revival. "
                    "You answer with strict JSON only, never markdown."
                ),
            },
            {
                "role": "user",
                "content": notes_format.build_prompt(date, notes_lines, subjects),
            },
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    if isinstance(content, list):  # content chunks: join defensively
        content = "".join(str(part) for part in content)
    if not content or not content.strip():
        raise RuntimeError("empty completion from patch-notes model")
    # Validate inside the activity, before returning: a raise here retries the
    # whole activity, which re-runs the model call, so a batch that dropped a
    # "Patch notes:" line gets regenerated instead of published (PR #25 showed
    # a silent skip is otherwise easy to miss). parse_llm_batch raises on
    # malformed JSON, validate_block_coverage on a batch missing a section a
    # block line names. Once retries are exhausted the failure propagates and
    # the execution is marked failed: incomplete notes never reach the site.
    sections = notes_format.parse_llm_batch(content)
    notes_format.validate_block_coverage(sections, notes_lines)
    return content


@workflows.activity(name="publish-patch-notes")
async def publish_patch_notes(
    branch: str,
    content: str,
    title: str,
    body: str,
    date: str,
) -> str:
    """Branch, commit the updated notes and open a PR against the page repo's main."""
    from worker.workflows import github_rest

    token = _github_token()
    await github_rest.create_branch(OWNER, PAGE_REPO, branch, token=token)
    await github_rest.put_file(
        OWNER,
        PAGE_REPO,
        NOTES_PATH,
        branch,
        message=f"update patch notes for {date}",
        content=content,
        token=token,
    )
    return await github_rest.create_pull_request(
        OWNER, PAGE_REPO, title=title, head=branch, base="main", body=body, token=token
    )


@workflows.activity(
    name="finalize-patch-notes",
    start_to_close_timeout=timedelta(minutes=20),
    retry_policy_max_attempts=2,
)
async def finalize_patch_notes(
    branch: str,
    number: int,
    date: str,
    pr_url: str,
) -> str:
    """Wait for the PR's CI, squash-merge it and delete its branch.

    Fail-safe by design: if CI fails, stays pending past ``CI_WAIT_SECONDS``,
    or GitHub refuses the merge, the PR is left open with its branch for the
    daily ops run — nothing is force-merged. The state check up front keeps a
    retry idempotent: an already-merged PR only gets its branch deleted, never
    a second merge. Polling sleeps here (inside the activity), not on the
    workflow path: activities are the SDK's home for side-effectful waiting.
    """
    from worker.workflows import github_rest

    token = _github_token()

    pr = await github_rest.get_pull_request(OWNER, PAGE_REPO, number, token=token)
    if str(pr.get("state") or "") == "closed":
        if pr.get("merged"):
            await github_rest.delete_branch(OWNER, PAGE_REPO, branch, token=token)
            return f"published patch notes for {date}: {pr_url} (auto-merged, branch deleted)"
        return f"patch notes PR was closed without merging: {pr_url}"

    deadline = time.monotonic() + CI_WAIT_SECONDS
    while True:
        runs = await github_rest.list_check_runs(OWNER, PAGE_REPO, branch, token=token)
        pending = [r for r in runs if r["status"] != "completed"]
        if runs and not pending:
            failed = sorted(
                r["name"]
                for r in runs
                if r["conclusion"] not in ("success", "skipped", "neutral")
            )
            if failed:
                return (
                    "patch notes PR left open, CI failed ("
                    + ", ".join(failed)
                    + f"): {pr_url}"
                )
            break
        if time.monotonic() >= deadline:
            return f"patch notes PR left open, CI still pending: {pr_url}"
        await asyncio.sleep(CI_POLL_SECONDS)

    head_sha = await github_rest.ref_sha(OWNER, PAGE_REPO, f"heads/{branch}", token=token)
    try:
        merged = await github_rest.merge_pull_request(
            OWNER,
            PAGE_REPO,
            number,
            expected_head_sha=head_sha,
            merge_method="squash",
            commit_title=f"add patch notes for {date}",
            token=token,
        )
    except github_rest.GitHubError as error:
        if error.status in (405, 409, 422):
            return f"patch notes PR left open, merge refused: {pr_url}"
        raise
    if not merged.get("merged"):
        return f"patch notes PR left open, merge refused: {pr_url}"
    await github_rest.delete_branch(OWNER, PAGE_REPO, branch, token=token)
    merged_sha = str(merged.get("sha") or "")[:7]
    suffix = (
        f" (auto-merged {merged_sha}, branch deleted)"
        if merged_sha
        else " (auto-merged, branch deleted)"
    )
    return f"published patch notes for {date}: {pr_url}{suffix}"


# ---------------------------------------------------------------------------
# Workflow: deterministic orchestration only
# ---------------------------------------------------------------------------


@workflows.workflow.define(
    name="revival-patch-notes",
    workflow_display_name="Revival patch notes",
    workflow_description=(
        "Turn a push to Dreadnought-Revival-server into a pull request of "
        "player-facing patch notes on the Dreadnought-Revival-Page site, "
        "auto-merged once its CI is green (branch deleted after merge)."
    ),
)
class PatchNotesWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, event: WebhookEvent) -> str:
        event_type = event.header("x-github-event")
        if event_type != "push":
            return f"ignored: event_type={event_type!r}"

        push = event.body or {}
        repo = notes_format.repo_name(push)
        if repo != SERVER_REPO:
            return f"ignored: repo={repo!r} is not {SERVER_REPO}"

        default_ref = notes_format.default_branch_ref(push)
        ref = notes_format.push_ref(push)
        if default_ref is not None and ref != default_ref:
            return f"ignored: {ref!r} is not the default branch"

        commits = notes_format.commit_entries(push)
        if not commits:
            return "ignored: no player-relevant commits in payload"

        # The commits' "Patch notes:" blocks are the source of truth; commits
        # marked "none (internal)" are dropped here, pre-convention commits
        # (no block) fall back to their subject for the model to phrase.
        notes_lines: list[str] = []
        fallback_subjects: list[str] = []
        for entry in commits:
            block = notes_format.patch_note_lines(entry.get("message") or "")
            if block is None:
                fallback_subjects.append(entry["subject"])
            elif block:
                notes_lines.extend(block)
        if not notes_lines and not fallback_subjects:
            return f"no player-facing changes in {len(commits)} commit(s); nothing published"

        now = workflow.now()
        date = now.date().isoformat()

        existing = await fetch_patch_notes()
        batch_json = await generate_note_batch(
            date=date, notes_lines=notes_lines, subjects=fallback_subjects
        )
        try:
            notes_data = json.loads(existing)
            if not isinstance(notes_data, dict):
                notes_data = {}
        except ValueError:
            notes_data = {}

        # Ordering is deterministic: parsing and sorting stay on the workflow
        # path so the skill's section order holds regardless of the model's
        # output order. Shape and block-line coverage are already validated
        # inside the generation activity, whose retries regenerate the batch.
        sections = notes_format.sort_sections(notes_format.parse_llm_batch(batch_json))
        if not sections:
            return f"no player-facing changes in {len(commits)} commit(s); nothing published"

        merged = notes_format.merge_batch(
            notes_data, date, sections, generated_at=now.isoformat()
        )
        content = notes_format.render_notes_json(merged)

        if push.get("dry_run"):
            return (
                f"dry run: would publish {len(sections)} section(s), "
                f"{notes_format.bullet_count(sections)} bullet(s) for {date}"
            )

        branch = f"vibe/patch-notes-{date}-{commits[0]['sha'][:7] or 'latest'}"
        title = f"Patch notes {date}: {len(commits)} commit(s)"
        body = notes_format.build_pr_body(date, commits)

        pr_url = await publish_patch_notes(
            branch=branch, content=content, title=title, body=body, date=date
        )
        # Auto-merge: wait for the PR's CI, squash-merge it, delete the branch.
        # A PR the finalize activity leaves open (CI failed or still pending) is
        # the daily ops run's queue; the run result says which happened.
        number = notes_format.pr_url_number(pr_url)
        if number is None:
            return (
                f"published patch notes for {date}: {pr_url} "
                "(not auto-merged: unreadable PR number)"
            )
        return await finalize_patch_notes(
            branch=branch, number=number, date=date, pr_url=pr_url
        )
