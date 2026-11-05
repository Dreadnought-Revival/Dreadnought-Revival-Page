"""Minimal GitHub REST client for the patch-notes pipeline.

The workflow runs unattended under webhook triggers, so it cannot use the OAuth
GitHub connector: that would need a workspace-shared credential, which the
workspace does not offer. Instead the deployment binds the workspace secret
``github_token`` (a GitHub fine-grained PAT) to the ``GITHUB_TOKEN`` environment
variable, and every call here carries it as a bearer token.

stdlib-only on purpose, mirroring ``env._mistral_secrets``: fewer moving parts
in the worker image and trivial to fake in tests, which replace
``_request_sync`` and pass tokens explicitly.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
TIMEOUT_SECONDS = 30.0


class GitHubError(RuntimeError):
    """A non-2xx GitHub API response, carrying the status for the caller."""

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"GitHub API {status} on {method} {path}: {body[:400]}")
        self.status = status


def _request_sync(
    method: str,
    path: str,
    token: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    raw: bool = False,
) -> tuple[int, str]:
    """One REST call; returns ``(status, text)`` and raises ``GitHubError`` on HTTP errors."""
    url = f"{API_URL}{path}"
    if params:
        url += "?" + urlencode(params, safe="/:")
    payload = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        # GitHub requires a User-Agent on every API call.
        "User-Agent": "dreadnought-revival-patch-notes",
    }
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace") if error.fp else ""
        raise GitHubError(error.code, method, path, detail) from None


async def _request(
    method: str,
    path: str,
    token: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    raw: bool = False,
) -> tuple[int, str]:
    return await asyncio.to_thread(
        _request_sync, method, path, token, params=params, body=body, raw=raw
    )


def _content_path(owner: str, repo: str, path: str) -> str:
    return f"/repos/{owner}/{repo}/contents/{quote(path, safe='/')}"


async def get_file_text(
    owner: str, repo: str, path: str, ref: str = "main", token: str = ""
) -> str:
    """The raw text of one file at ``ref``."""
    _, text = await _request(
        "GET", _content_path(owner, repo, path), token, params={"ref": ref}, raw=True
    )
    return text


async def ref_sha(owner: str, repo: str, ref: str, token: str) -> str:
    """The commit SHA a branch points at (``ref`` like ``heads/main``)."""
    _, text = await _request(
        "GET", f"/repos/{owner}/{repo}/git/ref/{quote(ref, safe='/')}", token
    )
    return str(json.loads(text)["object"]["sha"])


async def create_branch(
    owner: str, repo: str, branch: str, from_branch: str = "main", token: str = ""
) -> None:
    """Branch ``from_branch`` as ``refs/heads/<branch>``; a 422 (already exists) is tolerated."""
    sha = await ref_sha(owner, repo, f"heads/{from_branch}", token)
    try:
        await _request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            token,
            body={"ref": f"refs/heads/{branch}", "sha": sha},
        )
    except GitHubError as error:
        if error.status != 422:
            raise


async def put_file(
    owner: str,
    repo: str,
    path: str,
    branch: str,
    message: str,
    content: str,
    token: str = "",
) -> None:
    """Commit one file's new text on ``branch`` (base64 contents API, one commit)."""
    _, text = await _request(
        "GET", _content_path(owner, repo, path), token, params={"ref": branch}
    )
    blob_sha = json.loads(text).get("sha")
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if blob_sha:
        body["sha"] = blob_sha
    await _request("PUT", _content_path(owner, repo, path), token, body=body)


async def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str = "main",
    body: str = "",
    token: str = "",
) -> str:
    """Open a PR and return its ``html_url``."""
    _, text = await _request(
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        token,
        body={"title": title, "head": head, "base": base, "body": body},
    )
    return str(json.loads(text)["html_url"])
