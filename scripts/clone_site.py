#!/usr/bin/env python3
"""
clone_site.py — Mirror a static/WordPress informational site for Next.js serving.

Usage:
  python3 clone_site.py <url> --discover
  python3 clone_site.py <url> [--pages /p1 /p2 ...] [--output ./] [--no-browser]

By default uses a real Chromium browser (via Playwright) to fully render each page —
scrolling to trigger lazy-loads and waiting for AJAX — before extracting HTML.
Pass --no-browser to fall back to the fast but JS-blind requests mode.
"""
import sys
import os
import re
import json
import time
import argparse
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path


def ensure_deps(browser_mode: bool):
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        missing.append("beautifulsoup4")

    if missing:
        import subprocess
        print(f"Installing {', '.join(missing)}...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + missing + ["-q"]
        )

    if browser_mode:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            import subprocess
            print("Installing playwright...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "playwright", "-q"]
            )
            print("Installing Chromium...")
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"]
            )


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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
    def __init__(self, base_url: str, output_dir: str = ".", max_pages: int = 60,
                 browser_mode: bool = True):
        self.base_url = base_url.rstrip("/")
        self.parsed_base = urlparse(self.base_url)
        self.base_domain = self.parsed_base.netloc
        self.output_dir = Path(output_dir).resolve()
        self.max_pages = max_pages
        self.browser_mode = browser_mode

        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA

        self.asset_map: dict[str, str] = {}
        self.used_filenames: dict[str, int] = {}

        self._playwright = None
        self._browser = None
        self._page = None

    # ── Browser lifecycle ─────────────────────────────────────────────────────

    def _start_browser(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        ctx = self._browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        self._page = ctx.new_page()
        print("  [browser] Chromium started")

    def _stop_browser(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _render_page(self, url: str) -> str | None:
        """Navigate, scroll to trigger all lazy-loads/AJAX, return rendered HTML."""
        page = self._page
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as exc:
            print(f"    ✗ Browser navigation failed: {exc}")
            return None

        # Smooth scroll to bottom in steps to trigger IntersectionObserver + lazy loaders
        page.evaluate("""
            async () => {
                await new Promise(resolve => {
                    const step = 400;
                    let pos = 0;
                    const tick = setInterval(() => {
                        window.scrollBy(0, step);
                        pos += step;
                        if (pos >= document.body.scrollHeight) {
                            clearInterval(tick);
                            resolve();
                        }
                    }, 120);
                });
            }
        """)

        # Wait for any AJAX triggered by scroll (network settle)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        time.sleep(0.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.3)

        return page.content()

    # ── URL utilities ─────────────────────────────────────────────────────────

    def abs_url(self, href: str, page_url: str) -> str:
        href = href.strip()
        if href.startswith("//"):
            return f"{self.parsed_base.scheme}:{href}"
        return urljoin(page_url, href)

    def is_internal(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == "" or parsed.netloc == self.base_domain

    def url_to_route(self, url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        base_path = self.parsed_base.path.rstrip("/")
        if base_path and path.startswith(base_path):
            path = path[len(base_path):]
        return path.lstrip("/")

    def route_to_slug(self, route: str) -> str:
        if not route:
            return "index"
        return re.sub(r"[^a-zA-Z0-9가-힣]+", "-", route).strip("-") or "index"

    def unique_filename(self, subdir: str, filename: str) -> str:
        key = f"{subdir}/{filename}"
        stem, ext = os.path.splitext(filename)
        count = self.used_filenames.get(key, 0)
        self.used_filenames[key] = count + 1
        if count == 0:
            return filename
        return f"{stem}_{count}{ext}"

    # ── Asset downloading ─────────────────────────────────────────────────────

    def fetch_asset(self, url: str) -> str | None:
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
            self.asset_map[url] = url
            return url

        self.asset_map[url] = web_path
        return web_path

    # ── HTML processing ───────────────────────────────────────────────────────

    def rewrite_html(self, html: str, page_url: str) -> str:
        """Download all referenced assets and rewrite URLs; fix internal hrefs."""
        soup = BeautifulSoup(html, "html.parser")

        # <link rel="stylesheet">
        for tag in soup.find_all("link", rel=lambda v: v and "stylesheet" in v):
            href = tag.get("href", "")
            if not href or href.startswith("data:"):
                continue
            new = self.fetch_asset(self.abs_url(href, page_url))
            if new:
                tag["href"] = new

        # <script src>
        for tag in soup.find_all("script", src=True):
            src = tag["src"]
            if src.startswith("data:"):
                continue
            new = self.fetch_asset(self.abs_url(src, page_url))
            if new:
                tag["src"] = new

        # <img src> and <source src> — in browser mode src is already the real URL
        for tag in soup.find_all(["img", "source"], src=True):
            src = tag["src"]
            if src.startswith("data:"):
                continue
            new = self.fetch_asset(self.abs_url(src, page_url))
            if new:
                tag["src"] = new

        # data-src / data-lazy-src (residual lazy attrs the JS didn't yet swap)
        for tag in soup.find_all(True):
            for attr in list(tag.attrs):
                if re.match(r"data-(src|lazy-src|lazy|original)$", attr):
                    val = tag[attr]
                    if isinstance(val, str) and not val.startswith("data:"):
                        new = self.fetch_asset(self.abs_url(val, page_url))
                        if new:
                            tag[attr] = new

        # favicon / apple-touch-icon
        for tag in soup.find_all("link", href=True):
            rel = tag.get("rel", [])
            if any(r in ("icon", "apple-touch-icon", "shortcut icon") for r in rel):
                href = tag["href"]
                if href.startswith("data:"):
                    continue
                new = self.fetch_asset(self.abs_url(href, page_url))
                if new:
                    tag["href"] = new

        # Internal <a href> → local routes
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or any(href.startswith(s) for s in SKIP_SCHEMES):
                continue
            abs = self.abs_url(href, page_url)
            if self.is_internal(abs):
                route = self.url_to_route(abs)
                tag["href"] = f"/{route}" if route else "/"

        return str(soup)

    # ── Page fetching ─────────────────────────────────────────────────────────

    def fetch_html(self, url: str) -> str | None:
        """Get page HTML — via browser (rendered) or requests (raw)."""
        if self.browser_mode:
            return self._render_page(url)

        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("Content-Type", ""):
                return None
            return resp.text
        except Exception as exc:
            print(f"    ✗ Fetch failed: {exc}")
            return None

    def clone_page(self, url: str, slug: str) -> str | None:
        print(f"\n  → {url}")
        html = self.fetch_html(url)
        if not html:
            return None

        html = self.rewrite_html(html, url)

        pages_dir = self.output_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        filename = f"{slug}.html" if slug else "index.html"
        (pages_dir / filename).write_text(html, encoding="utf-8")
        print(f"    Saved → pages/{filename}")
        return filename

    # ── Discovery (always uses requests — faster, links are in static HTML) ───

    def discover_pages(self, max_depth: int = 2) -> list[dict]:
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

        print(f"\nCloning {len(discovered)} page(s)"
              f" [{'browser' if self.browser_mode else 'requests'} mode]...\n")

        if self.browser_mode:
            self._start_browser()

        try:
            results = []
            for page in discovered:
                route = page["route"]
                slug = self.route_to_slug(route)
                filename = self.clone_page(page["url"], slug)
                if filename:
                    results.append({"route": route, "slug": slug, "filename": filename})
        finally:
            if self.browser_mode:
                self._stop_browser()

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
    parser.add_argument("--no-browser", action="store_true",
                        help="Use plain requests instead of Playwright (faster but misses JS-rendered content)")
    args = parser.parse_args()

    browser_mode = not args.no_browser
    ensure_deps(browser_mode)

    cloner = SiteCloner(args.url, args.output, args.max_pages, browser_mode=browser_mode)

    if args.discover:
        pages = cloner.discover_pages()
        print(f"\n{len(pages)} page(s) found:")
        for p in pages:
            print(f"  /{p['route']}")
    else:
        cloner.run(args.pages)


if __name__ == "__main__":
    main()
