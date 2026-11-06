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
index.html      one-page landing: two-row header (centred brand row, then the tab bar),
                hero (one primary Download button, secondary links, four HUD step
                cards), three overview banners (ship art + text), then tabbed panels behind
                an ARIA tablist in the header nav (Play / Status / Game Modes / Patch
                Notes / Fleet / Roadmap / Contribute / Support), 31-ship gallery
                grouped by class, footer
styles.css      dark HUD theme after the original game site's visual language: Teko
                headings, cyan on dotted dark-teal panels, thin HUD lines and a tick
                ruler, orange-red buttons with a corner mark (no original logo or
                copy); IBM Plex Sans/Mono for text; reveal-on-scroll
app.js          ARIA tabs + hash routing (arrow-key support), burger nav, reveal,
                server-status badge, patch-notes rendering (fetches data/),
                gallery lightbox
404.html        custom not-found page (same theme)
assets/         the maintainer's asset library: dreadnought-logo_small/_highres.png
                (Dreadnought Revival logo, header), dn_favicon.png + DNfavicon.png (favicon,
                touch icon, compact header), dn_development-logo-beta.png (BETA badge),
                button*.png / btn-submit-gray.png (button images, used as CSS border
                images: orange primary, aqua secondary, grey); dreadnought.png (the plain
                game logo) is deliberately unused; og-image.png (social preview);
                logo.svg / favicon.svg (older marks, unused). Ship art is fetched at
                deploy time (see below) — assets/market-images/ is NOT in the repo
data/           patch-notes.json (player-facing notes — see below), supporters.txt (Patreon
                supporters, hand-edited), server-status.json (optional)
workflow/       Mistral Studio workflow project: revival-patch-notes (see below)
.github/workflows/  ci.yml, deploy-pages.yml, workflow-ci.yml
```

The tabs are real ARIA tabs: the header nav is a `tablist`, each panel is a
`role="tabpanel"` section under the hero, `hidden` except the active one. Hash
fragments (`#play`, `#gallery`, …) deep-link the tabs, including the hero links and
footer links; the ids from before the November 2026 reorganisation (`#briefing`,
`#systems`, `#community`) are aliased in `app.js`, so old links still land. Play is
the default tab. With JavaScript disabled, a `<noscript>` style block shows every
panel stacked, so all content stays reachable.

### Ship art (deploy-time fetch)

The hero, the overview banners and the fleet gallery use the game's own ship images. They are binary game
data (cannot round-trip through text-only tooling and must not be committed by hand),
so `deploy-pages.yml` fetches a pinned list of 31 images from the old
`darkace1998/Dreadnought-Revival-project` repo (pinned commit SHA) into
`assets/market-images/` during every Pages build, after stripping `workflow/` and
before validation. The fetch uses `--fail` and `test -s`, so a broken upstream fails
the Deploy Pages run on purpose. To change the image set: update the gallery
(`index.html`), the fetch list (`deploy-pages.yml`) and the raw-URL source together.

## Working rules

- **Never hand-edit `data/patch-notes.json`** (the one exception is an
  operator-requested rework, landed like any other PR). The notes are
  player-facing: dated batches, one section per game mode or area (Team
  Deathmatch, Team Elimination, Conquest, Onslaught, Ceres Awakens, Proving
  Grounds, Havoc, Turbo TDM, Escalation, All game modes, or Launcher / Hangar /
  Market / Tech tree / Social / General), each change under the game mode it
  actually affects, \"Before, ...\" context lines, and no known-issues closer —
  issue reporting lives in the site's link to the server's GitHub issues. No
  internals: no hashes, file names, function names or log lines. The
  format is defined by the server repo's patch-notes skill
  (`.claude/skills/dreadnought-patch-notes/` in Dreadnought-Revival-server):
  its commits end with a `Patch notes:` block of player-worded lines
  (`Patch notes: none (internal)` marks a commit as internal, which is dropped).
  New notes are generated automatically (see the patch-notes automation section
  below); to change the format, change the prompt in
  `workflow/apps/worker/src/worker/workflows/notes_format.py` and the renderer in
  `app.js`, not the data file.
- Keep the site dependency-free and responsive from day one; test locally with
  `python3 -m http.server` before pushing.
- Content rules: describe the project exactly as the server repo README does (unmodified
  client, server-side emulation, launcher-only install); always link to the server and
  launcher repositories; keep the disclaimer (not affiliated with Greybox/Yager).
- The Discord invite is https://discord.gg/dreadnought (header icon, Play tab card,
  hero links, Contribute, Support, footer). The Support tab and the footer link the
  maintainer's Patreon, https://www.patreon.com/cw/DARKACE39. Download buttons use GitHub's
  `releases/latest/download/<asset>` links, so they follow every launcher release
  as long as the asset names (`Dreadnought-Revival.exe`,
  `Dreadnought-Revival-linux.tar.gz`) stay the same.
- The panel at the top of the Patch Notes tab links to the server repo's issue
  tracker and must keep pointing at
  https://github.com/Dreadnought-Revival/Dreadnought-Revival-server/issues.
  Patch-notes batches themselves carry no "Known issues" section.
- `data/supporters.txt` is the Patreon supporters list on the Support tab, edited by
  hand by the maintainer: one name per line, `## Tier` starts a group, `//` lines are
  comments. `app.js` escapes every name. Only list people who agreed to be named; never
  add names yourself.
- Server status is a static badge by default ("Public Test Server Live"). `app.js` upgrades it if
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
  It reads each commit's `Patch notes:` block (the convention set by the server
  repo's patch-notes skill): those lines are the source of truth, commits marked
  `none (internal)` are dropped, and block-less (pre-convention) commits are
  phrased for players by `mistral-medium-latest`. Every block line's named
  section must survive into the batch (`notes_format.validate_block_coverage`):
  a dropped line fails the run, so the trigger retries instead of the site
  shipping incomplete notes. The batch is ordered by the
  skill's section list (game modes first, then All game modes, Launcher / Hangar /
  Market / Tech tree / Social, General), with each change under the game mode it
  actually affects and no known-issues closer, merged into
  `data/patch-notes.json` (same-day pushes merge into that
  day's entry), and opens a PR like `Patch notes <date>: N commit(s)`.
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
