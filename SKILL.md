---
name: clone-to-nextjs
description: |
  Mirror any simple informational website (hospital, clinic, restaurant, portfolio, corporate intro, etc.) directly into a Next.js App Router project — no recoding needed. Downloads raw HTML/CSS/JS/images and auto-generates route.ts handlers that serve each page file directly. Use when the user says things like "사이트 그대로 복사해서 Next.js로 만들어줘", "이 병원 사이트 가져와서 배포하고 싶어", "clone this website to Next.js", "copy this site without recoding", "HTML 그대로 가져와서 서빙해줘", "기존 사이트 Next.js로 옮겨줘", or "mirror a website". Proactively suggest this skill when the user has already downloaded HTML pages from another site and wants to serve them through Next.js, or when they want to take over an existing static/WordPress site without rebuilding from scratch.
---

# Clone to Next.js

Takes any simple informational website and turns it into a deployable Next.js App Router project by serving the raw HTML/CSS/JS files directly — no React components, no re-styling.

## How it works

The pattern is deliberately simple:
- **`pages/*.html`** — one HTML file per page (downloaded as-is from the original site)
- **`public/css|js|images|fonts/`** — all static assets (served by Next.js at root automatically)
- **`app/*/route.ts`** — one GET handler per page that reads the HTML file and returns it

Each route handler is just:
```ts
import { readFileSync } from "fs";
import path from "path";

export function GET() {
  const html = readFileSync(path.join(process.cwd(), "pages/about.html"), "utf-8");
  return new Response(html, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
```

## Scripts in this skill

| Script | Purpose |
|--------|---------|
| `scripts/clone_site.py` | Crawls a URL, renders each page in a real browser (Playwright), downloads all assets, rewrites links |
| `scripts/setup_nextjs.py` | Reads `clone-manifest.json`, generates all `route.ts` files and `next.config.ts` |

### clone_site.py — browser mode (default)

By default the crawler launches headless Chromium via Playwright and **scrolls each page to the bottom** before saving HTML. This ensures:
- Lazy-loaded images (`data-src`) are already swapped into `src` by the time HTML is captured
- AJAX-driven sections (Elementor carousels, WordPress post grids) are fully rendered
- Scroll-triggered animations have fired

Pass `--no-browser` to fall back to the old fast-but-JS-blind `requests` mode (good for simple static sites).

The harness sets `${CLAUDE_SKILL_DIR}` automatically — use it directly:

---

## Step 0 — Determine the output directory (ALWAYS do this first)

**Never write into the current working directory without explicit confirmation.**

Determine the output folder using this priority:

1. **User already specified a folder** → use it
2. **Cloning from a URL** → derive from domain: `sominclinic` from `sominclinic.com`
3. **Existing pages/ already in a specific folder the user pointed to** → use that folder
4. **Otherwise** → ask the user:
   > "어느 폴더에 Next.js 프로젝트를 만들까요? (기본값: `./sominclinic-nextjs`)"

Then create the folder if it doesn't exist:
```bash
OUTPUT_DIR="./sominclinic-nextjs"   # replace with actual chosen name
mkdir -p "$OUTPUT_DIR"
```

All subsequent steps use `$OUTPUT_DIR` as the project root.

---

## Workflow

### Case A: Pages already downloaded (user has pages/ and public/ somewhere)

If the user says files are already in a folder, confirm:
- Which folder are the `pages/` and `public/` files in?
- Should those files be moved into a new project folder, or is that folder already the project?

Then run setup:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_nextjs.py" "$OUTPUT_DIR"
```

If `clone-manifest.json` doesn't exist yet (files were downloaded manually), generate it first:
```bash
python3 - <<'EOF'
import json
from pathlib import Path
import sys

output_dir = sys.argv[1] if len(sys.argv) > 1 else "."
pages = []
for f in sorted((Path(output_dir) / "pages").glob("*.html")):
    slug = f.stem
    route = "" if slug == "index" else slug
    pages.append({"route": route, "slug": slug, "filename": f.name})

manifest = {"base_url": "unknown", "pages": pages}
(Path(output_dir) / "clone-manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Manifest created: {len(pages)} pages")
for p in pages:
    print(f"  /{p['route']} → pages/{p['filename']}")
EOF
python3 /dev/stdin "$OUTPUT_DIR"
```

Then generate routes:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_nextjs.py" "$OUTPUT_DIR"
```

---

### Case B: Starting fresh from a URL

#### Step 1 — Determine output folder

Derive from the URL domain (e.g., `https://sominclinic.com` → `sominclinic`). Confirm with the user or use the derived name:

```bash
OUTPUT_DIR="./sominclinic"
mkdir -p "$OUTPUT_DIR"
```

#### Step 2 — Discover pages

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clone_site.py" "https://example.com" --discover
```

Show the list to the user and confirm which pages to include (or all of them).

#### Step 3 — Clone the site

**All discovered pages (browser mode — recommended for WordPress/Elementor sites):**
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clone_site.py" "https://example.com" --output "$OUTPUT_DIR"
```

**Specific pages only:**
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clone_site.py" "https://example.com" \
  --pages / /about /location /process \
  --output "$OUTPUT_DIR"
```

**Fast mode for simple static sites (no JS rendering):**
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clone_site.py" "https://example.com" --output "$OUTPUT_DIR" --no-browser
```

The script produces inside `$OUTPUT_DIR`:
```
pages/
  index.html         ← root /
  about.html         ← /about
  location.html      ← /location
public/
  css/...
  js/...
  images/...
  fonts/...
clone-manifest.json
```

#### Step 4 — Generate routes

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/setup_nextjs.py" "$OUTPUT_DIR"
```

Produces `app/*/route.ts` for every page and `next.config.ts` with cache headers.

#### Step 5 — Initialize Next.js (if not already set up)

If there's no `package.json` yet:
```bash
cd "$OUTPUT_DIR"
npm init -y
npm install next react react-dom
npm install -D typescript @types/react @types/node
```

Add to `package.json`:
```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start"
}
```

Also create `tsconfig.json`:
```bash
npx tsc --init --target ES2017 --lib dom,es2017 --jsx preserve \
  --moduleResolution bundler --allowImportingTsExtensions --noEmit
```

#### Step 6 — Verify

```bash
cd "$OUTPUT_DIR" && npm run dev
```

Open each page and check: styles load, images show, internal links work.

---

## URL rewriting (what the crawler does automatically)

| Before | After |
|--------|-------|
| `https://original.com/about/` | `/about` |
| `https://original.com/wp-content/themes/x/style.css` | `/css/style.css` |
| `https://original.com/wp-content/uploads/img.jpg` | `/images/img.jpg` |
| External links, mailto:, tel: | Unchanged |

---

## Troubleshooting

**Styles missing?** CSS files sometimes import other CSS via `@import`. Download those manually and put in `public/css/`.

**Images missing?** Inline CSS `background-image: url(...)` isn't parsed by the crawler. Fix manually by downloading images and updating the CSS file.

**WordPress forms/comments don't work?** Expected — those require the original PHP backend. Only the HTML display is cloned.

**JS-heavy / SPA site shows blank page?** The crawler downloads raw HTML, not rendered output. Use `/gstack` with Playwright to capture rendered HTML first.

**Duplicate asset filenames from different paths?** The crawler uses only the basename. If two assets share a name (e.g., two `style.css` from different plugins), the second overwrites the first. Check `public/css/` after cloning and manually rename duplicates if needed.

**Internal links still pointing to original domain?** The HTML rewriter catches `<a href>` tags. If some escaped through (rare), do a manual find-replace in the HTML file.
