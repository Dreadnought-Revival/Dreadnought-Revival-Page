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

Plain static HTML/CSS/JS. **No build step, no framework, no dependencies** — GitHub Pages
serves the repo root as-is.

```
index.html      single page: hero, about, how to join, status, patch notes, community
styles.css      dark space-combat theme
app.js          nav toggle, server-status badge, patch-notes rendering (fetches data/)
404.html        custom not-found page
assets/         logo.svg, favicon.svg, og-image.png (social preview)
data/           patch-notes.json (player-facing notes written by the AI agent — see
                below), server-status.json (optional)
.github/workflows/  ci.yml, deploy-pages.yml
```

## Working rules

- **Never hand-edit `data/patch-notes.json`.** The notes are player-facing: dated
  batches, one section per game mode or area (Team Deathmatch, Team Elimination,
  Conquest, Onslaught, Ceres Awakens, Proving Grounds, Havoc, Turbo TDM, or
  Launcher / Hangar / Market / Tech tree / General), “Before, ...” context lines,
  and a “Known issues / please report” closer. No internals: no hashes, file names,
  function names or log lines. They are written by the project's AI agent from new
  commits in the server and launcher repos; to change the format, change the agent's
  patch-notes skill and the renderer in `app.js`, not the data file.
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
  `.github/workflows/deploy-pages.yml` uploads the repo root on every push to `main`.
  Do not add a build/deploy pipeline for a framework — there is no build step.
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
