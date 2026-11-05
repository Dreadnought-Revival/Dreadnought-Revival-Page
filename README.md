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
data/           patch-notes.json (generated), server-status.json (optional)
scripts/        update_patch_notes.py — patch-notes generator
assets/         logo, favicon, social preview image
```

## Local preview

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Automation

- `.github/workflows/deploy-pages.yml` — deploys the site to GitHub Pages on every push to `main`.
- `.github/workflows/update-patch-notes.yml` — hourly (and on demand) regenerates
  `data/patch-notes.json` from commits in
  [Dreadnought-Revival-server](https://github.com/Dreadnought-Revival/Dreadnought-Revival-server)
  and [Dreadnought-Revival-Launcher](https://github.com/Dreadnought-Revival/Dreadnought-Revival-Launcher),
  commits the change to `main`, which re-triggers the deploy. Never hand-edit the JSON —
  change `scripts/update_patch_notes.py` instead. Trigger manually:
  `gh workflow run "Update patch notes" --repo Dreadnought-Revival/Dreadnought-Revival-Page`.

## Agents

`AGENTS.md` defines how AI coding agents work in this repository (stack, layout,
generated files, commit and PR conventions).
