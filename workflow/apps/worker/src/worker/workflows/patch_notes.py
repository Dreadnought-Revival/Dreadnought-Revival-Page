"""Patch-notes pipeline: a push to the server repo becomes a player-facing PR on the site.

Unattended by design: a GitHub webhook trigger starts this workflow, so it runs
under the deployment's service identity, not a user's. GitHub is therefore not
reached through the OAuth connector (that would need a workspace-shared
credential) but through :mod:`worker.workflows.github_rest`, authenticating with
the fine-grained PAT bound to ``GITHUB_TOKEN`` from the workspace Secrets
Manager; model calls authenticate through the same worker identity. Never enable
``on_behalf_of`` here: webhook-started runs have no triggering user and OBO
runs would be rejected.
"""

from __future__ import annotations

import json
from typing import Any

import pydantic

import mistralai.workflows as workflows
from env.github import env as github_settings
from mistralai.workflows import Depends, workflow
from mistralai.workflows.plugins.mistralai import ChatCompletionResponse, get_mistral_client

from worker.workflows import github_rest, notes_format

OWNER = "Dreadnought-Revival"
PAGE_REPO = "Dreadnought-Revival-Page"
SERVER_REPO = "Dreadnought-Revival-server"
NOTES_PATH = "data/patch-notes.json"
MODEL = "mistral-medium-latest"


def _github_token() -> str:
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
    return await github_rest.get_file_text(
        OWNER, PAGE_REPO, NOTES_PATH, token=_github_token()
    )


@workflows.activity(name="generate-note-batch")
async def generate_note_batch(date: str, subjects: list[str], client=Depends(get_mistral_client)) -> str:
    """Turn commit subjects into one player-facing batch; returns the model's JSON."""
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
            {"role": "user", "content": notes_format.build_prompt(date, subjects)},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    if isinstance(content, list):  # content chunks: join defensively
        content = "".join(str(part) for part in content)
    if not content or not content.strip():
        raise RuntimeError("empty completion from patch-notes model")
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


# ---------------------------------------------------------------------------
# Workflow: deterministic orchestration only
# ---------------------------------------------------------------------------


@workflows.workflow.define(
    name="revival-patch-notes",
    workflow_display_name="Revival patch notes",
    workflow_description=(
        "Turn a push to Dreadnought-Revival-server into a pull request of "
        "player-facing patch notes on the Dreadnought-Revival-Page site."
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
        subjects = [c["subject"] for c in commits]

        now = workflow.now()
        date = now.date().isoformat()

        existing = await fetch_patch_notes()
        batch_json = await generate_note_batch(date=date, subjects=subjects)
        # Parsing and validation are deterministic: keep them on the workflow path so
        # a malformed model answer retries the activity without re-publishing.
        try:
            notes_data = json.loads(existing)
            if not isinstance(notes_data, dict):
                notes_data = {}
        except ValueError:
            notes_data = {}

        sections = notes_format.parse_llm_batch(batch_json)
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
        return f"published patch notes for {date}: {pr_url}"
