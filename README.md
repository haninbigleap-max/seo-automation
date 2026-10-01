# SEO Automation

Python scripts for the technical SEO checks that are too slow to do by hand: bulk status codes and redirect chains, XML sitemap validation, and on-page meta extraction. Each script reads a list of URLs (or a sitemap) and writes a clean CSV you can filter in Google Sheets or Excel.

## What it does

| Script | What it checks | Output |
|---|---|---|
| `scripts/status_code_checker.py` | HTTP status for each URL, every redirect hop, chains, loops, temporary redirects, HTTP→HTTPS | `status_report.csv` |
| `scripts/sitemap_validator.py` | Every URL in a sitemap or sitemap index (gzip supported): non-200, redirected, noindexed (meta or `X-Robots-Tag`), canonicalised elsewhere | `sitemap_report.csv` |
| `scripts/meta_extractor.py` | Title, meta description, H1, canonical, robots meta: missing, too long or short, duplicate, multiple H1s, noindex | `meta_report.csv` |

## Why it matters

- **Redirect chains and loops** waste crawl budget, slow users down and dilute link signals. They pile up quietly after migrations and CMS changes.
- **Dirty sitemaps** full of redirects, 404s and noindexed URLs send mixed signals and make Search Console coverage data harder to trust.
- **Missing or duplicate titles and descriptions** are among the most common on-page issues, and they're easy to fix once you can see them at scale.

Crawlers like Screaming Frog do all of this too. These scripts are useful when you need a quick check on a specific URL list, want to schedule checks (cron, GitHub Actions), or want to plug the results into your own reporting.

## Folder structure

```
seo-automation/
├── README.md
├── LICENSE
├── requirements.txt
├── examples/
│   └── urls.txt                  # Sample input list
└── scripts/
    ├── status_code_checker.py    # Status codes + redirect chains
    ├── sitemap_validator.py      # Sitemap / sitemap index validation
    └── meta_extractor.py         # Title, description, H1, canonical, robots
```

## How to use it

Requires Python 3.10+.

```bash
git clone https://github.com/haninbigleap-max/seo-automation.git
cd seo-automation
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 1. Status codes and redirect chains

```bash
python scripts/status_code_checker.py examples/urls.txt -o status_report.csv
```

Options: `--workers 5` (parallel requests), `--max-hops 10`, `--timeout 15`, `--user-agent "..."`.

### 2. Sitemap validation

```bash
# Remote sitemap index (child sitemaps are followed automatically)
python scripts/sitemap_validator.py https://example.com/sitemap_index.xml -o sitemap_report.csv

# Local file, only the first 200 URLs
python scripts/sitemap_validator.py ./sitemap.xml --limit 200
```

### 3. Meta extraction

```bash
python scripts/meta_extractor.py examples/urls.txt -o meta_report.csv --title-max 60 --desc-max 160
```

Length thresholds are configurable with `--title-min`, `--title-max`, `--desc-min` and `--desc-max`. Character counts are a guide only. Google truncates by pixel width, and Arabic titles may need different limits than English ones.

**Be polite.** Keep `--workers` low on sites you don't own, and only crawl sites you have permission to audit.

## Example output

`status_report.csv`

| url | status | final_url | final_status | hops | redirect_chain | issues |
|---|---|---|---|---|---|---|
| http://example.com/old-page/ | 301 | https://example.com/ | 200 | 2 | http://example.com/old-page/ [301] -> https://example.com/old-page/ [302] -> https://example.com/ [200] | Temporary redirect (302) at hop 2; Redirect chain (2 hops) |
| https://example.com/en-ae/services/ | 200 | https://example.com/en-ae/services/ | 200 | 0 | https://example.com/en-ae/services/ [200] | |
| https://example.com/ar-sa/old-offer/ | 404 | https://example.com/ar-sa/old-offer/ | 404 | 0 | https://example.com/ar-sa/old-offer/ [404] | Client error 404 |

`sitemap_report.csv`

| url | sitemap | status | redirect_to | meta_robots | x_robots_tag | canonical | issues |
|---|---|---|---|---|---|---|---|
| https://example.com/en-ae/ | https://example.com/sitemap-pages.xml | 200 | | | | https://example.com/en-ae/ | |
| https://example.com/blog/old-post/ | https://example.com/sitemap-posts.xml | 301 | https://example.com/blog/new-post/ | | | | Redirected URL in sitemap |
| https://example.com/thank-you/ | https://example.com/sitemap-pages.xml | 200 | | noindex, follow | | | Noindex via meta robots |

`meta_report.csv` (some columns trimmed)

| url | title | title_length | description_length | h1_count | issues |
|---|---|---|---|---|---|
| https://example.com/en-ae/ | SEO Services in Dubai \| Example | 32 | 142 | 1 | |
| https://example.com/about/ | About | 5 | 0 | 2 | Title too short (<30); Missing meta description; Multiple H1s |
| https://example.com/ar-ae/services/ | Services | 8 | 95 | 1 | Title too short (<30); Duplicate title |

Each script also prints a one-line summary, for example:

```
Checked 250 URLs, 37 with issues. Report: status_report.csv
```

## Ideas for extending

- Run the scripts weekly with GitHub Actions and commit the CSVs to track changes over time.
- Feed `sitemap_report.csv` into the status checker to trace the redirect targets.
- Combine with the [technical-seo-checklist](https://github.com/haninbigleap-max/technical-seo-checklist) to cover the Redirects and Indexation sections.

## License

MIT
