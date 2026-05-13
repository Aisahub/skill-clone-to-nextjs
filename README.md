# clone-to-nextjs — Claude Code Skill

Mirror any simple informational website (hospital, clinic, restaurant, portfolio, corporate intro) directly into a Next.js App Router project — no recoding needed.

## Install

```bash
git clone https://github.com/Aisahub/skill-clone-to-nextjs ~/.claude/skills/clone-to-nextjs
```

That's it. The skill is available immediately in your next Claude Code session.

## What it does

- **Renders each page in a real Chromium browser** (Playwright) — scrolls to bottom to trigger lazy-loads and AJAX before saving HTML
- Downloads all CSS/JS/images/fonts and rewrites URLs to local paths
- Auto-generates `app/*/route.ts` handlers for each page
- Sets up `next.config.ts` with security headers and asset cache rules
- Works correctly with WordPress/Elementor, lazy-loaded images, and AJAX-driven carousels

## Usage triggers

Say any of the following in Claude Code:

- `"이 병원 사이트 가져와서 배포하고 싶어"`
- `"clone this website to Next.js"`
- `"사이트 그대로 복사해서 Next.js로 만들어줘"`
- `"HTML 그대로 가져와서 서빙해줘"`

Claude will automatically invoke the skill and walk you through the two-step workflow.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/clone_site.py` | Renders pages in Chromium (Playwright), downloads all assets, rewrites links. Use `--no-browser` for fast static-only mode. |
| `scripts/setup_nextjs.py` | Reads `clone-manifest.json`, generates all `route.ts` files |

## How the output looks

```
my-project/
├── pages/
│   ├── index.html
│   ├── about.html
│   └── location.html
├── public/
│   ├── css/
│   ├── js/
│   ├── images/
│   └── fonts/
├── app/
│   ├── route.ts          ← serves pages/index.html
│   ├── about/route.ts    ← serves pages/about.html
│   └── location/route.ts ← serves pages/location.html
├── next.config.ts
└── clone-manifest.json
```

## Uninstall

```bash
rm -rf ~/.claude/skills/clone-to-nextjs
```
