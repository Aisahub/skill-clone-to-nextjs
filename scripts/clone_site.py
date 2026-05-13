#!/usr/bin/env python3
"""
clone_site.py — Mirror a static/WordPress informational site for Next.js serving.

Usage:
  python3 clone_site.py <url> --discover
  python3 clone_site.py <url> [--pages /p1 /p2 ...] [--output ./]
"""
import sys
import os
import re
import json
import argparse
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path


def ensure_deps():
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        import subprocess
        print("Installing requests and beautifulsoup4...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "-q"]
        )

ensure_deps()

import requests
from bs4 import BeautifulSoup


ASSET_EXT_MAP = {
    ".css": "css",
    ".js": "js",
    ".jpg": "images", ".jpeg": "images", ".png": "images",
    ".gif": "images", ".svg": "images", ".webp": "images",
    ".ico": "images", ".avif": "images",
    ".woff": "fonts", ".woff2": "fonts",
    ".ttf": "fonts", ".eot": "fonts", ".otf": "fonts",
}

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "#"}


def classify_asset(url: str):
    """Return (subdir, filename) for a public/ asset, or (None, None) if not an asset."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    subdir = ASSET_EXT_MAP.get(ext)
    if not subdir or not filename:
        return None, None
    return subdir, filename


class SiteCloner:
    def __init__(self, base_url: str, output_dir: str = ".", max_pages: int = 60):
        self.base_url = base_url.rstrip("/")
        self.parsed_base = urlparse(self.base_url)
        self.base_domain = self.parsed_base.netloc
        self.output_dir = Path(output_dir).resolve()
        self.max_pages = max_pages

        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )

        # original_url -> web_path (e.g. "/css/style.css")
        self.asset_map: dict[str, str] = {}
        # track used filenames to avoid overwriting different assets with same basename
        self.used_filenames: dict[str, int] = {}

    # ── URL utilities ──────────────────────────────────────────────────────────

    def abs_url(self, href: str, page_url: str) -> str:
        """Resolve href relative to page_url into an absolute URL."""
        href = href.strip()
        if href.startswith("//"):
            return f"{self.parsed_base.scheme}:{href}"
        return urljoin(page_url, href)

    def is_internal(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == "" or parsed.netloc == self.base_domain

    def url_to_route(self, url: str) -> str:
        """URL path → clean route string (no leading/trailing slash)."""
        path = urlparse(url).path.rstrip("/")
        # strip base path if base_url has one
        base_path = self.parsed_base.path.rstrip("/")
        if base_path and path.startswith(base_path):
            path = path[len(base_path):]
        return path.lstrip("/")

    def route_to_slug(self, route: str) -> str:
        """route → safe filename stem (e.g. "about" or "services-dental")."""
        if not route:
            return "index"
        return re.sub(r"[^a-zA-Z0-9가-힣]+", "-", route).strip("-") or "index"

    def unique_filename(self, subdir: str, filename: str) -> str:
        """Return a filename that doesn't collide with previously used names."""
        key = f"{subdir}/{filename}"
        stem, ext = os.path.splitext(filename)
        count = self.used_filenames.get(key, 0)
        self.used_filenames[key] = count + 1
        if count == 0:
            return filename
        return f"{stem}_{count}{ext}"

    # ── Asset downloading ─────────────────────────────────────────────────────

    def fetch_asset(self, url: str) -> str | None:
        """Download an asset, save to public/, return its web path or None."""
        if url in self.asset_map:
            return self.asset_map[url]

        subdir, filename = classify_asset(url)
        if not subdir:
            return None

        filename = self.unique_filename(subdir, filename)
        dest_dir = self.output_dir / "public" / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        web_path = f"/{subdir}/{filename}"

        try:
            resp = self.session.get(url, timeout=20, stream=True)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            size = dest_path.stat().st_size
            print(f"    ✓ {web_path}  ({size:,} bytes)")
        except Exception as exc:
            print(f"    ✗ {url}  ({exc})")
            self.asset_map[url] = url  # leave original on failure
            return url

        self.asset_map[url] = web_path
        return web_path

    # ── HTML processing ───────────────────────────────────────────────────────

    def rewrite_html(self, html: str, page_url: str) -> str:
        """Download all referenced assets and rewrite their URLs; fix internal hrefs."""
        soup = BeautifulSoup(html, "html.parser")

        # <link rel="stylesheet">
        for tag in soup.find_all("link", rel=lambda v: v and "stylesheet" in v):
            href = tag.get("href", "")
            if not href or href.startswith("data:"):
                continue
            abs = self.abs_url(href, page_url)
            new = self.fetch_asset(abs)
            if new:
                tag["href"] = new

        # <script src>
        for tag in soup.find_all("script", src=True):
            src = tag["src"]
            if src.startswith("data:"):
                continue
            abs = self.abs_url(src, page_url)
            new = self.fetch_asset(abs)
            if new:
                tag["src"] = new

        # <img src>, <source src>
        for tag in soup.find_all(["img", "source"], src=True):
            src = tag["src"]
            if src.startswith("data:"):
                continue
            abs = self.abs_url(src, page_url)
            new = self.fetch_asset(abs)
            if new:
                tag["src"] = new

        # <link rel="icon|apple-touch-icon">
        for tag in soup.find_all("link", href=True):
            if tag.get("rel") and any(r in ("icon", "apple-touch-icon", "shortcut icon")
                                      for r in tag.get("rel", [])):
                href = tag["href"]
                if href.startswith("data:"):
                    continue
                abs = self.abs_url(href, page_url)
                new = self.fetch_asset(abs)
                if new:
                    tag["href"] = new

        # Rewrite internal <a href> to local routes
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or any(href.startswith(s) for s in SKIP_SCHEMES):
                continue
            abs = self.abs_url(href, page_url)
            if self.is_internal(abs):
                route = self.url_to_route(abs)
                tag["href"] = f"/{route}" if route else "/"

        return str(soup)

    # ── Page downloading ──────────────────────────────────────────────────────

    def clone_page(self, url: str, slug: str) -> str | None:
        """Download, rewrite, and save one HTML page. Returns filename or None."""
        print(f"\n  → {url}")
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("Content-Type", ""):
                print("    (not HTML, skipping)")
                return None
        except Exception as exc:
            print(f"    ✗ Fetch failed: {exc}")
            return None

        html = self.rewrite_html(resp.text, url)

        pages_dir = self.output_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        filename = f"{slug}.html" if slug else "index.html"
        out = pages_dir / filename
        out.write_text(html, encoding="utf-8")
        print(f"    Saved → pages/{filename}")
        return filename

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover_pages(self, max_depth: int = 2) -> list[dict]:
        """BFS crawl to find internal HTML pages. Returns list of {url, route}."""
        print(f"Discovering pages at {self.base_url} (max_depth={max_depth})...\n")
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(self.base_url + "/", 0)]
        pages: list[dict] = []

        while queue and len(visited) < self.max_pages:
            url, depth = queue.pop(0)
            canonical = url.rstrip("/")
            if canonical in visited:
                continue
            visited.add(canonical)

            try:
                resp = self.session.get(url, timeout=15)
                ct = resp.headers.get("Content-Type", "")
                if "text/html" not in ct:
                    continue
            except Exception as exc:
                print(f"  ✗ {url}: {exc}")
                continue

            route = self.url_to_route(url)
            pages.append({"url": url, "route": route})
            print(f"  ✓ /{route or ''}")

            if depth < max_depth:
                try:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if not href or any(href.startswith(s) for s in SKIP_SCHEMES):
                            continue
                        abs = self.abs_url(href, url)
                        # only follow same-domain, no query strings or fragments
                        parsed = urlparse(abs)
                        if (self.is_internal(abs)
                                and not parsed.query
                                and not parsed.fragment
                                and abs.rstrip("/") not in visited):
                            queue.append((abs.rstrip("/") + "/", depth + 1))
                except Exception:
                    pass

        return pages

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self, page_routes: list[str] | None = None) -> list[dict]:
        """Clone specified pages (or discover if None). Returns manifest pages list."""
        for d in ["pages", "public/css", "public/js", "public/images", "public/fonts"]:
            (self.output_dir / d).mkdir(parents=True, exist_ok=True)

        if page_routes is None:
            discovered = self.discover_pages()
        else:
            discovered = []
            for r in page_routes:
                route = r.lstrip("/")
                url = self.base_url + ("/" + route if route else "/")
                discovered.append({"url": url, "route": route})

        print(f"\nCloning {len(discovered)} page(s)...\n")
        results = []
        for page in discovered:
            route = page["route"]
            slug = self.route_to_slug(route)
            filename = self.clone_page(page["url"], slug)
            if filename:
                results.append({"route": route, "slug": slug, "filename": filename})

        manifest = {
            "base_url": self.base_url,
            "pages": results,
        }
        manifest_path = self.output_dir / "clone-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

        print(f"\n{'─'*50}")
        print(f"Done. {len(results)} page(s) cloned.")
        print(f"Manifest → {manifest_path}")
        return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mirror a website for Next.js serving")
    parser.add_argument("url", help="Base URL of the site to clone")
    parser.add_argument("--pages", nargs="*", metavar="ROUTE",
                        help="Specific routes to clone (e.g. / /about /location)")
    parser.add_argument("--output", default=".", metavar="DIR",
                        help="Output directory (default: current dir)")
    parser.add_argument("--discover", action="store_true",
                        help="Only discover pages, don't clone")
    parser.add_argument("--max-pages", type=int, default=60)
    args = parser.parse_args()

    cloner = SiteCloner(args.url, args.output, args.max_pages)

    if args.discover:
        pages = cloner.discover_pages()
        print(f"\n{len(pages)} page(s) found:")
        for p in pages:
            print(f"  /{p['route']}")
    else:
        cloner.run(args.pages)


if __name__ == "__main__":
    main()
