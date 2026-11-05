# AGENTS.md — Dreadnought Revival Page

This file is the agent definition for AI coding agents (Vibe Code and any other
agent that reads `AGENTS.md`) working in this repository,
[Dreadnought-Revival-Page](https://github.com/Dreadnought-Revival/Dreadnought-Revival-Page) —
the public website of the Dreadnought Revival project (branch `main`, remote `origin`).

## What this repo is

The project website for Dreadnought Revival, a community-operated private server for the
discontinued game Dreadnought (UE4, Steam App 835860): unmodified game client, everything
emulated server-side, one replacement launcher. Sibling repositories:

- **Server**: https://github.com/Dreadnought-Revival/Dreadnought-Revival-server — backend services, battle-server mod, docs (content source for the About section)
- **Launcher**: https://github.com/Dreadnought-Revival/Dreadnought-Revival-Launcher — the only thing a player installs; link its releases for downloads

## Stack and layout

Plain static HTML/CSS/JS site. **No build step, no framework, no dependencies** — GitHub
Pages serves the repo root as-is. The one exception is `workflow/`, the Mistral Studio
workflow project (see below); it is stripped from the Pages artifact before upload and
never ships to the site.

```
index.html      one-page HUD landing: full-height hero, then tabbed panels behind an
                ARIA tablist in the header nav (Briefing / Systems / Fleet / Patch
                Notes / Roadmap / Community), 31-ship gallery grouped by class, footer
styles.css      dark space-combat HUD theme (void bg, amber/cyan accents, clipped
                panels/buttons, tab bar, grid + scanline overlays, reveal-on-scroll)
app.js          ARIA tabs + hash routing (arrow-key support), burger nav, reveal,
                server-status badge, patch-notes rendering (fetches data/),
                gallery lightbox, copy button
404.html        custom not-found page (same theme)
assets/         logo.svg, favicon.svg, og-image.png (social preview); ship art is
                fetched at deploy time (see below) — assets/market-images/ is NOT in the repo
data/           patch-notes.json (player-facing notes — see below), server-status.json (optional)
workflow/       Mistral Studio workflow project: revival-patch-notes (see below)
.github/workflows/  ci.yml, deploy-pages.yml, workflow-ci.yml
```

The tabs are real ARIA tabs: the header nav is a `tablist`, each panel is a
`role="tabpanel"` section under the hero, `hidden` except the active one. Hash
fragments (`#gallery`, `#community`, …) deep-link the tabs, including the hero CTAs
and footer links. With JavaScript disabled, a `<noscript>` style block shows every
panel stacked, so all content stays reachable.

### Ship art (deploy-time fetch)

The hero and the fleet gallery use the game's own ship images. They are binary game
data (cannot round-trip through text-only tooling and must not be committed by hand),
so `deploy-pages.yml` fetches a pinned list of 31 images from the old
`darkace1998/Dreadnought-Revival-project` repo (pinned commit SHA) into
`assets/market-images/` during every Pages build, after stripping `workflow/` and
before validation. The fetch uses `--fail` and `test -s`, so a broken upstream fails
the Deploy Pages run on purpose. To change the image set: update the gallery
(`index.html`), the fetch list (`deploy-pages.yml`) and the raw-URL source together.

## Working rules

- **Never hand-edit `data/patch-notes.json`.** The notes are player-facing: dated
  batches, one section per game mode or area (Team Deathmatch, Team Elimination,
  Conquest, Onslaught, Ceres Awakens, Proving Grounds, Havoc, Turbo TDM, or
  Launcher / Hangar / Market / Tech tree / General), "Before, ..." context lines,
  and a "Known issues / please report" closer. No internals: no hashes, file names,
  function names or log lines. New notes are generated automatically (see the
  patch-notes automation section below); to change the format, change the prompt in
  `workflow/apps/worker/src/worker/workflows/patch_notes.py` and the renderer in
  `app.js`, not the data file.
- Keep the site dependency-free and responsive from day one; test locally with
  `python3 -m http.server` before pushing.
- Content rules: describe the project exactly as the server repo README does (unmodified
  client, server-side emulation, launcher-only install); always link to the server and
  launcher repositories; keep the disclaimer (not affiliated with Greybox/Yager).
- Server status is a static badge by default. `app.js` upgrades it if
  `data/server-status.json` exists (`{"online": true, "players": 12, "updated_at": "..."}`);
  do not invent a live-status backend.
- Validate before pushing: `python3 -m json.tool data/patch-notes.json`, and the checks
  in `.github/workflows/ci.yml` (file presence, no files over 10M).
- Deployment is GitHub Pages with **Source: GitHub Actions** (Settings → Pages);
  `.github/workflows/deploy-pages.yml` uploads the repo root (minus `workflow/`) on
  every push to `main`. Do not add a build/deploy pipeline for a framework — there is
  no build step for the site.
- Patch-notes updates land on `main` through the normal PR flow; that push triggers
  the Pages deploy, so the site updates itself. Do not add `[skip ci]` to those
  commits.
- Every workflow has an `alert-on-failure` job: a failed run opens a deduplicated
  `[workflow failure] <workflow name>` tracking issue (repeated failures comment on the
  open one). If you cause a failure, diagnose it, fix it, and close the issue once the
  workflow passes again. CI alerts fire only for pushes to `main`, not for PR checks.
- Commit style: short imperative subject, lowercase, like the existing history
  (`Add .gitignore and basic CI workflow`). Work on a `vibe/<slug>-fa133d` branch and
  open a draft PR; push to `main` only via PR merge.

## Patch-notes automation (Mistral Studio workflow)

`workflow/` is a Mistral Workflows (Python/uv) project deployed as the managed
deployment `revival-ops` on Mistral Cloud. Its single workflow:

- **`revival-patch-notes`** — started by a GitHub webhook trigger when commits are
  pushed to `Dreadnought-Revival-server` (default branch only, other events and repos
  are ignored in code; the trigger filter also enforces `event_type == 'push'`).
  It turns the push's commit subjects into a player-facing notes batch with
  `mistral-medium-latest`, merges it into `data/patch-notes.json` (same-day pushes
  merge into that day's entry), and opens a PR like `Patch notes <date>: N commit(s)`.
  It never merges the PR itself: the daily Vibe ops run reviews and merges it, and
  the Pages deploy follows.

How to work on it:

- Code: `workflow/apps/worker/src/worker/workflows/` (`patch_notes.py` is the workflow,
  `notes_format.py` the stdlib-only formatting helpers, `github_rest.py` the stdlib
  GitHub REST client). The Workflows SDK docs are at
  https://docs.mistral.ai/studio/workflows (start with "build your first workflow"
  and "connectors in workflows").
- Tests: `workflow/apps/worker/tests/` — pure-logic tests plus SDK tests with the
  GitHub/model activities faked. `bash tools/uv.sh sync --all-packages` then
  `bash tools/uv.sh run --all-packages pytest apps/worker/tests -q` from `workflow/`.
  GitHub Actions runs them on every change under `workflow/` (workflow-ci.yml).
- The Docker build resolves dependencies at build time (no committed `uv.lock`); keep
  it that way unless you also start committing a lockfile.
- The deployment is unattended: it authenticates GitHub with a fine-grained PAT
  (read/write Contents and Pull requests on the page repo) stored as the workspace
  secret `github_token` (https://console.mistral.ai/secrets) and bound to the
  `GITHUB_TOKEN` environment variable on the `revival-ops` deployment, reaching
  GitHub through `github_rest.py` instead of the OAuth connector (whose
  workspace-shared credential this workspace does not offer). Model calls
  authenticate through the worker identity. Never enable `on_behalf_of` on this
  workflow.
- After merging changes to `workflow/`, redeploy the `revival-ops` deployment
  (Mistral Studio, or ask the Vibe agent), keeping the `github_token` → `GITHUB_TOKEN`
  secret binding, so the running worker picks them up.
