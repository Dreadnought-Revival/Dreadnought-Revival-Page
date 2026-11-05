# Dreadnought-Revival-Page

The website of the [Dreadnought Revival](https://github.com/Dreadnought-Revival) project —
a community-operated private server for the discontinued game **Dreadnought**
(unmodified game client, everything emulated server-side, one replacement launcher).

Live site: deployed with GitHub Pages from `main` (Source: GitHub Actions) →
https://dreadnought-revival.github.io/Dreadnought-Revival-Page/

## Stack

Plain static HTML/CSS/JS — no build step, no dependencies. Pages serves the repo root.

```
index.html      single page (about, how to join, status, patch notes, community)
styles.css      dark space-combat theme
app.js          nav toggle, status badge, patch-notes rendering
data/           patch-notes.json (player-facing notes, written by the AI agent), server-status.json (optional)
assets/         logo, favicon, social preview image
```

## Local preview

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Automation

- `.github/workflows/deploy-pages.yml` — deploys the site to GitHub Pages on every push to `main`.
- Patch notes are written for players by the project's AI agent — dated batches,
  sectioned by game mode or area, no internals — from new commits in
  [Dreadnought-Revival-server](https://github.com/Dreadnought-Revival/Dreadnought-Revival-server)
  and [Dreadnought-Revival-Launcher](https://github.com/Dreadnought-Revival/Dreadnought-Revival-Launcher).
  Never hand-edit `data/patch-notes.json`; notes go live through the normal PR flow.

## Agents

`AGENTS.md` defines how AI coding agents work in this repository (stack, layout,
generated files, commit and PR conventions).
