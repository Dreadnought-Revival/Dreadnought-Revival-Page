"""End-to-end test of the revival-patch-notes workflow with side-effect activities faked.

The workflow's deterministic orchestration is what's under test: filtering,
batch merging and the dry-run/publish decision. The connector and model
activities are replaced by fakes registered under the same activity names, so
no GitHub or Mistral credentials are touched. The dry-run input path exercises
everything except publishing; the publish test captures what would be pushed.
"""

import asyncio
import json
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows.testing import create_test_worker

from worker.workflows.patch_notes import PatchNotesWorkflow

WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=30)

EXISTING = {
    "generated_at": "2026-11-01T00:00:00+00:00",
    "notes": [
        {"date": "2026-11-01", "sections": [{"title": "General", "bullets": ["Old note."]}]}
    ],
}


@workflows.activity(name="fetch-patch-notes")
async def fake_fetch_patch_notes() -> str:
    return json.dumps(EXISTING)


@workflows.activity(name="generate-note-batch")
async def fake_generate_note_batch(date: str, subjects: list[str]) -> str:
    return json.dumps(
        {"sections": [{"title": "General", "bullets": [f"Shipped **{subjects[0]}**."]}]}
    )


@workflows.activity(name="publish-patch-notes")
async def fake_publish_patch_notes(branch: str, content: str, title: str, body: str, date: str) -> str:
    fake_publish_patch_notes.captured = {  # type: ignore[attr-defined]
        "branch": branch,
        "content": content,
        "title": title,
        "body": body,
        "date": date,
    }
    return "https://github.com/Dreadnought-Revival/Dreadnought-Revival-Page/pull/99"


def push_event(dry_run: bool = True) -> dict:
    return {
        "method": "POST",
        "path": "/",
        "headers": {"x-github-event": "push"},
        "body": {
            "repository": {"name": "Dreadnought-Revival-server", "default_branch": "master"},
            "ref": "refs/heads/master",
            "commits": [
                {"id": "abc1234def", "message": "add havoc rotation\n\ninternal: refs #12"},
                {"id": "fff0001111", "message": "Merge branch 'feature'"},
            ],
            "dry_run": dry_run,
        },
    }


async def _run(temporal_env, event, activities, test_id):
    async with create_test_worker(
        temporal_env,
        workflows=[PatchNotesWorkflow],
        activities=activities,
    ):
        handle = await temporal_env.client.start_workflow(
            "revival-patch-notes",
            event,
            id=test_id,
            task_queue="test-task-queue",
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )
        return await asyncio.wait_for(handle.result(), timeout=60)


async def test_dry_run_skips_publishing(temporal_env):
    result = await _run(
        temporal_env,
        push_event(dry_run=True),
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-dry-run",
    )
    assert result.startswith("dry run:")
    assert "1 section(s)" in result
    assert "1 bullet(s)" in result
    assert not hasattr(fake_publish_patch_notes, "captured")


async def test_publish_branch_and_pr(temporal_env):
    captured_before = getattr(fake_publish_patch_notes, "captured", None)
    result = await _run(
        temporal_env,
        push_event(dry_run=False),
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-publish",
    )
    assert result.endswith("pull/99")
    captured = fake_publish_patch_notes.captured  # type: ignore[attr-defined]
    assert captured["branch"].startswith("vibe/patch-notes-")
    assert captured["branch"].endswith("-abc1234")
    assert captured["title"].startswith("Patch notes ")
    data = json.loads(captured["content"])
    newest = data["notes"][0]
    assert newest["date"] != "2026-11-01"  # today's batch prepended before the old one
    assert any("Havoc" in s["title"] or s["title"] == "General" for s in newest["sections"])
    assert data["notes"][1]["date"] == "2026-11-01"
    if captured_before is None:
        del fake_publish_patch_notes.captured  # type: ignore[attr-defined]


async def test_ignores_non_push_events(temporal_env):
    event = push_event()
    event["headers"] = {"x-github-event": "ping"}
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-ping",
    )
    assert result.startswith("ignored: event_type='ping'")


async def test_ignores_other_repos(temporal_env):
    event = push_event()
    event["body"]["repository"]["name"] = "Dreadnought-Revival-Launcher"
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-other-repo",
    )
    assert result.startswith("ignored: repo=")


async def test_ignores_non_default_branch(temporal_env):
    event = push_event()
    event["body"]["ref"] = "refs/heads/feature-x"
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-feature-branch",
    )
    assert result.startswith("ignored: 'refs/heads/feature-x'")
