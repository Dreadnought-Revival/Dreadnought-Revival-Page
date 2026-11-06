"""End-to-end test of the revival-patch-notes workflow with side-effect activities faked.

The workflow's deterministic orchestration is what's under test: filtering,
patch-notes block extraction, batch merging and the dry-run/publish decision.
The GitHub REST and model activities are replaced by fakes registered under the
same activity names, so no GitHub or Mistral credentials are touched. The
dry-run input path exercises everything except publishing; the publish test
captures what would be pushed.
"""

import asyncio
import json
from datetime import timedelta

import pytest
import mistralai.workflows as workflows
from mistralai.workflows.testing import create_test_worker

from worker.workflows import notes_format
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


@workflows.activity(name="generate-note-batch", retry_policy_max_attempts=3)
async def fake_generate_note_batch(date: str, notes_lines: list[str], subjects: list[str]) -> str:
    fake_generate_note_batch.called = True  # type: ignore[attr-defined]
    fake_generate_note_batch.calls = getattr(fake_generate_note_batch, "calls", 0) + 1  # type: ignore[attr-defined]
    fake_generate_note_batch.captured_inputs = {  # type: ignore[attr-defined]
        "notes_lines": list(notes_lines),
        "subjects": list(subjects),
    }
    content = json.dumps({"sections": [{"title": "Havoc", "bullets": list(notes_lines)}]})
    # same contract as the real activity: a batch that drops a section a block
    # line names must raise (the activity retries, then the run fails)
    notes_format.validate_block_coverage(notes_format.parse_llm_batch(content), notes_lines)
    return content


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
                {
                    "id": "abc1234def",
                    "message": (
                        "add havoc rotation\n\n"
                        "internal: refs #12\n\n"
                        "Patch notes:\n"
                        "- Havoc: New wave rotation on every map.\n"
                        "\n"
                        "Co-Authored-By: Someone <x>"
                    ),
                },
                {
                    "id": "222abcd333",
                    "message": "tune corvette spread\n\nPatch notes: none (internal)",
                },
                {"id": "fff0001111", "message": "Merge branch 'feature'"},
                {"id": "444aaa5555", "message": "fix dreadnought hp"},
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


def as_text(result, label: str) -> str:
    """Unwrap the workflow result to its text, tolerating SDK result envelopes.

    The SDK may deliver the entrypoint's return value wrapped in a dict; the
    assertion message keeps the full repr so a shape change is visible in CI.
    """
    assert result is not None, f"{label}: result was None"
    if isinstance(result, dict):
        for key in ("result", "output", "value", "text"):
            if isinstance(result.get(key), str):
                return result[key]
        raise AssertionError(f"{label}: unexpected dict result: {result!r}")
    assert isinstance(result, str), f"{label}: unexpected result type {type(result)}: {result!r}"
    return result


def _reset_fakes():
    fake_generate_note_batch.called = False  # type: ignore[attr-defined]
    fake_generate_note_batch.calls = 0  # type: ignore[attr-defined]
    fake_generate_note_batch.captured_inputs = None  # type: ignore[attr-defined]


async def test_dry_run_skips_publishing(temporal_env):
    _reset_fakes()
    result = await _run(
        temporal_env,
        push_event(dry_run=True),
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-dry-run",
    )
    text = as_text(result, "dry-run")
    assert text.startswith("dry run:"), f"dry-run text: {text!r}"
    assert "1 section(s)" in text
    assert "1 bullet(s)" in text
    assert not hasattr(fake_publish_patch_notes, "captured")
    # the block line feeds the model; the internal commit is dropped; the
    # block-less commit falls back to its subject
    captured = fake_generate_note_batch.captured_inputs  # type: ignore[attr-defined]
    assert captured == {
        "notes_lines": ["Havoc: New wave rotation on every map."],
        "subjects": ["fix dreadnought hp"],
    }, f"model inputs: {captured!r}"


async def test_publish_branch_and_pr(temporal_env):
    captured_before = getattr(fake_publish_patch_notes, "captured", None)
    _reset_fakes()
    result = await _run(
        temporal_env,
        push_event(dry_run=False),
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-publish",
    )
    text = as_text(result, "publish")
    assert text.endswith("pull/99"), f"publish text: {text!r}"
    captured = fake_publish_patch_notes.captured  # type: ignore[attr-defined]
    assert captured["branch"].startswith("vibe/patch-notes-"), f"branch: {captured['branch']!r}"
    assert captured["branch"].endswith("-abc1234"), f"branch: {captured['branch']!r}"
    assert captured["title"].startswith("Patch notes "), f"title: {captured['title']!r}"
    data = json.loads(captured["content"])
    newest = data["notes"][0]
    assert newest["date"] != "2026-11-01"  # today's batch prepended before the old one
    assert any(s["title"] == "Havoc" for s in newest["sections"])
    assert data["notes"][1]["date"] == "2026-11-01"
    assert "`abc1234` add havoc rotation" in captured["body"], f"body: {captured['body']!r}"
    if captured_before is None:
        del fake_publish_patch_notes.captured  # type: ignore[attr-defined]


def _chain_text(exc: BaseException) -> str:
    """Every message of an exception chain: workflow errors arrive wrapped, so
    the original ValueError (which names the dropped section) may live in a
    __cause__ or __context__ link rather than the top message."""
    parts = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        parts.append(f"{type(exc).__name__}: {exc}")
        exc = exc.__cause__ or exc.__context__  # type: ignore[assignment]
    return "\n".join(parts)


async def test_all_internal_commits_publish_nothing(temporal_env):
    _reset_fakes()
    event = push_event(dry_run=False)
    event["body"]["commits"] = [
        {"id": "999eee8888", "message": "refactor internals\n\nPatch notes: none (internal)"},
    ]
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-all-internal",
    )
    text = as_text(result, "all-internal")
    assert text.startswith("no player-facing changes in 1 commit(s)"), f"text: {text!r}"
    assert not fake_generate_note_batch.called  # type: ignore[attr-defined]
    assert not hasattr(fake_publish_patch_notes, "captured")


async def test_dropped_block_section_fails_the_run(temporal_env):
    # PR #25's failure mode: the model dropped one of a commit's two block
    # lines. The generation activity validates its own batch (same contract as
    # the real one, mirrored by the fake): a batch missing a section a block
    # line names raises, the activity retries, and once retries are exhausted
    # the run is marked failed naming the dropped section — nothing publishes,
    # so the site can never ship incomplete notes. The fake puts every block
    # line under "Havoc", so the "Escalation" line's section is missing on
    # purpose, on every attempt.
    _reset_fakes()
    event = push_event(dry_run=False)
    event["body"]["commits"] = [
        {
            "id": "abc1234def",
            "message": (
                "add escalation queue\n\n"
                "Patch notes:\n"
                "- Havoc: Waves rotate on every map.\n"
                "- Escalation: **Escalation** returns to the queues.\n"
                "\n"
                "Co-Authored-By: Someone <x>"
            ),
        },
    ]
    with pytest.raises(Exception) as exc_info:
        await _run(
            temporal_env,
            event,
            [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
            "test-revival-patch-notes-dropped-section",
        )
    chain = _chain_text(exc_info.value)
    assert "Escalation" in chain, f"failure must name the dropped section: {chain!r}"
    assert fake_generate_note_batch.called  # type: ignore[attr-defined]
    assert not hasattr(fake_publish_patch_notes, "captured")  # nothing published


async def test_ignores_non_push_events(temporal_env):
    event = push_event()
    event["headers"] = {"x-github-event": "ping"}
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-ping",
    )
    text = as_text(result, "ping")
    assert text.startswith("ignored: event_type='ping'"), f"ping text: {text!r}"


async def test_ignores_other_repos(temporal_env):
    event = push_event()
    event["body"]["repository"]["name"] = "Dreadnought-Revival-Launcher"
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-other-repo",
    )
    text = as_text(result, "other-repo")
    assert text.startswith("ignored: repo="), f"other-repo text: {text!r}"


async def test_ignores_non_default_branch(temporal_env):
    event = push_event()
    event["body"]["ref"] = "refs/heads/feature-x"
    result = await _run(
        temporal_env,
        event,
        [fake_fetch_patch_notes, fake_generate_note_batch, fake_publish_patch_notes],
        "test-revival-patch-notes-feature-branch",
    )
    text = as_text(result, "feature-branch")
    assert text.startswith("ignored: 'refs/heads/feature-x'"), f"feature-branch text: {text!r}"
