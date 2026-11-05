"""Unit tests for the stdlib GitHub REST client.

``_request_sync`` is the seam: tests replace it with a fake that records every
call and answers with canned responses, so no HTTP and no token are needed.
The async wrappers are exercised through ``asyncio.to_thread``.
"""

import asyncio
import base64
import json

import pytest

from worker.workflows import github_rest

TOKEN = "github_pat_test_token"


class FakeAPI:
    """Records calls and replays canned flat responses (method, path, status, text, error)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, path, token, *, params=None, body=None, raw=False):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "token": token,
                "params": params,
                "body": body,
                "raw": raw,
            }
        )
        for want_method, want_path, status, text, error in self.responses:
            if want_method == method and want_path == path:
                if error is not None:
                    raise error
                return status, text
        raise AssertionError(f"unexpected request: {method} {path} params={params}")


NOTES = "/repos/o/r/contents/data/patch-notes.json"
REF_MAIN = "/repos/o/r/git/ref/heads/main"
REFS = "/repos/o/r/git/refs"
PULLS = "/repos/o/r/pulls"


def test_get_file_text_uses_raw_accept_and_ref(monkeypatch):
    fake = FakeAPI([("GET", NOTES, 200, '{"notes": []}', None)])
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    text = asyncio.run(
        github_rest.get_file_text("o", "r", "data/patch-notes.json", ref="main", token=TOKEN)
    )

    assert text == '{"notes": []}'
    (call,) = fake.calls
    assert call["raw"] is True
    assert call["params"] == {"ref": "main"}
    assert call["token"] == TOKEN


def test_get_file_text_raises_on_http_error(monkeypatch):
    fake = FakeAPI([("GET", NOTES, 0, "", github_rest.GitHubError(404, "GET", NOTES, "Not Found"))])
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    with pytest.raises(github_rest.GitHubError) as excinfo:
        asyncio.run(github_rest.get_file_text("o", "r", "data/patch-notes.json", token=TOKEN))
    assert excinfo.value.status == 404


def test_create_branch_points_new_ref_at_main_sha(monkeypatch):
    fake = FakeAPI(
        [
            ("GET", REF_MAIN, 200, json.dumps({"object": {"sha": "mainsha"}}), None),
            ("POST", REFS, 201, "{}", None),
        ]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    asyncio.run(github_rest.create_branch("o", "r", "vibe/patch-notes-x", token=TOKEN))

    assert fake.calls[0]["method"] == "GET"
    assert fake.calls[1]["body"] == {"ref": "refs/heads/vibe/patch-notes-x", "sha": "mainsha"}


def test_create_branch_tolerates_existing_ref(monkeypatch):
    fake = FakeAPI(
        [
            ("GET", REF_MAIN, 200, json.dumps({"object": {"sha": "mainsha"}}), None),
            ("POST", REFS, 0, "", github_rest.GitHubError(422, "POST", REFS, "Reference already exists")),
        ]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    asyncio.run(github_rest.create_branch("o", "r", "vibe/patch-notes-x", token=TOKEN))  # no raise


def test_create_branch_reraises_other_errors(monkeypatch):
    fake = FakeAPI(
        [
            ("GET", REF_MAIN, 200, json.dumps({"object": {"sha": "mainsha"}}), None),
            ("POST", REFS, 0, "", github_rest.GitHubError(401, "POST", REFS, "Bad credentials")),
        ]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    with pytest.raises(github_rest.GitHubError) as excinfo:
        asyncio.run(github_rest.create_branch("o", "r", "vibe/patch-notes-x", token=TOKEN))
    assert excinfo.value.status == 401


def test_put_file_commits_base64_content_with_blob_sha(monkeypatch):
    fake = FakeAPI(
        [
            ("GET", NOTES, 200, json.dumps({"sha": "blobsha"}), None),
            ("PUT", NOTES, 200, "{}", None),
        ]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    asyncio.run(
        github_rest.put_file(
            "o",
            "r",
            "data/patch-notes.json",
            "vibe/patch-notes-x",
            "update patch notes for 2026-11-05",
            '{"notes": []}',
            token=TOKEN,
        )
    )

    get, put = fake.calls
    assert get["params"] == {"ref": "vibe/patch-notes-x"}
    assert put["body"]["message"] == "update patch notes for 2026-11-05"
    assert put["body"]["sha"] == "blobsha"
    assert put["body"]["branch"] == "vibe/patch-notes-x"
    assert put["body"]["content"] == base64.b64encode(b'{"notes": []}').decode("ascii")


def test_put_file_omits_sha_when_file_is_new(monkeypatch):
    fake = FakeAPI(
        [
            ("GET", NOTES, 200, json.dumps({"sha": None}), None),
            ("PUT", NOTES, 201, "{}", None),
        ]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    asyncio.run(github_rest.put_file("o", "r", "data/patch-notes.json", "br", "m", "{}", token=TOKEN))

    assert "sha" not in fake.calls[1]["body"]


def test_create_pull_request_returns_html_url(monkeypatch):
    fake = FakeAPI(
        [("POST", PULLS, 201, json.dumps({"html_url": "https://github.com/o/r/pull/42"}), None)]
    )
    monkeypatch.setattr(github_rest, "_request_sync", fake)

    url = asyncio.run(
        github_rest.create_pull_request(
            "o",
            "r",
            title="Patch notes 2026-11-05: 2 commit(s)",
            head="vibe/patch-notes-x",
            base="main",
            body="- body",
            token=TOKEN,
        )
    )

    assert url == "https://github.com/o/r/pull/42"
    assert fake.calls[0]["body"] == {
        "title": "Patch notes 2026-11-05: 2 commit(s)",
        "head": "vibe/patch-notes-x",
        "base": "main",
        "body": "- body",
    }
