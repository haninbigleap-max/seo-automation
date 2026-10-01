#!/usr/bin/env python3
"""
meta_extractor.py - Extract and audit on-page meta elements in bulk.

For every URL it extracts the title, meta description, H1(s), canonical
and robots meta, then flags:

  * missing title / description / H1 / canonical
  * titles or descriptions that are too long or too short
  * multiple H1s
  * duplicate titles, descriptions and H1s across the URL set
  * noindex pages

Usage:
    python scripts/meta_extractor.py urls.txt -o meta_report.csv
    python scripts/meta_extractor.py urls.txt --title-max 60 --desc-max 160
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = "Mozilla/5.0 (compatible; SEOMetaExtractor/1.0; +https://example.com/bot)"


def clean(text: str | None) -> str:
    """Collapse whitespace so lengths and duplicate checks are reliable."""
    return " ".join((text or "").split())


def extract(url: str, session: requests.Session, timeout: float) -> dict[str, object]:
    """Fetch a page and pull out the elements we care about."""
    row: dict[str, object] = {"url": url, "status": "", "final_url": "", "title": "", "title_length": 0,
                              "meta_description": "", "description_length": 0,
                              "h1": "", "h1_count": 0, "canonical": "", "meta_robots": "", "issues": []}
    try:
        resp = session.get(url, timeout=timeout)
    except requests.RequestException as exc:
        row["status"] = "ERROR"
        row["issues"].append(f"Request failed: {exc.__class__.__name__}")
        return row

    row["status"] = resp.status_code
    row["final_url"] = resp.url
    if resp.history:
        # requests followed one or more redirects to reach this page.
        row["issues"].append(f"Redirected ({resp.history[0].status_code}) to {resp.url}")
    if resp.status_code != 200:
        row["issues"].append(f"Status {resp.status_code}")
        return row

    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("title")
    row["title"] = clean(title_tag.get_text()) if title_tag else ""

    desc = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    row["meta_description"] = clean(desc.get("content")) if desc else ""

    h1s = [clean(h.get_text()) for h in soup.find_all("h1")]
    row["h1_count"] = len(h1s)
    row["h1"] = " | ".join(h1s)

    canonical = soup.find("link", rel=lambda v: v is not None and v.lower() == "canonical")
    row["canonical"] = urljoin(resp.url, canonical["href"].strip()) if canonical and canonical.get("href") else ""

    robots = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "robots"})
    row["meta_robots"] = clean(robots.get("content")) if robots else ""

    row["title_length"] = len(row["title"])
    row["description_length"] = len(row["meta_description"])
    return row


def add_flags(rows: list[dict[str, object]], args: argparse.Namespace) -> None:
    """Add per-page and cross-page (duplicate) issues to each row."""
    ok_rows = [r for r in rows if r["status"] == 200]
    # Count each final page once, so a redirect is not reported as a duplicate of its target.
    unique_pages = list({r["final_url"]: r for r in ok_rows}.values())
    title_counts = Counter(r["title"].lower() for r in unique_pages if r["title"])
    desc_counts = Counter(r["meta_description"].lower() for r in unique_pages if r["meta_description"])
    h1_counts = Counter(r["h1"].lower() for r in unique_pages if r["h1"])

    for r in ok_rows:
        issues: list[str] = r["issues"]
        # Title
        if not r["title"]:
            issues.append("Missing title")
        elif r["title_length"] > args.title_max:
            issues.append(f"Title too long (>{args.title_max})")
        elif r["title_length"] < args.title_min:
            issues.append(f"Title too short (<{args.title_min})")
        if r["title"] and title_counts[r["title"].lower()] > 1:
            issues.append("Duplicate title")
        # Meta description
        if not r["meta_description"]:
            issues.append("Missing meta description")
        elif r["description_length"] > args.desc_max:
            issues.append(f"Description too long (>{args.desc_max})")
        elif r["description_length"] < args.desc_min:
            issues.append(f"Description too short (<{args.desc_min})")
        if r["meta_description"] and desc_counts[r["meta_description"].lower()] > 1:
            issues.append("Duplicate meta description")
        # H1
        if r["h1_count"] == 0:
            issues.append("Missing H1")
        elif r["h1_count"] > 1:
            issues.append("Multiple H1s")
        if r["h1"] and h1_counts[r["h1"].lower()] > 1:
            issues.append("Duplicate H1")
        # Canonical and robots
        if not r["canonical"]:
            issues.append("Missing canonical")
        elif r["canonical"].rstrip("/") != str(r["final_url"]).rstrip("/"):
            issues.append("Canonical points elsewhere")
        if "noindex" in str(r["meta_robots"]).lower():
            issues.append("Noindex")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and audit titles, descriptions, H1s, canonicals and robots meta.")
    parser.add_argument("input", help="Text file with one URL per line")
    parser.add_argument("-o", "--output", default="meta_report.csv")
    parser.add_argument("--title-min", type=int, default=30)
    parser.add_argument("--title-max", type=int, default=60)
    parser.add_argument("--desc-min", type=int, default=70)
    parser.add_argument("--desc-max", type=int, default=160)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        urls = list(dict.fromkeys(l.strip() for l in fh if l.strip() and not l.startswith("#")))
    if not urls:
        print("No URLs found in input file.", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda u: extract(u, session, args.timeout), urls))

    add_flags(rows, args)

    fields = ["url", "status", "final_url", "title", "title_length", "meta_description", "description_length",
              "h1", "h1_count", "canonical", "meta_robots", "issues"]
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "issues": "; ".join(r["issues"])})

    flagged = sum(1 for r in rows if r["issues"])
    print(f"Extracted {len(rows)} URLs, {flagged} with issues. Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
