#!/usr/bin/env python3
"""
status_code_checker.py - Bulk HTTP status code and redirect chain checker.

Reads a list of URLs, follows every redirect hop manually (so each hop is
recorded), and exports a CSV with the full chain, final status and any
issues such as long chains, loops, temporary redirects or errors.

Usage:
    python scripts/status_code_checker.py urls.txt -o status_report.csv
    python scripts/status_code_checker.py urls.txt --workers 10 --max-hops 10
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests

DEFAULT_UA = "Mozilla/5.0 (compatible; SEOStatusChecker/1.0; +https://example.com/bot)"
PERMANENT = {301, 308}
TEMPORARY = {302, 303, 307}


@dataclass
class Result:
    """Outcome of checking one starting URL."""

    url: str
    chain: list[tuple[str, int | str]] = field(default_factory=list)
    final_url: str = ""
    final_status: int | str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def hops(self) -> int:
        # Every entry except the last one is a redirect hop.
        return max(len(self.chain) - 1, 0)

    def as_row(self) -> dict[str, object]:
        first_status = self.chain[0][1] if self.chain else ""
        return {
            "url": self.url,
            "status": first_status,
            "final_url": self.final_url,
            "final_status": self.final_status,
            "hops": self.hops,
            "redirect_chain": " -> ".join(f"{u} [{s}]" for u, s in self.chain),
            "issues": "; ".join(self.issues),
        }


def check_url(url: str, session: requests.Session, max_hops: int, timeout: float) -> Result:
    """Follow redirects one hop at a time and record each step."""
    result = Result(url=url)
    current = url
    seen: set[str] = set()

    for _ in range(max_hops + 1):
        if current in seen:
            result.issues.append("Redirect loop")
            break
        seen.add(current)

        try:
            # HEAD is cheaper, but many servers handle it badly, so fall back to GET.
            resp = session.head(current, allow_redirects=False, timeout=timeout)
            if resp.status_code in (405, 501) or resp.status_code >= 500:
                resp = session.get(current, allow_redirects=False, timeout=timeout, stream=True)
                resp.close()
        except requests.RequestException as exc:
            result.chain.append((current, "ERROR"))
            result.issues.append(f"Request failed: {exc.__class__.__name__}")
            break

        status = resp.status_code
        result.chain.append((current, status))

        if 300 <= status < 400 and "Location" in resp.headers:
            if status in TEMPORARY:
                result.issues.append(f"Temporary redirect ({status}) at hop {len(result.chain)}")
            current = urljoin(current, resp.headers["Location"])
            continue
        break
    else:
        result.issues.append(f"Exceeded {max_hops} redirects")

    last_url, last_status = result.chain[-1]
    result.final_url, result.final_status = last_url, last_status

    if result.hops > 1:
        result.issues.append(f"Redirect chain ({result.hops} hops)")
    if isinstance(last_status, int):
        if 400 <= last_status < 500:
            result.issues.append(f"Client error {last_status}")
        elif last_status >= 500:
            result.issues.append(f"Server error {last_status}")
    if result.chain and str(result.chain[0][0]).startswith("http://") and result.final_url.startswith("http://"):
        result.issues.append("Not redirected to HTTPS")
    return result


def read_urls(path: str) -> list[str]:
    """Read one URL per line, ignoring blanks, comments and duplicates."""
    urls: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and line not in urls:
                urls.append(line)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk status code and redirect chain checker.")
    parser.add_argument("input", help="Text file with one URL per line")
    parser.add_argument("-o", "--output", default="status_report.csv", help="CSV output path")
    parser.add_argument("--workers", type=int, default=5, help="Parallel requests (be polite)")
    parser.add_argument("--max-hops", type=int, default=10, help="Maximum redirects to follow")
    parser.add_argument("--timeout", type=float, default=15, help="Request timeout in seconds")
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    args = parser.parse_args()

    urls = read_urls(args.input)
    if not urls:
        print("No URLs found in input file.", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = args.user_agent

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda u: check_url(u, session, args.max_hops, args.timeout), urls))

    fieldnames = ["url", "status", "final_url", "final_status", "hops", "redirect_chain", "issues"]
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for res in results:
            writer.writerow(res.as_row())

    flagged = sum(1 for r in results if r.issues)
    print(f"Checked {len(results)} URLs, {flagged} with issues. Report: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
