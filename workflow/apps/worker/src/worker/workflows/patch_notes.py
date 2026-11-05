"""Patch-notes pipeline: a push to the server repo becomes a player-facing PR on the site.

Unattended by design: a GitHub webhook trigger starts this workflow, so it runs
under the deployment's service identity, not a user's. The GitHub connector
therefore resolves the workspace-scope credential configured in Studio; model
calls authenticate through the same worker identity. Never enable
``on_behalf_of`` here: webhook-started runs have no triggering user and OBO
runs would be rejected.
"""

from __future__ import annotations

import json
from typing import Any

import pydantic

import mistralai.workflows as workflows
from mistralai.workflows import Depends, workflow
from mistralai.workflows.plugins.mistralai import ChatCompletionResponse, get_mistral_client
from mistralai.workflows.plugins.mistralai.connectors import (
    ToolCallClient,
    connector,
    uses_connectors,
)

from worker.workflows import notes_format

OWNER = "Dreadnought-Revival"
PAGE_REPO = "Dreadnought-Revival-Page"
SERVER_REPO = "Dreadnought-Revival-server"
NOTES_PATH = "data/patch-notes.json"
MODEL = "mistral-medium-latest"

# Unattended runs resolve the deployment's service identity, so the workspace-scope
# credential on the GitHub connector serves these calls. auto_auth=False: the trigger
# path has no interactive user, credentials must already exist, and skipping the
# preflight keeps test workers from needing them.
github = connector("github_app", run_as="deployment", auto_auth=False)


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
async def fetch_patch_notes(client: ToolCallClient = Depends(github)) -> str:
    """Read the current data/patch-notes.json from the page repo."""
    result = await client.call_tool(
        tool_name="get_file_contents",
        arguments={"owner": OWNER, "repo": PAGE_REPO, "path": NOTES_PATH},
    )
    text = notes_format.extract_file_text(result)
    if not text:
        raise RuntimeError(f"empty response reading {NOTES_PATH} from {OWNER}/{PAGE_REPO}")
    return text


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
    client: ToolCallClient = Depends(github),
) -> str:
    """Branch, commit the updated notes and open a PR against the page repo's main."""
    await client.call_tool(
        tool_name="create_branch",
        arguments={"branch": branch, "owner": OWNER, "repo": PAGE_REPO, "from_branch": "main"},
    )
    await client.call_tool(
        tool_name="push_files",
        arguments={
            "branch": branch,
            "owner": OWNER,
            "repo": PAGE_REPO,
            "message": f"update patch notes for {date}",
            "files": [{"path": NOTES_PATH, "content": content}],
        },
    )
    result = await client.call_tool(
        tool_name="create_pull_request",
        arguments={
            "owner": OWNER,
            "repo": PAGE_REPO,
            "base": "main",
            "head": branch,
            "title": title,
            "body": body,
            "draft": False,
        },
    )
    return notes_format.extract_pr_url(result)


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
@uses_connectors(github)
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
