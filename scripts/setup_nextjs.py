#!/usr/bin/env python3
"""
setup_nextjs.py — Generate Next.js App Router route.ts files from clone-manifest.json.

Usage:
  python3 setup_nextjs.py [project-dir]
  python3 setup_nextjs.py .           # uses clone-manifest.json in current dir
"""
import json
import sys
from pathlib import Path


ROUTE_TS = """\
import {{ readFileSync }} from "fs";
import path from "path";

export function GET() {{
  const html = readFileSync(path.join(process.cwd(), "pages/{filename}"), "utf-8");
  return new Response(html, {{
    headers: {{ "Content-Type": "text/html; charset=utf-8" }},
  }});
}}
"""

NEXT_CONFIG_TS = """\
import type { NextConfig } from "next";

const config: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      {
        source: "/css/(.*)",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/js/(.*)",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/images/(.*)",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        source: "/fonts/(.*)",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default config;
"""


def build_manifest_from_pages(project: Path) -> dict:
    """Fallback: build manifest by scanning pages/*.html when clone-manifest.json is absent."""
    pages_dir = project / "pages"
    if not pages_dir.exists():
        print("Error: No pages/ directory and no clone-manifest.json found.")
        sys.exit(1)

    html_files = sorted(pages_dir.glob("*.html"))
    if not html_files:
        print("Error: pages/ exists but contains no .html files.")
        sys.exit(1)

    pages = []
    for f in html_files:
        slug = f.stem
        route = "" if slug == "index" else slug
        pages.append({"route": route, "slug": slug, "filename": f.name})

    manifest = {"base_url": "unknown", "pages": pages}
    manifest_path = project / "clone-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"Auto-created clone-manifest.json from pages/ ({len(pages)} files)")
    return manifest


def setup(project_dir: str = ".") -> None:
    project = Path(project_dir).resolve()
    manifest_path = project / "clone-manifest.json"

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = build_manifest_from_pages(project)

    pages = manifest.get("pages", [])
    if not pages:
        print("No pages in manifest. Nothing to do.")
        return

    app_dir = project / "app"
    app_dir.mkdir(exist_ok=True)
    generated = []

    for page in pages:
        route = page["route"].strip("/")
        filename = page["filename"]

        if not route:
            # root page → app/route.ts
            route_file = app_dir / "route.ts"
        else:
            # nested route → app/<slug>/route.ts  (handles multi-segment paths too)
            parts = [p for p in route.split("/") if p]
            route_dir = app_dir.joinpath(*parts)
            route_dir.mkdir(parents=True, exist_ok=True)
            route_file = route_dir / "route.ts"

        content = ROUTE_TS.format(filename=filename)
        route_file.write_text(content)
        rel = route_file.relative_to(project)
        generated.append(str(rel))
        print(f"  ✓ {rel}")

    # next.config.ts — write only if absent
    next_config = project / "next.config.ts"
    if not next_config.exists():
        next_config.write_text(NEXT_CONFIG_TS)
        print(f"  ✓ next.config.ts  (created)")
    else:
        print(f"  – next.config.ts  (already exists, skipped)")

    print(f"\nDone. {len(generated)} route file(s) generated.")
    print("Run 'npm run dev' to start the dev server.")


if __name__ == "__main__":
    project_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    setup(project_dir)
