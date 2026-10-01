#!/usr/bin/env python3
"""
sitemap_validator.py - Validate the URLs listed in XML sitemaps.

Accepts a sitemap URL or a local file. Sitemap indexes are followed
recursively and gzipped sitemaps are supported. Every listed URL is
checked and flagged when it:

  * does not return 200
  * redirects (sitemaps should only list final URLs)
  * is noindexed via meta robots or the X-Robots-Tag header
  * canonicalises to a different URL

Usage:
    python scripts/sitemap_validator.py https://example.com/sitemap.xml
    python scripts/sitemap_validator.py ./sitemap.xml -o sitemap_report.csv --limit 500
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
DEFAULT_UA = "Mozilla/5.0 (compatible; SEOSitemapValidator/1.0; +https://example.com/bot)"


def load_xml(source: str, session: requests.Session, timeout: float) -> bytes:
    """Return raw XML bytes from a URL or local path, un-gzipping if needed."""
    if source.startswith(("http://", "https://")):
        resp = session.get(source, timeout=timeout)
        resp.raise_for_status()
        data = resp.content
    else:
        data = Path(source).read_bytes()
    if data[:2] == b"\x1f\x8b":  # gzip magic number
        data = gzip.decompress(data)
    return data


def collect_urls(source: str, session: requests.Session, timeout: float,
                 visited: set[str] | None = None) -> list[tuple[str, str]]:
    """Return (page_url, sitemap_source) pairs, recursing into sitemap indexes."""
    visited = visited if visited is not None else set()
    if source in visited:
        return []
    visited.add(source)

    try:
        root = ET.fromstring(load_xml(source, session, timeout))
    except (requests.RequestException, ET.ParseError, OSError) as exc:
        print(f"  ! Could not read {source}: {exc}", file=sys.stderr)
        return []

    tag = root.tag.split("}")[-1]
    if tag == "sitemapindex":
        pairs: list[tuple[str, str]] = []
        for loc in root.findall("sm:sitemap/sm:loc", NS):
            child = (loc.text or "").strip()
            if child:
                print(f"  -> child sitemap {child}")
                pairs.extend(collect_urls(child, session, timeout, visited))
        return pairs

    return [((loc.text or "").strip(), source)
            for loc in root.findall("sm:url/sm:loc", NS) if (loc.text or "").strip()]


def check_page(url: str, session: requests.Session, timeout: float) -> dict[str, object]:
    """Fetch one sitemap URL without following redirects and inspect it."""
    row: dict[str, object] = {"url": url, "status": "", "redirect_to": "",
                              "meta_robots": "", "x_robots_tag": "", "canonical": "", "issues": ""}
    issues: list[str] = []
    try:
        resp = session.get(url, allow_redirects=False, timeout=timeout)
    except requests.RequestException as exc:
        row.update(status="ERROR", issues=f"Request failed: {exc.__class__.__name__}")
        return row

    row["status"] = resp.status_code
    if 300 <= resp.status_code < 400:
        row["redirect_to"] = urljoin(url, resp.headers.get("Location", ""))
        issues.append("Redirected URL in sitemap")
    elif resp.status_code != 200:
        issues.append(f"Non-200 status ({resp.status_code})")

    x_robots = resp.headers.get("X-Robots-Tag", "")
    row["x_robots_tag"] = x_robots
    if "noindex" in x_robots.lower():
        issues.append("Noindex via X-Robots-Tag")

    if resp.status_code == 200 and "html" in resp.headers.get("Content-Type", "html"):
        soup = BeautifulSoup(resp.text, "html.parser")
        robots = soup.find("meta", attrs={"name": lambda v: v and v.lower() in ("robots", "googlebot")})
        if robots:
            row["meta_robots"] = robots.get("content", "")
            if "noindex" in row["meta_robots"].lower():
                issues.append("Noindex via meta robots")
        canonical = soup.find("link", rel=lambda v: v is not None and v.lower() == "canonical")
        if canonical and canonical.get("href"):
            row["canonical"] = urljoin(url, canonical["href"].strip())
            if row["canonical"].rstrip("/") != url.rstrip("/"):
                issues.append("Canonicalised to another URL")

    row["issues"] = "; ".join(issues)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate URLs listed in XML sitemaps.")
    parser.add_argument("sitemap", help="Sitemap or sitemap index URL, or a local file path")
    parser.add_argument("-o", "--output", default="sitemap_report.csv")
    parser.add_argument("--limit", type=int, default=0, help="Only check the first N URLs (0 = all)")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    args = parser.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent

    print(f"Reading {args.sitemap}")
    pairs = collect_urls(args.sitemap, session, args.timeout)
    # De-duplicate while keeping the first sitemap each URL was found in.
    unique: dict[str, str] = {}
    for url, src in pairs:
        unique.setdefault(url, src)
    duplicates = len(pairs) - len(unique)
    items = list(unique.items())
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("No URLs found.", file=sys.stderr)
        return 1

    print(f"Checking {len(items)} URLs ({duplicates} duplicate entries skipped)")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda pair: check_page(pair[0], session, args.timeout), items))
    for row, (_url, src) in zip(rows, items):
        row["sitemap"] = src

    fields = ["url", "sitemap", "status", "redirect_to", "meta_robots", "x_robots_tag", "canonical", "issues"]
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    flagged = sum(1 for r in rows if r["issues"])
    print(f"Done. {flagged} of {len(rows)} URLs flagged. Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
