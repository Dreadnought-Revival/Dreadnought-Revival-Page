"""GitHub access for the patch-notes pipeline.

A GitHub fine-grained PAT (read/write Contents and Pull requests on the page
repo) that the managed deployment binds to ``GITHUB_TOKEN`` from the workspace
secret ``github_token``. Marked :class:`~env.WorkspaceSecret` so a deployment
that runs with ``MISTRAL_SECRETS_ENABLED`` can also resolve it by name; the
environment binding always wins.
"""

from typing import Annotated

from env._base import BaseEnv
from env._mistral_secrets import WorkspaceSecret


class Env(BaseEnv):
    github_token: Annotated[str | None, WorkspaceSecret()] = None


env = Env()
